# 选举管理与投票系统 (Election Management & Voting System)

> COMP 3500SEF / 8500SEF / S350F — 软件工程 小组项目
> 选题 2：Election Management and Voting System

一个**可运行、可测试、可审计**的选举系统。工程重点不是界面，而是解决选举领域最核心的矛盾：

> **匿名性要求查不出谁投了谁，可审计性又要求能查出有没有人作弊 —— 这两个要求互相打架。**

我们用**数据结构**和**数据库约束**同时满足它们，而不是靠"我们承诺不去查日志"。

---

## 一、技术栈

| 层次 | 技术 | 说明 |
|---|---|---|
| 前端 | **Vue 3 + TypeScript** | Vite · Pinia · Vue Router · ECharts · Axios |
| 实时推送 | **SSE（Server-Sent Events）** | 浏览器 `EventSource` ↔ FastAPI `StreamingResponse` |
| 后端 | **Python 3.11+ + FastAPI** | Pydantic v2 · SQLAlchemy 2.0 (async) · Uvicorn |
| 数据库 | **PostgreSQL 16** | 唯一约束 + 事务保证"一人一票" |
| 缓存 | **Redis 7** | 会话 / 结果缓存 / SSE 多实例发布订阅 |

> 开发环境无 PostgreSQL / Redis 时自动回退到 **SQLite + 进程内发布订阅**，
> 功能完全一致，只是不支持多实例部署。切换只需改 `.env` 一行。

---

## 二、快速开始

### 后端（无需安装数据库）

```bash
cd backend
pip install -r requirements.txt
python -m app.seed                    # 生成演示数据
uvicorn app.main:app --reload --port 8770
```

- API 文档：**http://127.0.0.1:8770/docs**（FastAPI 自动生成，可在线调试）

### 前端

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

> Vite 已配置 `/api` 代理到 `127.0.0.1:8770`，打开 5173 即可，无需处理跨域。

### 演示账号

| 角色 | 学号 | 密码 |
|---|---|---|
| 管理员 | `ADMIN001` | `admin12345` |
| 审计员 | `AUDIT001` | `audit12345` |
| 选民 | `HK100000` – `HK100029`（共 30 个） | `voter12345` |

### 切换到 PostgreSQL + Redis

```bash
docker compose up -d                  # 起 PostgreSQL 16 + Redis 7
cp .env.example .env                  # 按需修改 DATABASE_URL / REDIS_URL
cd backend && python -m app.seed
```

---

## 三、目录结构

```
.
├── backend/                  正式版后端（FastAPI）
│   ├── app/
│   │   ├── main.py             应用组装（不写业务逻辑）
│   │   ├── config.py           唯一读取环境变量的地方
│   │   ├── db.py               异步引擎与会话
│   │   ├── models.py           ORM 模型 + 唯一约束
│   │   ├── schemas.py          Pydantic 请求/响应（自动 OpenAPI）
│   │   ├── security.py         bcrypt / JWT / AES-GCM 选票加密
│   │   ├── deps.py             鉴权依赖（角色控制）
│   │   ├── domain/             纯逻辑：状态机 / 哈希链 / 计票策略
│   │   ├── services/           投票 / 结果 / 审计 / 发布订阅
│   │   ├── api/                auth / elections / votes / results / audit / events
│   │   └── seed.py             演示数据
│   ├── tests/                  40 个测试
│   └── requirements.txt
├── frontend/                 正式版前端（Vue 3 + TypeScript）
│   └── src/
│       ├── views/              4 步流程 + 管理台
│       ├── stores/             Pinia 登录态
│       ├── composables/        SSE 订阅
│       └── api.ts              REST 客户端与类型定义
├── docs/                     项目文档
│   ├── 01-project-plan.md      业务流程 / 功能拆解 / 技术选型
│   ├── 02-flowchart-with-tech-stack.md
│   ├── diagrams/               流程与架构图（simple 白话版 / detailed 详细版）
│   └── templates/              SRS / ADR / API 契约 / 会议纪要模板
├── prototype/                早期探索原型（Flask + SQLite，仅作历史留存）
├── docker-compose.yml        PostgreSQL + Redis
└── .env.example
```

> `prototype/` 是项目早期用 Flask + SQLite 快速做的可运行原型，
> 作用是在正式开发前验证"这个选题长什么样"（对应课程 Lecture 2 的原型法）。
> 它**不是**最终交付代码，保留是为了记录开发过程。

---

## 四、两个核心设计

### ① 匿名性：选票与选民册**物理隔离**

```
voter_roll   谁投了      user_id / has_voted      ※ 没有 ballot_id
ballots      投了什么    anon_id / choice_enc     ※ 没有 user_id
receipts     凭证        code → 只发给选民本人
votes_log    一人一票    UNIQUE(position_id, user_id)
```

系统里**不存在**任何能把"某选民"与"其选择"关联起来的字段或外键。
匿名性不是承诺，而是数据模型里没有这条边 —— 这一点有测试直接断言表结构。

### ② 一人一票：由**数据库唯一约束**仲裁

投票时**不写**"先查询是否已投票，再插入"（check-then-act，并发下会双投），
而是直接插入带 `UNIQUE(position_id, user_id)` 的记录，让数据库裁决。

并发测试证明：同一选民并发提交 8 次，**恰好 1 次成功**。

---

## 五、SSE 实时推送的约束

| 频道 | 内容 | 何时可推送 |
|---|---|---|
| `/api/v1/events/turnout` | 投票率（聚合值） | 投票进行中 |
| `/api/v1/events/results` | 各候选人票数 | **仅选举截止后** |

> 真实选举在投票期间不公布各候选人票数 —— 公布会引导后续投票行为，损害公平性。
> 这一条写进领域需求（DR-1），前后端都遵守：投票期间后端**不提供**票数接口，
> 前端即使想显示也拿不到数据。

---

## 六、测试

```bash
cd backend
pytest -q                        # 40 个测试
pytest tests/test_api.py -q      # 接口与集成
```

| 层次 | 覆盖内容 |
|---|---|
| 领域层 | 状态机全部迁移、FPTP / IRV 计票、哈希链篡改与删除检测 |
| 接口层 | 登录、投票、重复投票、凭证核验、状态门控、越权访问 |
| 不变量 | 选票数 == 投票记录数 == 凭证数 |
| 并发 | 同一选民并发投票只有 1 票成功 |
| SSE | 协议头、首帧格式、发布订阅投递 |

---

## 七、API 一览（完整文档见 `/docs`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录，返回 JWT |
| GET | `/api/v1/auth/me` | 当前用户 |
| GET | `/api/v1/elections` | 可参与的选举列表 |
| POST | `/api/v1/elections` | 创建选举（管理员） |
| PATCH | `/api/v1/elections/{id}/status` | 状态变更（仅状态机允许的迁移） |
| POST | `/api/v1/elections/{id}/votes` | 投票 |
| GET | `/api/v1/receipts/{code}` | 凭证核验（不返回选择内容） |
| GET | `/api/v1/elections/{id}/results` | 结果（截止后才公开） |
| POST | `/api/v1/elections/{id}/results/publish` | 计票并公示（管理员） |
| GET | `/api/v1/elections/{id}/integrity` | 完整性不变量校验 |
| GET | `/api/v1/audit/verify` | 审计哈希链校验 |
| GET | `/api/v1/events/turnout` | SSE：投票率 |
| GET | `/api/v1/events/results` | SSE：结果（仅截止后） |

---

## 八、诚实声明（保证边界）

- **选票加密**是应用层 AES-GCM，用于防止"只读数据库的人直接看到选择"；
  **不是**端到端可验证加密（如 Paillier 同态计票），不声称达到真实选举的密码学强度。
- **哈希链**只能**检测**篡改，不能防止能重算整条链的攻击者 ——
  除非把链尾哈希对外公示做外部锚定。
- 当前使用 JWT 认证；真实选举通常还需多因素认证与硬件令牌。
- 生产部署需启用 HTTPS、更换 ASGI 服务器配置、关闭 `/docs`。
