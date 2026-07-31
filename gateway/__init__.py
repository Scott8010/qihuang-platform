"""
API网关模块 — Phase 1 (#8)

功能：
- 双鉴权体系（Token + HMAC-SHA256 签名）
- 双维度限流配额（用户/Key + 接口）
- 统一计量埋点（call_log异步写入）
- 统一响应包装（code/message/data/trace_id）

实现文件：
- auth.py       — Token验证 / API Key签名验证 / 鉴权中间件
- limiter.py    — 限流器（滑动窗口 / 令牌桶，Redis）
- metrics.py    — 计量埋点（call_log记录 / 响应头注入X-RateLimit-*）
- response.py   — 统一响应包装（三段式 + 12个通用错误码）
- router.py     — 网关路由分发（前缀匹配 / 租户路由 / 降级策略）
"""
