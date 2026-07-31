"""
RBAC权限系统 — Phase 1 (#10)

数据模型（账号权限域7表）：
  tenant / org / user / role / permission / user_role / role_permission

权限模型：
  - 三级账号：租户 → 机构 → 用户
  - 三类权限：菜单 / API端点 / 数据(SELF/ORG/TENANT)
  - 9个预置角色模板
  - 场景白名单（大健康不能拿处方审查权限）
  - 权限变更全程审计

实现文件：
- models.py     — SQLAlchemy ORM模型（7表）
- auth.py       — 微信登录 / 短信验证码 / Token签发刷新 / 登出
- roles.py      — 角色模板 / 权限点绑定 / 场景白名单
- middleware.py — Token注入X-User-Id/X-Tenant-Id/X-Org-Id/X-Roles
"""
