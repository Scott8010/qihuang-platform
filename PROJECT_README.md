"""
岐黄智脑商业化平台 - Platform Layer
与现有 api/ 平级，独立端口运行（8602），不碰现有运行代码。

目录结构：
  gateway/    - API网关（双鉴权/限流/计量/路由分发）
  rbac/       - RBAC权限系统（角色/权限/租户-机构-用户）
  billing/    - 计费系统（套餐/用量/账单）
  control/    - 控制端API（管理/运维/运营三端）
  db/         - PostgreSQL ORM模型（24张表分4域）
  middleware/ - 中间件（Token验证/API Key签名/审计日志）
"""
