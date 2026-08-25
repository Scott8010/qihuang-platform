# 变更记录 · P0 活态调度器 append-only event log

> **归属**：本变更由 **8602 组（岐黄中台组 / 金虎）** 在本工作区直接落地。评估输入来自 HB 组受老黄之托撰写的 `OpenViking借鉴建议_8602参考.md`（外部参考），采纳与落地均为 8602 组自闭环，无外部 review 方。
>
> 来源：OpenViking / Apache Maka 双开源评估（老黄 2026-08-25 01:00 拍板升 P0，01:07 令"开干"）。**仅参考 Maka 的 append-only log 设计模式，未引入任何外部依赖。**

---

## 状态

- **已合并**：commit `de113c3`「feat(observability): 活态调度器 append-only event log（P0 落地）」→ push 到 `origin/main` 闭环（远端 `git ls-remote` 校验 main == `de113c3...` 一致）。
- CI 按 8602 部署铁律 rsync 至生产 `/root/qihuang_platform`。
- **剩余**：生产真实链路 E2E 灰度（任务 #531）待补，不假绿。

## 1. 背景与价值

评估结论（见 `OpenViking借鉴建议_8602参考.md` §7~§10）：OpenViking 管"记忆怎么组织"，Apache Maka 管"执行怎么审计"。其中 Maka 的 **"Log is the Runtime"（原始证据永不丢 / Context is not history）** 对咱最有现实价值——

当前 8602 排错依赖 journal grep 全量日志，**缺结构化的"权限判定 + 计费/拦截决策 + 工具调用"事件流**。一旦商业化场景用户投诉"为啥这单算了我 2 套餐 / agent 为啥没拦住"，无法快速定位。本变更补上这一层。

## 2. 设计要点

| 要点 | 实现 |
|---|---|
| append-only | `SchedulerEventLog` 只提供 INSERT，无 update/delete 方法；文档建议生产侧加触发器禁止 UPDATE/DELETE 双保险 |
| 旁路非阻断 | `emit_event` 任何环节失败仅 `logger.warning`，**绝不 raise**，不影响主业务 |
| JSONL 兜底 | 先写 `event_logs/scheduler_events.jsonl`（路径可配 `QH_EVENT_LOG_PATH`），DB 宕机也不丢证据 |
| DB 双写 | 兜底成功后再写 `scheduler_event_log` 表 |
| 零外部依赖 | 纯 stdlib + SQLAlchemy，与现有 `Base/SessionLocal` 同构 |
| 事件类型 | INVOCATION / TOOL_CALL / PERMISSION / DECISION / ERROR（对齐 Maka runtime 事件精简集） |

## 3. 文件改动清单（5 个文件，已 commit `de113c3`）

### 新增 `qihuang_platform/event_log.py`
- `SchedulerEventLog` ORM（`__tablename__ = "scheduler_event_log"`）：`id / tenant_id / trace_id / agent_key / event_type / payload(json) / created_at` + 3 个复合索引。
- `emit_event(tenant_id, agent_key, event_type, payload, trace_id, db_session)` 旁路发射器：JSONL 兜底 → DB 双写，全程失败仅 warn。
- `configure_event_log(path)` 供测试/部署覆盖路径。

### 改 `qihuang_platform/db/config.py`（`init_db`）
- 延迟 `import qihuang_platform.event_log`（避循环依赖），随 `Base.metadata.create_all` 自动建表。

### 埋点 1 · `qihuang_platform/agent/deps.py`（`require_agent_in_plan`）
- `deps.py:25` 局部 import；`deps.py:29` 在权限判定各分支发射 **PERMISSION** 事件：
  - `no_tenant`（无法解析租户）→ 拒绝
  - `agent_inactive`（能力已停用）→ 拒绝
  - `no_subscription`（无有效订阅）→ 拒绝
  - `not_in_plan`（套餐未含该能力）→ 拒绝
  - 放行 → `allowed`
  - → 直接回答"**agent 为啥没拦住**"。

### 埋点 2 · `qihuang_platform/billing/quota.py`（`check_quota`）
- `quota.py:195` 局部 import；`quota.py:196` 在 `is_exceeded` 决策处发射 **DECISION** 事件（含 `used_calls/limit/month_calls_limit/used_tokens/...`）。
  - → 直接回答"**为啥这单算 N 套餐 / 是否超额拦截**"。

### 埋点 3 · `qihuang_platform/living/scheduler.py`（`_run_once` 活态闭环核心）
- 开头 `scheduler.py:26` 发射 **INVOCATION**；
- 聚合/趋势采集/回路三 各 success → **DECISION**、exception → **ERROR**（共 1×INVOCATION + 多×DECISION/ERROR，见 grep 行号 43/54/68/76/88/96）。

## 4. 单测与真验结果（已跑，非假绿）

- **单测 3 passed**（独立内存 SQLite，不污染开发库 `qihuang_platform.db`）：
  - `test_emit_writes_jsonl_and_db`：JSONL + DB 双写一致；
  - `test_unknown_event_type_falls_back`：未知类型回退 DECISION；
  - `test_db_failure_still_writes_jsonl`：DB 挂仍落 JSONL 且不抛。
- **`py_compile` 5 文件全 OK** + `config` / `deps` / `quota` / `scheduler` 模块 `import OK` → 改动未破坏加载。
- 运行命令（8602 工程根）：`python -m pytest tests/test_event_log.py -v`

## 5. 灰度计划

1. 先灰度 **`health-advisor`** 单个 agent（已在埋点 `agent_key` 维度可过滤）。
2. push 后做一次**真实 HTTP 链路 E2E**：用真实租户/套餐数据调 `/api/v1/agent/health-advisor/consult`，确认事件真入 `scheduler_event_log`，且能回答"这单为啥算 2 套餐 / 为啥没拦"。
3. 观察 1~2 天 JSONL + DB 写入量，评估表增长与索引性能，再考虑全量 agent 放开。

## 6. 风险与回滚

- **风险**：`emit_event` 高频调用下 JSONL 文件 IO 开销 —— 已用 `_log_lock` 串行化，且为 append；如成为瓶颈可改批量/异步落盘（后续优化，非阻塞）。
- **回滚**：`emit_event` 全旁路，即使表不存在/写入失败也仅 warn，主业务零影响；如需彻底下线，删 4 处埋点调用即可，核心模块可保留。

---

_归档：8602 组（金虎） · 2026-08-25 08:57 · 已合并 commit `de113c3`_
