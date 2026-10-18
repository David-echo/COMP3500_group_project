# 系统流程与技术栈详图

> COMP 3500SEF / 8500SEF — 选举管理与投票系统
> 后端已定：**Python + FastAPI**
>
> 本文的图**在每个环节标注了所用的语言 / 框架 / 组件**，可直接放进报告的「设计」章节，
> 也适合在进度评审时讲解。

---

## 一、技术栈全景（按层标注语言）

```mermaid
flowchart TB
    subgraph L1["① 表示层 — 用户界面"]
        direction LR
        V1["选民端<br/>Vue 3 + TypeScript"]
        V2["管理端<br/>Vue 3 + TypeScript"]
        V3["图表<br/>ECharts 5"]
    end

    subgraph L2["② 用户通信层"]
        direction LR
        N1["Nginx<br/>静态资源 + 反向代理"]
        N2["HTTP / REST + JSON<br/>AJAX: Axios"]
        N3["SSE: EventSource<br/>text/event-stream"]
    end

    subgraph L3["③ 应用逻辑层 — Python 3.11+"]
        direction TB
        A1["FastAPI 路由层<br/>APIRouter"]
        A2["Pydantic v2 模型<br/>请求 / 响应校验"]
        A3["业务服务层<br/>投票 · 状态机 · 计票"]
        A4["SQLAlchemy 2.0 (async)<br/>事务边界"]
    end

    subgraph L4["④ 数据层"]
        direction LR
        D1[("PostgreSQL 16<br/>唯一约束 · 事务")]
        D2[("Redis 7<br/>会话 · 缓存 · Pub/Sub")]
    end

    V1 --> N2
    V2 --> N2
    V3 --> V1
    N2 --> A1
    N3 -.-> A1
    A1 --> A2
    A2 --> A3
    A3 --> A4
    A4 --> D1
    A3 --> D2
    N1 --> N2
```

---

## 二、投票主流程（逐步标注语言与框架）

这是**一张图讲清整个系统怎么工作**：从浏览器点击到数据落库，每一步都标明用什么技术。

```mermaid
flowchart TD
    Start([选民打开浏览器]) --> S1

    subgraph FE1["前端 · Vue 3 + TypeScript"]
        S1["输入学号与 PIN<br/>Vue 表单 + 前端校验"]
        S1 --> S2["Axios POST /api/v1/auth/login"]
    end

    subgraph BE1["后端 · FastAPI"]
        S2 --> S3["Pydantic 校验请求体"]
        S3 --> S4["查询 voter_roll 表<br/>SQLAlchemy async + asyncpg"]
        S4 --> S5{"bcrypt 校验 PIN<br/>passlib"}
        S5 -->|失败| S6["返回 401<br/>统一错误码"]
        S5 -->|成功| S7["签发 JWT<br/>python-jose"]
    end

    S6 --> Err1([前端显示错误提示])
    S7 --> S8

    subgraph FE2["前端 · Vue 3"]
        S8["存 token 到 Pinia<br/>跳转选举列表页"]
        S8 --> S9["Axios GET /api/v1/elections<br/>带上 Authorization 头"]
    end

    subgraph BE2["后端 · FastAPI"]
        S9 --> S10["依赖注入校验 JWT<br/>Depends(get_current_user)"]
        S10 --> S11["SQLAlchemy 查询<br/>该选民名册内的选举"]
        S11 --> S12["Pydantic 序列化<br/>返回 ElectionResponse 列表"]
    end

    S12 --> S13

    subgraph FE3["前端 · Vue 3"]
        S13["渲染选举卡片<br/>显示状态徽章与投票率"]
        S13 --> S14["点击选举 → Vue Router 跳转"]
        S14 --> S15["展示候选人<br/>单选 / 点击排序"]
        S15 --> S16["确认弹窗<br/>Vue 组件"]
        S16 --> S17["Axios POST /api/v1/elections/:id/votes"]
    end

    subgraph BE3["后端 · FastAPI — 单事务内完成"]
        S17 --> S18["Pydantic 校验 choice 合法"]
        S18 --> S19["BEGIN 事务<br/>SQLAlchemy AsyncSession"]
        S19 --> S20{"选举状态 == open?<br/>状态机校验"}
        S20 -->|否| S21["409 ELECTION_NOT_OPEN"]
        S20 -->|是| S22{"选民在名册且未投票?"}
        S22 -->|否| S23["403 FORBIDDEN"]
        S22 -->|是| S24["INSERT ballots<br/>仅存 anon_id + 加密选择"]
        S24 --> S25["INSERT votes_log<br/>UNIQUE 约束仲裁"]
        S25 --> S26{"唯一约束冲突?"}
        S26 -->|是| S27["ROLLBACK<br/>409 DUPLICATE_VOTE"]
        S26 -->|否| S28["INSERT receipts<br/>生成凭证码"]
        S28 --> S29["UPDATE voter_roll<br/>has_voted = true"]
        S29 --> S30["写入审计日志<br/>哈希链：prev_hash + 内容"]
        S30 --> S31["COMMIT"]
    end

    S21 --> Err2([前端友好提示])
    S23 --> Err2
    S27 --> Err2

    S31 --> S32

    subgraph FE4["前端 · Vue 3"]
        S32["展示凭证码<br/>复制按钮 + 截图提示"]
        S32 --> S33["Axios GET /api/v1/receipts/:code<br/>可选核验"]
        S32 --> S34["EventSource 订阅<br/>/api/v1/events/turnout"]
    end

    subgraph BE4["后端 · FastAPI"]
        S33 --> S35["查询 receipts + ballots<br/>仅返回 counted 状态"]
        S34 --> S36["StreamingResponse<br/>SSE 推送投票率"]
        S36 --> S37[("Redis Pub/Sub<br/>多实例广播")]
    end

    S35 --> S38(["显示：已计入，未显示选择"])
    S36 --> S39(["前端图表实时更新"])
```

---

## 三、投票事务的内部时序（后端细节）

> 这一节对应报告里的「设计」与「事务一致性」，是评审最容易追问的地方。

```mermaid
sequenceDiagram
    autonumber
    actor V as 选民（浏览器）
    participant FE as Vue 3 + TypeScript
    participant RT as FastAPI 路由层
    participant SC as 业务服务（Python）
    participant DB as PostgreSQL 16

    V->>FE: 点击「确认投票」
    FE->>FE: Vue 校验：至少选 1 项
    FE->>RT: POST /api/v1/elections/1/votes<br/>Authorization: Bearer JWT
    RT->>RT: Pydantic 校验 VoteRequest

    RT->>SC: cast_ballot(user, election_id, choice)
    SC->>DB: BEGIN TRANSACTION
    SC->>DB: SELECT status FROM elections WHERE id=1
    DB-->>SC: status = 'open'

    alt 状态不是 open
        SC-->>RT: raise ElectionNotOpen
        RT-->>FE: 409 ELECTION_NOT_OPEN
        FE-->>V: 「该选举已截止」
    else 状态为 open
        SC->>DB: SELECT eligible,has_voted FROM voter_roll
        DB-->>SC: eligible=true, has_voted=false
        SC->>SC: 加密选择（HMAC 派生密钥）
        SC->>DB: INSERT INTO ballots(anon_id, choice_enc)
        SC->>DB: INSERT INTO votes_log(position_id,user_id)<br/>⚡ UNIQUE 约束在此仲裁

        alt 唯一约束冲突（并发/重复）
            DB-->>SC: IntegrityError
            SC->>DB: ROLLBACK
            SC-->>RT: raise DuplicateVote
            RT-->>FE: 409 DUPLICATE_VOTE
            FE-->>V: 「您已完成投票」
        else 插入成功
            SC->>DB: INSERT INTO receipts(code, ballot_id)
            SC->>DB: UPDATE voter_roll SET has_voted=true
            SC->>DB: INSERT INTO audit_log<br/>(prev_hash,op,payload,hash)
            SC->>DB: COMMIT
            SC-->>RT: receipt_code
            RT-->>FE: 201 + {receiptCode}
            FE-->>V: 显示凭证码
        end
    end
```

---

## 四、部署拓扑（物理视图）

```mermaid
flowchart LR
    subgraph Client["客户端"]
        BROWSER["浏览器<br/>Chrome / Safari / Edge"]
    end

    subgraph Server["服务器（Docker Compose）"]
        NGINX["Nginx 容器<br/>:80 / :443<br/>静态文件 + 反代"]
        subgraph APP["应用容器"]
            UV["Uvicorn<br/>ASGI 服务器"]
            FA["FastAPI<br/>Python 3.11+"]
        end
        PG[("PostgreSQL 容器<br/>:5432")]
        RD[("Redis 容器<br/>:6379")]
    end

    BROWSER -->|HTTPS| NGINX
    NGINX -->|静态资源| BROWSER
    NGINX -->|/api/*| UV
    UV --> FA
    FA -->|asyncpg :5432| PG
    FA -->|redis-py :6379| RD
    BROWSER -.->|SSE<br/>长连接| NGINX
```

---

## 五、技术选型速查表（讲给导师用）

| 环节 | 语言 / 技术 | 为什么用它 |
|---|---|---|
| 用户界面 | **TypeScript + Vue 3** | 类型安全 + 组件化，适合表单与列表 |
| 构建工具 | **Vite 5** | 冷启动快，HMR 体验好 |
| 状态管理 | **Pinia** | 管理登录态与选举数据，比 Vuex 简洁 |
| 图表 | **ECharts 5** | 计票柱状图、逐轮淘汰可视化 |
| HTTP 调用 | **Axios** | 拦截器统一处理 401 / 错误码 |
| 实时推送 | **EventSource（SSE）** | 服务器单向推投票率，自带重连 |
| 后端框架 | **Python 3.11 + FastAPI** | 异步、自动 OpenAPI、Pydantic 契约即文档 |
| 请求校验 | **Pydantic v2** | 请求/响应模型即接口契约 |
| 数据访问 | **SQLAlchemy 2.0 async** | 显式事务边界，能精确控制 COMMIT/ROLLBACK |
| 数据库驱动 | **asyncpg** | PostgreSQL 异步驱动，性能好 |
| 数据库迁移 | **Alembic** | schema 版本化，团队协作必需 |
| 主数据库 | **PostgreSQL 16** | **唯一约束**是"一人一票"的最终保证 |
| 缓存 | **Redis 7** | 会话 + 结果缓存 + SSE 多实例 Pub/Sub |
| 鉴权 | **python-jose + passlib[bcrypt]** | JWT 签发与密码哈希 |
| 测试 | **pytest + pytest-asyncio + httpx** | 单元测试 + 异步接口测试 |
| 容器 | **Docker Compose** | 一条命令起 PostgreSQL + Redis |

---

## 六、给成员的分工落点（对应 7 人分工表）

| 成员 | 负责环节 | 用到的语言/技术 | 产出文件 |
|---|---|---|---|
| 1 | 选民端页面 | TypeScript + Vue 3 + Pinia | `frontend/src/views/Voter*` |
| 2 | 管理端页面 | TypeScript + Vue 3 + ECharts | `frontend/src/views/Admin*` |
| 3 | 认证与权限 | Python + FastAPI + python-jose | `backend/api/auth.py` |
| 4 | 选举与投票 | Python + FastAPI + SQLAlchemy | `backend/api/elections.py` |
| 5 | 数据库设计 | PostgreSQL + Alembic | `backend/db/`、`migrations/` |
| 6 | 功能与界面测试 | 手测 + Playwright（可选） | `tests/e2e/` |
| 7 | 接口与集成测试 | pytest + pytest-asyncio + httpx | `tests/api/` |
