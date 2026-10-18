# 接口契约（API Contract）

> **作用**：冻结前后端接口，让成员 1/2（前端）、3/4（后端）、5（数据库）可以**并行开发而不互相阻塞**。
> **规则**：本文件一旦冻结，任何修改都必须通知全体；修改需在下方「变更记录」登记。

---

## 0. 通用约定

| 项目 | 约定 |
|---|---|
| 基础路径 | `/api/v1` |
| 数据格式 | `application/json; charset=utf-8` |
| 认证方式 | 会话 Cookie 或 `Authorization: Bearer <token>` |
| 时间格式 | ISO 8601（`2026-10-01T09:00:00Z`），全部用 UTC |
| 分页参数 | `?page=1&size=20`，响应含 `total` |
| 命名风格 | JSON 字段 **camelCase**；数据库字段 **snake_case** |

### 统一响应结构

**成功**
```json
{ "success": true, "data": { }, "message": null }
```

**失败**
```json
{ "success": false, "error": { "code": "DUPLICATE_VOTE", "message": "您已完成投票" } }
```

### 统一错误码

| HTTP | code | 含义 |
|---|---|---|
| 400 | `INVALID_PARAM` | 参数缺失或格式错误 |
| 401 | `UNAUTHENTICATED` | 未登录或会话过期 |
| 403 | `FORBIDDEN` | 已登录但无权限 / 不在名册内 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `ELECTION_NOT_OPEN` | 选举不在进行中 |
| 409 | `DUPLICATE_VOTE` | 重复投票 |
| 422 | `INVALID_CHOICE` | 候选人选择越界 |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 500 | `INTERNAL_ERROR` | 服务端错误（不返回堆栈） |

---

## 1. 认证（成员 3）

### POST `/api/v1/auth/register`

**请求**
```json
{ "studentId": "HK12345678", "name": "陈大文", "password": "********" }
```

**规则**
- `studentId` 唯一，重复返回 `409 DUPLICATE`
- 密码最短 8 位，使用 bcrypt/argon2 加盐哈希存储
- 是否需要管理员审核 → **待定（需在 SRS 中明确）**

**响应 201**
```json
{ "success": true, "data": { "userId": 101, "studentId": "HK12345678" } }
```

### POST `/api/v1/auth/login`
```json
{ "studentId": "HK12345678", "password": "********" }
```
**响应 200**
```json
{ "success": true, "data": { "userId": 101, "role": "VOTER", "name": "陈大文" } }
```

### POST `/api/v1/auth/logout` → 204

### GET `/api/v1/auth/me`
```json
{ "success": true, "data": { "userId": 101, "role": "VOTER", "name": "陈大文" } }
```

---

## 2. 选举（成员 4）

### GET `/api/v1/elections`
返回当前用户可见的选举（选民只返回名册内的）。

**响应 200**
```json
{
  "success": true,
  "data": [
    {
      "electionId": 1,
      "title": "2026 学生事务委员会主席选举",
      "status": "open",
      "opensAt": "2026-10-01T09:00:00Z",
      "closesAt": "2026-10-03T18:00:00Z",
      "tallyMethod": "FPTP",
      "positions": [
        {
          "positionId": 1,
          "title": "主席",
          "candidates": [
            { "candidateId": 1, "name": "陈嘉禾", "party": "学生会" },
            { "candidateId": 2, "name": "李浩然", "party": "独立" }
          ]
        }
      ],
      "myVoteStatus": "NOT_VOTED",
      "turnout": { "voted": 35, "total": 60, "percent": 58.3 }
    }
  ]
}
```

> `status` 取值：`scheduled` | `open` | `closed` | `published`
> `myVoteStatus` 取值：`NOT_VOTED` | `VOTED` | `NOT_ELIGIBLE`

### GET `/api/v1/elections/{electionId}` → 单个选举（结构同上）

### POST `/api/v1/elections` （仅 ADMIN，成员 2 的前端依赖）
```json
{
  "title": "2026 学生会主席选举",
  "description": "说明文字",
  "opensAt": "2026-10-01T09:00:00Z",
  "closesAt": "2026-10-03T18:00:00Z",
  "tallyMethod": "FPTP"
}
```

### POST `/api/v1/elections/{id}/candidates` （仅 ADMIN）
```json
{ "positionId": 1, "name": "陈嘉禾", "party": "学生会", "order": 1 }
```

### PATCH `/api/v1/elections/{id}/status` （仅 ADMIN）
```json
{ "status": "closed" }
```
**规则**：只允许状态机定义的迁移（`scheduled→open→closed→published`），非法迁移返回 `400 INVALID_TRANSITION`。

---

## 3. 投票（成员 4）⭐ 核心接口

### POST `/api/v1/elections/{electionId}/votes`

**请求**
```json
{ "positionId": 1, "choice": [1] }
```
- 单选制：`choice` 长度为 1
- 排序复选制：`choice` 为按偏好排序的候选人数组

**服务端校验顺序（必须严格按此顺序）**
1. 会话有效 → 否则 `401`
2. 在名册内 → 否则 `403`
3. 选举状态为 `open` → 否则 `409 ELECTION_NOT_OPEN`
4. 候选人合法（不越界、不重复）→ 否则 `422 INVALID_CHOICE`
5. 写入选票 → 若唯一约束冲突 → `409 DUPLICATE_VOTE`
6. 生成凭证码

**响应 201**
```json
{ "success": true, "data": { "receiptCode": "5KWV-7N5F-V6SM", "castAt": "2026-10-02T10:15:00Z" } }
```

**关键约束（写进报告）**
- 全流程在**单个事务**内完成；任一步失败**全部回滚**
- 重复投票由**数据库唯一约束**兜底，不依赖应用层查询
- 响应中**不得包含**任何与「用户 ↔ 选择」可关联的信息

### GET `/api/v1/receipts/{code}` （凭证核验，无需登录）

**响应 200**
```json
{
  "success": true,
  "data": {
    "found": true,
    "electionTitle": "2026 学生事务委员会主席选举",
    "counted": true,
    "castAt": "2026-10-02T10:15:00Z"
  }
}
```

> ⚠️ **严禁**在此响应中返回 `choice` / `candidateId` / 任何可推断选择的信息。
> 理由：否则凭证可被用于向第三方"证明"投票选择，为贿选与胁迫留下空间。

---

## 4. 结果与实时推送（成员 4）

### GET `/api/v1/elections/{id}/results`
**仅当** `status` 为 `closed` 或 `published` 时可用。

**响应 200**
```json
{
  "success": true,
  "data": {
    "electionId": 3,
    "positionId": 1,
    "tallyMethod": "IRV",
    "ballotCount": 44,
    "counts": { "1": 20, "2": 24 },
    "winnerCandidateId": 2,
    "digest": "11e8324e69429bd0d50a0c96e276e2ef...",
    "publishedAt": "2026-10-04T12:00:00Z",
    "rounds": [
      { "round": 1, "remaining": [1, 2, 3], "counts": { "1": 13, "2": 19, "3": 12 } },
      { "round": 2, "remaining": [1, 2], "counts": { "1": 20, "2": 24 } }
    ]
  }
}
```

### GET `/api/v1/events/turnout?electionId={id}` （SSE）

**事件流格式**
```
event: turnout
data: {"electionId":1,"voted":35,"total":60,"percent":58.3}

event: heartbeat
data: {"ts":"2026-10-02T10:15:00Z"}
```

> ⚠️ **重要设计决定（必须写进 SRS / 报告）**
> 投票**进行中**的 SSE **只推送投票率（聚合值）**，**不推送各候选人票数**。
> 原因：真实选举中公布实时票数会引导后续投票行为，损害公平性。
> 候选人票数仅在 `status = closed/published` 后通过 `/results` 或结果 SSE 提供。

### GET `/api/v1/events/results?electionId={id}` （SSE，仅截止后）

```
event: result
data: {"electionId":3,"positionId":1,"counts":{"1":20,"2":24},"winnerCandidateId":2}
```

---

## 5. 审计（成员 3 / 5）

### GET `/api/v1/audit/entries?limit=50` （仅 ADMIN / AUDITOR）
```json
{
  "success": true,
  "data": [
    { "seq": 120, "op": "VOTE_CAST", "actor": "HK12345678", "ts": "2026-10-02T10:15:00Z", "hash": "3b58643b..." }
  ]
}
```

### GET `/api/v1/audit/verify` （仅 ADMIN / AUDITOR）
```json
{ "success": true, "data": { "ok": true, "length": 120, "firstBadSeq": null, "message": "审计链完整" } }
```

---

## 6. 完整性校验（成员 5 / 7）

### GET `/api/v1/integrity/{electionId}`
```json
{
  "success": true,
  "data": {
    "allPassed": true,
    "checks": [
      { "name": "无重复投票记录", "passed": true },
      { "name": "选票数 = 投票记录数 = 凭证数", "passed": true },
      { "name": "已投票人数 = 投票记录数", "passed": true }
    ]
  }
}
```

---

## 7. 变更记录

| 日期 | 修改内容 | 提出人 | 影响范围 |
|---|---|---|---|
| | 初始冻结 | | 全体 |

---

## 8. 前端联调 Checklist（给成员 1/2）

- [ ] 所有请求统一走 `/api/v1` 前缀
- [ ] 统一处理 `success: false` 的错误结构
- [ ] 401 自动跳转登录页
- [ ] 409 `DUPLICATE_VOTE` 显示友好提示，而非技术错误
- [ ] SSE 断线后显示"重连中"，并自动重连
- [ ] 错误提示文案不得暴露内部字段名
