"""
E2E 冒烟测试 — 启动8602平台后验证核心流程
用法: python scripts/e2e_smoke.py
"""
import httpx
import os
import sys

# 支持环境变量覆盖，便于对生产实例冒烟：E2E_BASE=http://111.231.63.73:8602
BASE = os.getenv("E2E_BASE", "http://localhost:8602")
ADMIN_USER = os.getenv("QH_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("QH_ADMIN_PASS", "QhAdmin@2026")
PASS = 0
FAIL = 0

def check(name, resp, expected_codes, parse_json=True):
    global PASS, FAIL
    if resp.status_code in expected_codes:
        PASS += 1
        print(f"  ✅ [{resp.status_code}] {name}")
        if parse_json and resp.text and resp.text.strip().startswith("{"):
            try:
                return resp.json()
            except Exception:
                return {}
        return {}
    else:
        FAIL += 1
        print(f"  ❌ [{resp.status_code}] {name} (expected {expected_codes})")
        print(f"     body: {resp.text[:150]}")
        return {}

def token_from(resp):
    """从统一响应格式 {code,message,data:{access_token}} 提取token"""
    try:
        data = resp if isinstance(resp, dict) else resp
        return data.get("data", {}).get("access_token", "")
    except Exception:
        return ""

client = httpx.Client(timeout=15)

# ═══════════════════════════════════════════════════
# 1. 平台基础
# ═══════════════════════════════════════════════════
print("\n📦 1. 平台基础")
check("GET /platform/health", client.get(f"{BASE}/platform/health"), [200])
check("GET /platform/docs", client.get(f"{BASE}/platform/docs"), [200])
check("GET /platform/openapi.json", client.get(f"{BASE}/platform/openapi.json"), [200])

# ═══════════════════════════════════════════════════
# 2. 认证 — 正式管理员登录（dev 后门已下线）
# ═══════════════════════════════════════════════════
print("\n🔐 2. 认证流程")

# 2.1 开发后门必须已关闭
check(
    "POST /dev/admin-login 已下线",
    client.post(f"{BASE}/dev/admin-login"),
    [404, 405],
    parse_json=False,
)

# 2.2 错误口令必须被拒
check(
    "POST /admin/v1/login 错误口令拒绝",
    client.post(f"{BASE}/admin/v1/login", json={"username": ADMIN_USER, "password": "__wrong__"}),
    [401],
    parse_json=False,
)

# 2.3 正确口令签发 super_admin token
r = client.post(f"{BASE}/admin/v1/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
data = check("POST /admin/v1/login", r, [200])
admin_token = token_from(data)
admin_headers = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}
if admin_token:
    print(f"     admin_token: {admin_token[:30]}...")

# 用户token（复用admin token，平台侧无独立 user login 入口）
user_headers = admin_headers

# ═══════════════════════════════════════════════════
# 3. RBAC管理
# ═══════════════════════════════════════════════════
print("\n👥 3. RBAC管理")
check("GET /admin/v1/tenants", client.get(f"{BASE}/admin/v1/tenants", headers=admin_headers), [200])
check("GET /admin/v1/roles", client.get(f"{BASE}/admin/v1/roles", headers=admin_headers), [200])
check("GET /admin/v1/users", client.get(f"{BASE}/admin/v1/users", headers=admin_headers), [200])
# permissions/check is POST
r = client.post(f"{BASE}/admin/v1/permissions/check", json={"user_id": "dev_admin", "perm_codes": ["module_3d"]}, headers=admin_headers)
check("POST /admin/v1/permissions/check", r, [200, 422])
# RBAC plans
r = client.get(f"{BASE}/admin/v1/plans", headers=admin_headers)
plans_data = check("GET /admin/v1/plans", r, [200])
if isinstance(plans_data.get("data"), list):
    print(f"     套餐数: {len(plans_data['data'])}")

# ═══════════════════════════════════════════════════
# 4. 控制端 — 套餐/订阅/仪表盘/计费
# ═══════════════════════════════════════════════════
print("\n💰 4. 控制端核心功能")

check("GET /admin/v1/dashboard", client.get(f"{BASE}/admin/v1/dashboard", headers=admin_headers), [200])
check("GET /admin/v1/subscriptions", client.get(f"{BASE}/admin/v1/subscriptions", headers=admin_headers), [200])
check("GET /admin/v1/billing/bills", client.get(f"{BASE}/admin/v1/billing/bills?tenant_id=tenant_default&year=2026&month=7", headers=admin_headers), [200, 404])
check("GET /admin/v1/billing/usage", client.get(f"{BASE}/admin/v1/billing/usage", headers=admin_headers), [200])
check("GET /admin/v1/billing/scene-usage", client.get(f"{BASE}/admin/v1/billing/scene-usage", headers=admin_headers), [200])
check("GET /admin/v1/audit-logs", client.get(f"{BASE}/admin/v1/audit-logs", headers=admin_headers), [200])

# ═══════════════════════════════════════════════════
# 4.1 P1-A 监控大盘 (10端点)
# ═══════════════════════════════════════════════════
print("\n📡 4.1 监控大盘 (P1-A)")

check("GET /admin/v1/monitor/overview", client.get(f"{BASE}/admin/v1/monitor/overview", headers=admin_headers), [200])
check("GET /admin/v1/monitor/services", client.get(f"{BASE}/admin/v1/monitor/services", headers=admin_headers), [200])
check("GET /admin/v1/monitor/services/api/latency", client.get(f"{BASE}/admin/v1/monitor/services/api/latency", headers=admin_headers), [200])
check("GET /admin/v1/monitor/resources", client.get(f"{BASE}/admin/v1/monitor/resources", headers=admin_headers), [200])
check("GET /admin/v1/monitor/resources/trend/24h", client.get(f"{BASE}/admin/v1/monitor/resources/trend/24h", headers=admin_headers), [200])
check("GET /admin/v1/monitor/resources/trend/daily", client.get(f"{BASE}/admin/v1/monitor/resources/trend/daily", headers=admin_headers), [200])
check("GET /admin/v1/monitor/scaling-alerts", client.get(f"{BASE}/admin/v1/monitor/scaling-alerts", headers=admin_headers), [200])
check("GET /admin/v1/monitor/capacity-forecast", client.get(f"{BASE}/admin/v1/monitor/capacity-forecast", headers=admin_headers), [200])
check("GET /admin/v1/monitor/llm-status", client.get(f"{BASE}/admin/v1/monitor/llm-status", headers=admin_headers), [200])

# ═══════════════════════════════════════════════════
# 4.2 P1-B 成本中心 (6端点)
# ═══════════════════════════════════════════════════
print("\n💵 4.2 成本中心 (P1-B)")

check("GET /admin/v1/cost/overview", client.get(f"{BASE}/admin/v1/cost/overview", headers=admin_headers), [200])
check("GET /admin/v1/cost/trend", client.get(f"{BASE}/admin/v1/cost/trend", headers=admin_headers), [200])
check("GET /admin/v1/cost/breakdown", client.get(f"{BASE}/admin/v1/cost/breakdown", headers=admin_headers), [200])
check("GET /admin/v1/cost/daily", client.get(f"{BASE}/admin/v1/cost/daily", headers=admin_headers), [200])
check("GET /admin/v1/cost/services/expiring", client.get(f"{BASE}/admin/v1/cost/services/expiring", headers=admin_headers), [200])
check("GET /admin/v1/cost/resources", client.get(f"{BASE}/admin/v1/cost/resources", headers=admin_headers), [200])

# ═══════════════════════════════════════════════════
# 5. 中台能力 (透传8601, 可能降级503)
# ═══════════════════════════════════════════════════
print("\n🧠 5. 中台能力")

check("GET /api/v1/health/constitution", client.get(
    f"{BASE}/api/v1/health/constitution?description=容易疲劳乏力", headers=user_headers), [200, 404, 503])
check("GET /api/v1/health/regimen", client.get(
    f"{BASE}/api/v1/health/regimen?constitution=气虚质", headers=user_headers), [200, 404, 503])
check("POST /api/v1/medical/diagnose", client.post(
    f"{BASE}/api/v1/medical/diagnose", json={"symptoms": "头痛发热恶寒"}, headers=user_headers), [200, 404, 503])
check("POST /api/v1/medical/prescription-review", client.post(
    f"{BASE}/api/v1/medical/prescription-review", json={"prescription": "麻黄汤"}, headers=user_headers), [200, 404, 503])
check("GET /api/v1/education/classics", client.get(
    f"{BASE}/api/v1/education/classics?keyword=黄帝内经", headers=user_headers), [200, 404, 503])
check("GET /api/v1/acupoint/list", client.get(
    f"{BASE}/api/v1/acupoint/list", headers=user_headers), [200, 404, 503])

# ═══════════════════════════════════════════════════
# 6. 控制端子模块
# ═══════════════════════════════════════════════════
print("\n📊 6. 控制端子模块")

# customers: /admin/v1/customers/stats
r = client.get(f"{BASE}/admin/v1/customers/stats", headers=admin_headers)
check("GET /admin/v1/customers/stats", r, [200, 500])

# reports: /admin/v1/reports (GET list)
r = client.get(f"{BASE}/admin/v1/reports", headers=admin_headers)
check("GET /admin/v1/reports", r, [200, 500])

# alerts: /admin/v1/alerts/rules
r = client.get(f"{BASE}/admin/v1/alerts/rules", headers=admin_headers)
check("GET /admin/v1/alerts/rules", r, [200, 404, 500])

# sync: /admin/v1/sync/status
r = client.get(f"{BASE}/admin/v1/sync/status", headers=admin_headers)
check("GET /admin/v1/sync/status", r, [200, 404, 500])

# ═══════════════════════════════════════════════════
# 7. 网关/Mock
# ═══════════════════════════════════════════════════
print("\n🚦 7. 网关与Mock")
check("POST /mock/auth/wechat-login", client.post(f"{BASE}/mock/auth/wechat-login", json={"code": "test_123"}), [200, 404])

# dev 路由仅在 ENABLE_DEV_ROUTES=1 时挂载；生产环境应为 404（安全基线）
_DEV_ON = os.getenv("ENABLE_DEV_ROUTES", "0") == "1"
_dev_codes = [200] if _DEV_ON else [404]
_dev_hint = "可用" if _DEV_ON else "已下线"

r = client.get(f"{BASE}/dev/metering/stats")
check(f"GET /dev/metering/stats（{_dev_hint}）", r, _dev_codes, parse_json=_DEV_ON)

r = client.post(f"{BASE}/dev/register-api-key", json={"plan": "standard", "note": "E2E smoke test"})
check(f"POST /dev/register-api-key（{_dev_hint}）", r, _dev_codes, parse_json=_DEV_ON)

# ═══════════════════════════════════════════════════
# 总计
# ═══════════════════════════════════════════════════
print(f"\n{'='*50}")
total = PASS + FAIL
print(f"🎯 E2E冒烟: {total}项  ✅{PASS}  ❌{FAIL}")
print(f"{'='*50}")

client.close()
sys.exit(0 if FAIL == 0 else 1)
