# 接口契约（API Contract）

> **本文与当前代码保持同步**（`backend/app/schemas.py` + `app/api/*.py`）。
> **唯一权威是自动生成的 OpenAPI**：启动后端后访问 **http://127.0.0.1:8770/docs**。
> 本文是给人读的摘要；两者冲突时以 `/docs` 为准。

---

## 0. 通用约定

| 项目 | 约定 |
|---|---|
| 基础路径 | `/api/v1`（健康检查为 `/api/health`） |
| 数据格式 | `application/json; charset=utf-8` |
| **字段命名** | **全部 snake_case**（REST 与 SSE 一致） |
| 时间格式 | ISO 8601 字符串，**UTC**，如 `2026-10-18T14:57:43` |
| 认证方式 | 请求头 `Authorization: Bearer <JWT>` |
| 字符集 | 中文直接以 UTF-8 返回，不转义 |

### 0.1 成功响应：**直接返回数据，不套信封**

```json
{
  "id": 1,
  "title": "2026 学生事务委员会主席选举",
  "status": "open",
  "status_label": "投票进行中"
}
```

### 0.2 失败响应：**`detail` 一律是字符串**

```json
{ "detail": "您已完成投票，不能重复投票" }
```

> ⚠️ FastAPI 默认会把参数校验错误（422）返回成**数组**。
> 本项目在 `app/main.py` 里注册了全局异常处理器，把数组压成一句话：
>
> ```json
> { "detail": "student_id: String should have at least 4 characters；password: String should have at least 8 characters" }
> ```
>
> **前端只需处理 `detail: string` 一种形式**，不要假设它是对象或数组。

### 0.3 状态码

| HTTP | 何时出现 | detail 示例 |
|---|---|---|
| 200 / 201 | 成功 | — |
| 400 | 非法状态迁移 | `不允许从 closed 迁移到 open` |
| 401 | 未登录 / token 失效 / 账号密码错 | `凭证无效或已过期` |
| 403 | 已登录但无权限 / 不在名册内 | `您不在该选举的选民名册内` |
| 404 | 资源不存在 | `选举不存在` |
| 409 | 业务冲突 | `您已完成投票，不能重复投票` / `选举尚未截止，不能计票` |
| 422 | 参数校验失败 | `position_id: Input should be a valid integer` |
| 500 | 服务端异常 | `服务器内部错误` |

---

## 1. 认证 `/auth`

### POST `/api/v1/auth/register`

无需登录。

**请求**
```json
{ "student_id": "HK12345678", "name": "陈大文", "password": "至少8位" }
```
> `student_id` 4–32 字符，会转大写；`password` 至少 8 位。

**响应 201**
```json
{ "id": 101, "student_id": "HK12345678", "name": "陈大文", "role": "VOTER" }
```

**错误**
- `409`：`该学号已注册`
- `422`：`student_id: String should have at least 4 characters`

### POST `/api/v1/auth/login`

**请求**
```json
{ "student_id": "HK12345678", "password": "********" }
```

**响应 200**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": { "id": 101, "student_id": "HK12345678", "name": "陈大文", "role": "VOTER" }
}
```

**错误**：`401` `学号或密码错误`

### GET `/api/v1/auth/me`

需登录。返回 `UserOut`（同上 `user` 字段）。

---

## 2. 选举 `/elections`

### GET `/api/v1/elections`

需登录。**选民只返回自己名册内的选举**；管理员/审计员返回全部。
调用前会自动按时间推进状态（scheduled→open→closed）。

**响应 200**
```json
[
  {
    "id": 1,
    "title": "2026 学生事务委员会主席选举",
    "description": "演示数据",
    "status": "open",
    "status_label": "投票进行中",
    "opens_at": "2026-10-18T08:00:00",
    "closes_at": "2026-10-20T20:00:00",
    "tally_method": "fptp",
    "positions": [
      {
        "id": 1,
        "title": "主席",
        "seats": 1,
        "candidates": [
          { "id": 1, "idx": 0, "name": "陈嘉禾", "party": "学生会" }
        ]
      }
    ],
    "turnout": { "voted": 21, "total": 30, "percent": 70.0 },
    "my_vote_status": "NOT_VOTED"
  }
]
```

| 字段 | 取值 |
|---|---|
| `status` | `scheduled` / `open` / `closed` / `published` |
| `my_vote_status` | `NOT_VOTED` / `VOTED` / `NOT_ELIGIBLE` |
| `tally_method` | `fptp` / `irv` |
| `opens_at` `closes_at` | 可为 `null` |

### GET `/api/v1/elections/{election_id}`

需登录。返回单个 `ElectionOut`。`404` 若不存在。

### POST `/api/v1/elections`

仅 **ADMIN**。

**请求**
```json
{
  "title": "2026 学生会主席选举",
  "description": "",
  "opens_at": "2026-10-20T09:00:00",
  "closes_at": "2026-10-22T18:00:00",
  "tally_method": "fptp",
  "positions": [
    {
      "title": "主席",
      "seats": 1,
      "candidates": [
        { "idx": 0, "name": "陈嘉禾", "party": "学生会" },
        { "idx": 1, "name": "李浩然", "party": "独立" }
      ]
    }
  ]
}
```
**响应 201**：`ElectionOut`（状态为 `scheduled`）

### PATCH `/api/v1/elections/{election_id}/status`

仅 **ADMIN**。**只允许状态机定义的迁移**。

**请求**
```json
{ "status": "closed" }
```
**响应 200**：`ElectionOut`
**错误**
- `400`：`不允许从 closed 迁移到 open；允许: ['published']`
- `404`：`选举不存在`

### GET `/api/v1/elections/{election_id}/integrity`

仅 **ADMIN**。

**响应 200**
```json
{
  "election_id": 1,
  "all_passed": true,
  "checks": [
    { "name": "无重复投票记录", "passed": true, "detail": "未发现同一选民在同一职位重复投票" },
    { "name": "名册已投票数 == 投票记录数", "passed": true, "detail": "名册 21 人 / 记录 21 条" },
    { "name": "选票数 == 投票记录数 == 凭证数", "passed": true, "detail": "主席: 票 21 / 记录 21 / 凭证 21" }
  ]
}
```

---

## 3. 投票 `/votes`

### POST `/api/v1/elections/{election_id}/votes`

需登录（选民）。**服务端校验顺序固定**：
登录 → 名册 → 选举状态为 `open` → 候选合法 → 数据库唯一约束仲裁。

**请求**
```json
{ "position_id": 1, "choice": [2] }
```
- 单选制：`choice` 长度为 1
- 排序复选制：`choice` 按偏好顺序，如 `[2, 0, 1]`

**响应 201**
```json
{
  "receipt_code": "ERYW-JZNV-VASX",
  "cast_at": "2026-10-18T14:38:44",
  "audit_seq": 74
}
```

**错误**

| HTTP | 场景 | detail |
|---|---|---|
| 401 | 未登录 | `未登录或凭证缺失` |
| 403 | 不在名册 / 资格取消 | `您不在该选举的选民名册内` |
| 409 | 选举未开放 | `选举状态为 closed（已截止），不接受投票` |
| 409 | 重复投票 | `您已完成投票，不能重复投票` |
| 422 | 候选越界 | `候选序号 99 越界（共 5 名候选）` |

### GET `/api/v1/receipts/{code}`

**无需登录**。

**响应 200**
```json
{
  "found": true,
  "message": "该选票已计入，且计入后未被修改",
  "election_title": "2026 学生事务委员会主席选举",
  "counted": true,
  "cast_at": "2026-10-18T14:38:44"
}
```

> ⚠️ **绝不返回** `choice` / 候选人信息。
> 否则凭证可被用来向第三方"证明"投票选择，为贿选与胁迫留下空间。

---

## 4. 结果 `/results`

### GET `/api/v1/elections/{election_id}/results`

无需登录。**投票进行中不公开**。

**未截止时**
```json
{
  "published": false,
  "election_id": 1,
  "status": "open",
  "message": "选举尚未截止，计票结果不予公开（防止影响投票行为）",
  "results": []
}
```

**已截止 / 已公布**
```json
{
  "published": true,
  "election_id": 3,
  "status": "published",
  "message": "",
  "results": [
    {
      "position_id": 3,
      "position_title": "首选方案",
      "tally_method": "irv",
      "tally_label": "排序复选制 (Instant Runoff)",
      "ballot_count": 26,
      "counts": { "0": 14, "1": 0, "2": 12 },
      "winner_idx": 0,
      "winner_name": "方案甲：全面回收",
      "digest": "52872baa7dc5713b4692200eddca9a15...",
      "note": "第 2 轮过半数胜出",
      "rounds": [
        { "remaining": [0, 1, 2], "counts": { "0": 11, "1": 6, "2": 9 }, "exhausted": 0, "total": 26 },
        { "remaining": [0, 2], "counts": { "0": 14, "2": 12 }, "exhausted": 0, "total": 26 }
      ]
    }
  ]
}
```

> `winner_name` 可能为 `null`（并列）；`rounds` 只有 IRV 才有内容。

### POST `/api/v1/elections/{election_id}/results/publish`

仅 **ADMIN**，且选举须为 `closed`。

**响应 200**：同上的 `ResultsResponse`
**错误**
- `409`：`选举尚未截止，不能计票公示`

---

## 5. 审计 `/audit`

仅 **ADMIN / AUDITOR**。

### GET `/api/v1/audit/verify`
```json
{
  "ok": true,
  "length": 75,
  "first_bad_seq": null,
  "message": "审计链完整：共 75 条记录，链尾 d9a4dacf36f7d3e3…",
  "chain_tip": "d9a4dacf..."
}
```

### GET `/api/v1/audit/entries?limit=50`
```json
[
  { "seq": 75, "op": "ballot.cast", "actor": "HK100025",
    "payload": { "election_id": 1, "position_id": 1, "user_id": 26,
                 "receipt_code": "ERYW-JZNV-VASX", "ballot_id": 22 },
    "ts": "2026-10-18T14:38:44", "hash": "3b58643b5fcd90c62594…" }
]
```
> 审计日志**不包含**投票选择内容（写 `choice` 会直接抛异常）。

---

## 6. 实时推送（SSE）`/events`

> 浏览器用原生 `EventSource` 订阅。**EventSource 不能自定义请求头**，
> 因此这两个端点**不需要登录** —— 也正因如此，推送内容严格限制为聚合数据。

### 帧格式

```
event: open
data: {"channel": "turnout", "election_id": 1}

event: turnout
data: {"election_id": 1, "voted": 21, "total": 30, "percent": 70.0}

event: heartbeat
data: {"ts": 12345.6}
```

| 事件名 | 含义 |
|---|---|
| `open` | 连接已建立（首帧） |
| `turnout` | 投票率更新 |
| `results` | 结果发布（仅 `results` 频道） |
| `heartbeat` | 心跳，默认 15 秒一次 |

### GET `/api/v1/events/turnout?election_id={id}`

可省略 `election_id` 表示订阅所有选举。

- `Content-Type: text/event-stream`
- `Cache-Control: no-cache`
- `X-Accel-Buffering: no`（让 Nginx 不缓冲）

**事件**：`turnout`，payload 见上（**只有投票率，没有各候选人票数**）。

### GET `/api/v1/events/results?election_id={id}`

**仅在选举截止后**会有事件，payload：

```
event: results
data: {"election_id": 3, "status": "published",
       "results": [{"position_id": 3, "counts": {"0":14,"2":12},
                    "winner_idx": 0, "digest": "52872..."}]}
```

**前端注意**：`EventSource` 自带断线重连；UI 上应提示"重连中"，不要当作致命错误。

---

## 7. 健康检查

### GET `/api/health`

无需登录。
```json
{
  "status": "ok",
  "database": "sqlite+aiosqlite",
  "redis": "in-memory",
  "audit_chain_ok": true,
  "audit_entries": 75,
  "audit_message": "审计链完整：共 75 条记录…"
}
```

---

## 8. 前端联调 Checklist

- [ ] 所有请求统一前缀 `/api/v1`
- [ ] 字段名一律 snake_case，**不要**自动转 camelCase
- [ ] token 放 `Authorization: Bearer <token>`
- [ ] 401 → 清除 token 并跳登录页
- [ ] 409 `DUPLICATE_VOTE` → 显示友好文案，而非技术错误
- [ ] 422 的 `detail` 已是字符串，直接展示即可
- [ ] SSE 断线显示"重连中"，不要报错弹窗
- [ ] `winner_name`、`opens_at` 等字段可能为 `null`，渲染前判空

---

## 9. 变更记录

| 日期 | 修改内容 | 影响 |
|---|---|---|
| 2026-10-18 | 初版与实现对齐（去掉 `{success, data}` 信封） | 全部 |
| 2026-10-18 | SSE 字段由 camelCase 改为 snake_case | 前端 `useTurnout.ts`、`events.py` |
| 2026-10-18 | 422 错误 `detail` 由数组改为字符串 | `main.py` 全局异常处理器、`api.ts` |
