# 前端（Vue 3 + TypeScript）— 成员 1 / 2 负责

技术栈：Vue 3 + TypeScript + Vite + Pinia + Vue Router + ECharts + Axios + EventSource(SSE)

## 启动

```bash
# 1) 先启动后端（默认 8770）
cd ../backend
uvicorn app.main:app --reload --port 8770

# 2) 再启动前端
cd ../frontend
npm install
npm run dev          # http://localhost:5173
```

Vite 已配置 `/api` 代理到 `http://127.0.0.1:8770`，无需处理跨域。

## 目录

```
src/
├── main.ts              入口
├── App.vue              布局与导航
├── router.ts            路由（4 步流程）
├── api.ts               REST 客户端 + 类型定义
├── stores/auth.ts       Pinia：登录态
├── composables/
│   └── useTurnout.ts    SSE 订阅投票率（自动重连）
└── views/
    ├── LoginView.vue        ① 登录
    ├── ElectionsView.vue    ② 选择选举（含实时投票率）
    ├── BallotView.vue       ③ 选择候选人并投票
    ├── ReceiptView.vue      ④ 凭证核验 / 结果查看
    └── AdminView.vue        管理台（状态控制、计票、完整性、审计）
```

## 与后端契约

全部接口见后端自动生成的文档：**http://127.0.0.1:8770/docs**

## 重要约定

- **投票期间前端只显示投票率**，不显示各候选人票数（后端也不给）——这是公平性要求。
- 凭证码**不包含选择内容**，不要试图展示"你投给了谁"。
- SSE 断线会自动重连；页面刷新会重新订阅。
