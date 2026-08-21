"""租户开户一条龙回归测试（2026-08-21 老黄实测翻车后补）。

背景：控制台「新建租户开户」此前走 rbac POST /admin/v1/tenants（只建租户名，
套餐/联系人/3D 全被丢弃、不建订阅）→ 新建租户详情页套餐与服务全空。
修复后前端走 POST /admin/v1/tenants/onboard 一条龙，本测试锁定该行为：

1. onboard 创建租户（套餐 standard + 联系人 + 3D 开）
2. 列表接口 /admin/v1/tenants 应下发 plan/expires/contact_name/contact_phone/module_3d
3. 订阅接口 /admin/v1/subscriptions 应能看到该租户的 active 订阅
"""

import uuid

import pytest

TENANT_NAME = f"onboard回归_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def onboard_resp(client, ensure_admin_in_db, admin_headers):
    r = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_{uuid.uuid4().hex[:8]}",
        "display_name": TENANT_NAME,
        "scene": "health",
        "plan": "standard",
        "contact_name": "回归测试联系人",
        "contact_phone": "13800000000",
        "module_3d": True,
        "duration_months": 12,
    }, headers=admin_headers)
    assert r.status_code == 200, f"开户失败: {r.status_code} {r.text[:300]}"
    return r.json()["data"]


def test_onboard_returns_plan_and_subscription(onboard_resp):
    """开户响应应包含套餐、订阅 id、到期时间、联系人"""
    assert onboard_resp["plan"] == "standard"
    assert onboard_resp["plan_display"] == "标准版"
    assert onboard_resp["subscription_id"], "开户必须创建订阅"
    assert onboard_resp["end_date"], "订阅必须有到期时间"
    assert onboard_resp["contact_name"] == "回归测试联系人"
    assert onboard_resp["module_3d"] is True


def test_list_tenants_carries_plan_and_extras(client, ensure_admin_in_db, admin_headers, onboard_resp):
    """列表接口应下发套餐/到期/联系人/3D（此前全部缺失 → 列表空壳）"""
    rows = client.get("/admin/v1/tenants", headers=admin_headers).json()["data"]
    me = next((t for t in rows if t["id"] == onboard_resp["id"]), None)
    assert me, "新建租户应出现在列表"
    assert me["plan"] == "标准版", f"套餐应显示标准版，实际: {me.get('plan')!r}"
    assert me["expires"], "到期时间应下发"
    assert me["contact_name"] == "回归测试联系人"
    assert me["contact_phone"] == "13800000000"
    assert me["module_3d"] is True


def test_subscription_visible(client, ensure_admin_in_db, admin_headers, onboard_resp):
    """/admin/v1/subscriptions 应包含该租户的 active 订阅"""
    data = client.get("/admin/v1/subscriptions", headers=admin_headers).json()["data"]
    items = data.get("items", data) if isinstance(data, dict) else data
    subs = [s for s in (items or []) if s.get("tenant_id") == onboard_resp["id"]]
    assert subs, "订阅列表应包含新租户的订阅"
    assert any(s.get("status") == "active" for s in subs), "订阅应为 active"
