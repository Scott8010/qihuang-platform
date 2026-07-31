"""
中间件集合 — Phase 1

实现文件：
- token_auth.py    — Token鉴权（JWT验证 / 注入X-User-Id等头）
- api_key_auth.py  — API Key签名验证（HMAC-SHA256 / 时间窗±5分钟 / nonce防重放）
- audit.py         — 审计日志中间件（所有写操作→audit_log表）
- cors.py          — CORS白名单（控制端加强版：Token+IP白名单+敏感操作二次校验）
- ratelimit.py     — 限流中间件（用户/Key双维度 + 租户套餐QPS）
"""
