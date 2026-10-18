# 系统图集（可直接发给开发者）

> COMP 3500SEF / 8500SEF — 选举管理与投票系统
> 技术栈已定：前端 **Vue 3 + TypeScript**，后端 **Python 3.11 + FastAPI**，数据库 **PostgreSQL 16 + Redis 7**

本目录是**已渲染好的图片**，不需要任何工具即可查看，可直接贴到微信 / Slack / 邮件 / 报告里。

---

## 图片清单

| 文件 | 内容 | 适合给谁看 |
|---|---|---|
| **`00-overview.png`** / `.svg` | **主图**：完整业务流程 + 每一步使用的语言与框架（登录 → 选选举 → 投票校验 → 写入事务 → 核验与实时） | 全体开发者先看这张 |
| `01-tech-stack.png` | 四层架构全景：表示层 / 通信层 / 应用逻辑层 / 数据层，每层标注具体技术 | 架构讨论、部署分工 |
| `03-vote-transaction.png` | **投票事务时序图**：一次投票在后端内部的 28 步，含两条 `alt` 分支（状态非 open / 唯一约束冲突） | 后端开发者（成员 3/4/5） |
| `04-deployment.png` | 部署拓扑：浏览器 → Nginx → Uvicorn/FastAPI → PostgreSQL / Redis（Docker Compose） | 负责部署与联调的人 |

**建议**：日常沟通先发 `00-overview.png`；讨论投票事务细节时发 `03-vote-transaction.png`。

---

## 图例约定

| 颜色 | 含义 |
|---|---|
| 🔵 蓝色框 | 前端 / API 调用（Vue 3 + TypeScript、Axios、EventSource） |
| 🟢 绿色框 | 后端逻辑（FastAPI、Pydantic、业务服务、审计日志） |
| 🟠 橙色框 | 数据层（PostgreSQL、Redis、SQLAlchemy 操作） |
| 🔴 红色框 | 错误分支（4xx 响应、回滚） |
| 🟡 黄色底 | 一个业务阶段（subgraph） |

---

## 关键节点速查

- **认证**：`POST /auth/login` → Pydantic 校验 → `passlib[bcrypt]` 验密 → `python-jose` 签发 JWT
- **投票**：`POST /votes` → 状态机校验（必须 `open`）→ 资格校验 → 入 `ballots`（仅 `anon_id`）→ 入 `votes_log`（**UNIQUE 约束在此仲裁**）→ 生成凭证 → 写哈希链审计 → `COMMIT`
- **防重复**：由 `votes_log` 的 `UNIQUE(position_id, user_id)` 保证，**不是**应用层 `if` 判断
- **匿名性**：`ballots` 表无 `user_id`，`voter_roll` 表无 `ballot_id`，两者只通过发给选民的凭证码关联
- **实时**：`EventSource` 订阅 `/events/turnout`，FastAPI 用 `StreamingResponse` 推 SSE；**投票期间只推投票率，不推各候选人票数**

---

## 修改图后如何重新渲染

图的源文件是 `../02-flowchart-with-tech-stack.md` 里的 Mermaid 代码块。

```bash
# 1. 安装渲染工具（只需一次）
npm install -g @mermaid-js/mermaid-cli

# 2. 渲染（macOS 使用本机 Chrome，无需下载 Chromium）
mmdc -i 图.mmd -o 输出.png -b white -s 2 --size 1200
```

> 本目录的图是用 `mmdc 12.0.0` + 本机 Google Chrome 渲染的，
> 配置为中文字体 `PingFang SC`，因此中文不会显示为方块。

---

## 注意

- `.svg` 是矢量图，放大不失真，适合放进报告 PDF 或在大屏上演示
- `.png` 是位图，适合聊天工具直接预览
- 图与代码**必须保持同步**：如果实现改了流程，请同步更新 Mermaid 源码（`Lecture 5` 明确要求模型应准确反映系统）
