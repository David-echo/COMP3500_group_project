# COMP3500 Group 39 — 代码改动通知（Progress Review 最小修复）

日期：2026-11-08

为补 Progress Review 演示缺口，已做最小改动（**未改匿名性 schema**）。请组员 pull 后再测。

## 前端

1. 「View results」改为进入选民结果页 `/elections/:id/results`（新增 `ResultsView.vue`），不再误跳到 `/vote`
2. `BallotView` 支持多职位投票（可 Next position）；刷新后会从已投职位续投（`voted_position_ids`）

## 后端

1. `has_voted`：全部职位投完才算投过
2. 完整性检查：按 `distinct user_id` 统计，避免多职位误报
3. 选举接口补充返回 `voted_position_ids`
4. 补了多职位相关 API 测试（本地后端测过 45 项通过）

## 文档

- `README.md`、`docs/02-flowchart-with-tech-stack.md`：匿名性表述更谨慎（选票加密；`votes_log`/审计仍可关联身份，上台别硬说「只证投过」）

## 未改

- 数据库 schema / `VotesLog` 结构不动

有问题直接在组内回复。
