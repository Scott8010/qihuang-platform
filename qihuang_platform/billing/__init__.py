"""
计费系统 — Phase 2 (#20)

数据模型（计费计量域6表）：
  plan / subscription / api_key / call_log / bill / audit_log

套餐档位：
  体验版(免费30天) / 标准版(年订阅) / 专业版(可谈) / 私有化(项目制)

实现文件：
- models.py     — SQLAlchemy ORM模型（6表）
- plans.py      — 套餐管理（创建/修改/features_json门控）
- billing.py    — 月账单生成（call_log汇总 → bill状态流转）
- quota.py      — 配额控制（计数/预警PushPlus+邮件/降级TRIAL→READONLY）
"""
