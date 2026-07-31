# 岐黄智脑 — 存量端点迁移清单

> Phase 0 T0-4 | 生成：2026-07-26 | 来源：`Claw\qihuang-brain\api\main.py` + 14 routers

---

## 总览

| 指标 | 数值 |
|------|------|
| 现有端点总数 | ~144（分布在14个路由 + main.py内置5个） |
| 现有鉴权方式 | X-API-Key（普通）/ X-API-Key（Admin） |
| 新体系鉴权 | Token(JWT) 体系 + API Key(HMAC-SHA256) 签名 |
| 迁移策略 | 不动现有代码，platform/新建语义化端点，走网关转发 |

---

## 分组分类

### A类 — 复用（透传，不改代码）

这些端点直接通过网关透传到现有后端，仅添加鉴权升级 + 计量埋点。

| # | 现有路径 | 方法 | 功能 | 目标前缀 |
|---|---------|------|------|---------|
| A1 | `/reasoning/api/diagnose` | POST | 综合辨证推理 | `/api/v1/core/reasoning/diagnose` |
| A2 | `/reasoning/api/diagnose/{system}` | POST | 单体系辨证 | `/api/v1/core/reasoning/{system}` |
| A3 | `/reasoning/api/safety/check` | POST | 用药安全审查 | `/api/v1/core/safety/check` |
| A4 | `/query/api/search` | GET | 图谱语义查询 | `/api/v1/core/graph/query` |
| A5 | `/query/api/node/{id}` | GET | 图谱节点详情 | `/api/v1/core/graph/entities/{type}/{id}` |
| A6 | `/chat/api/agent/*` | POST | 智能对话（SSE） | `/api/v1/core/agent/chat` |
| A7 | `/literature/api/search` | GET | 文献检索 | `/api/v1/core/literature/search` |
| A8 | `/diagnosis/api/assess` | POST | 体质辨识 | `/api/v1/health/constitution/assess` |
| A9 | `/formula_analysis/api/analyze` | POST | 方剂分析 | `/api/v1/core/reasoning/formula` |
| A10 | `/expert/api/*` | GET | 专家知识库查询 | `/api/v1/core/expert/*` |

> **复用端点~50个**（推理/查询/文献/对话/方剂分析/专家/扩展等只读类）

---

### B类 — 改造（语义化封装，底层调现有引擎）

这些端点需要新建语义化路由，但核心引擎代码不动。

| # | 现有路由文件 | 改造目标 | 备注 |
|---|------------|---------|------|
| B1 | `diagnosis.py` (24K行) | 拆为 `/api/v1/health/*`(大健康) + `/api/v1/med/*`(医疗) | 原文件太大，按场景拆分 |
| B2 | `formula_analysis.py` (15K行) | 处方审查逻辑提取到 `/api/v1/med/prescription/review` | 安全模块独立 |
| B3 | `annotation.py` (44K行) | 标注角色改RBAC管理（大张/小张→正式角色） | 权限模型升级 |
| B4 | `auto_growth.py` (6.5K行) | 置信度区间(25%-65%)接入 `kg_review_item` 审核队列 | 知识审核工作流 |
| B5 | `versioning.py` (1.8K行) | 版本快照接入 `kg_version` 表 | 版本管理数据库化 |
| B6 | `radar.py` (7.5K行) | 知识雷达改为 `/admin/v1/monitor/radar` | 归入监控大盘 |
| B7 | `extraction.py` (22K行) | 抽取管理归入 `/admin/v1/extraction/*` | Admin域 |
| B8 | `crawler.py` (5.4K行) | 爬虫管理归入 `/admin/v1/crawler/*` | Admin域 |

> **改造端点~60个**（诊断/方剂/标注/自生长/版本/雷达/抽取/爬虫）

---

### C类 — 保留不动（内部运维用，不暴露给商业API）

| # | 现有路由 | 原因 |
|---|---------|------|
| C1 | `/health` | 健康检查，运维用 |
| C2 | `/api-status` | API状态，运维用 |
| C3 | `/graph` | 图谱可视化HTML页面 |
| C4 | `/qihuang3d` | 岐黄三境3D页面 |
| C5 | `/frontend/*` | 静态文件服务 |
| C6 | `/model/*`, `/lib/*` | 模型/库文件 |
| C7 | `/docs`, `/redoc` | API文档 |

> **保留端点~10个**（运维/HTML页面/静态资源）

---

## 新增端点（Phase 1-3）

| 域 | 端点 | Phase | 新增原因 |
|----|------|-------|---------|
| Auth | `/api/v1/auth/*`（7个） | Phase 1 | 全新认证体系 |
| Admin | `/admin/v1/*`（30+个） | Phase 1-3 | 管理/运维/运营三端 |
| Core | `/api/v1/core/acupoint/*`（3个） | Phase 1 | 3D模块独立端点 |
| Med | `/api/v1/med/*`（6个） | Phase 3 | 医疗场景新端点 |
| Health | `/api/v1/health/*`（4个） | Phase 2 | 大健康场景新端点 |
| Edu | `/api/v1/edu/*`（8个） | Phase 3 | 培训场景新端点 |
| Open | `/open/v1/*`（5个） | Phase 4 | 开发者门户 |
| Billing | `/api/v1/billing/*`（3个） | Phase 2 | 计费系统 |

---

## 迁移时序

```
Phase 0 (现在):
  ↓ 本清单冻结 → Mock 服务覆盖 auth + core 全部端点
  ↓ 前端可基于 Mock 并行开发

Phase 1:
  ↓ PostgreSQL + RBAC 上线
  ↓ auth/* 7端点切真实 → 新鉴权生效
  ↓ 网关转发规则上线 → A类端点透传
  ↓ 控制端 MVP 挂载 → Admin域初现

Phase 2:
  ↓ health/* 4端点上线 → B类诊断拆分完成
  ↓ billing/* 对接

Phase 3:
  ↓ med/* + edu/* 上线 → B类改造完成
  ↓ Admin全功能 → B类管理功能归入

Phase 4:
  ↓ open/* 按信号触发
```

---

## 风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| annotation.py 44K行重构 | B类最大单文件 | 不重构核心逻辑，只改鉴权+角色映射 |
| 新旧鉴权并行期间复杂度 | 两套Key体系可能冲突 | 网关层统一处理，底层不可见 |
| reasoning.py 168K行 | 核心引擎复杂度高 | 不改核心代码，只加外层封装 |
