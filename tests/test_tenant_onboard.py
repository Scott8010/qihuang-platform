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
    # 2026-08-22 老黄拍板：3D 严格按套餐门槛——标准版不含，传 true 也强制 false
    assert onboard_resp["module_3d"] is False


def test_list_tenants_carries_plan_and_extras(client, ensure_admin_in_db, admin_headers, onboard_resp):
    """列表接口应下发套餐/到期/联系人/3D（此前全部缺失 → 列表空壳）"""
    rows = client.get("/admin/v1/tenants", headers=admin_headers).json()["data"]
    me = next((t for t in rows if t["id"] == onboard_resp["id"]), None)
    assert me, "新建租户应出现在列表"
    assert me["plan"] == "标准版", f"套餐应显示标准版，实际: {me.get('plan')!r}"
    assert me["expires"], "到期时间应下发"
    assert me["contact_name"] == "回归测试联系人"
    assert me["contact_phone"] == "13800000000"
    # 2026-08-22 套餐门槛：标准版强制 module_3d=false
    assert me["module_3d"] is False


def test_subscription_visible(client, ensure_admin_in_db, admin_headers, onboard_resp):
    """/admin/v1/subscriptions 应包含该租户的 active 订阅"""
    data = client.get("/admin/v1/subscriptions", headers=admin_headers).json()["data"]
    items = data.get("items", data) if isinstance(data, dict) else data
    subs = [s for s in (items or []) if s.get("tenant_id") == onboard_resp["id"]]
    assert subs, "订阅列表应包含新租户的订阅"
    assert any(s.get("status") == "active" for s in subs), "订阅应为 active"


# ═══════════════════════════════════════════════════════════
# 2026-08-22 开户表单升级：机构资质字段 + 医疗两证必传 + 电话格式校验
# ═══════════════════════════════════════════════════════════

def test_medical_scene_requires_both_licenses(client, ensure_admin_in_db, admin_headers):
    """医疗场景（medical）不传两证 → 422 校验失败"""
    r = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_med_{uuid.uuid4().hex[:8]}",
        "display_name": "无证医疗测试",
        "scene": "medical",
        "plan": "standard",
        "contact_name": "张三",
        "contact_phone": "13800000001",
    }, headers=admin_headers)
    assert r.status_code == 422, f"医疗无两证应 422，实际 {r.status_code}: {r.text[:200]}"
    body = r.json()
    detail = body.get("detail") or {}
    msgs = " ".join(str(d.get("msg", "")) for d in (detail if isinstance(detail, list) else [detail]))
    assert "营业执照" in msgs or "执业许可证" in msgs, f"校验信息应提示两证缺失: {msgs}"


def test_medical_scene_with_licenses_ok(client, ensure_admin_in_db, admin_headers):
    """医疗场景带两证 + 完整资质字段 → 开户成功且字段落库"""
    r = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_medok_{uuid.uuid4().hex[:8]}",
        "display_name": "持证医疗测试",
        "scene": "medical",
        "plan": "standard",
        "contact_name": "李四",
        "contact_phone": "021-12345678",
        "contact_email": "lisi@example.com",
        "address_country": "中国",
        "address_province": "上海市",
        "address_city": "上海市",
        "address_district": "浦东新区",
        "org_intro": "专业中医馆，持证经营",
        "license_business": "/admin/v1/upload/abc123",
        "license_business_name": "营业执照.jpg",
        "license_medical": "/admin/v1/upload/def456",
        "license_medical_name": "医疗机构执业许可证.jpg",
        "module_3d": True,
        "duration_months": 12,
    }, headers=admin_headers)
    assert r.status_code == 200, f"医疗带两证应成功: {r.text[:300]}"
    data = r.json()["data"]
    assert data["contact_email"] == "lisi@example.com"
    assert data["license_business"] == "/admin/v1/upload/abc123"
    assert data["license_medical"] == "/admin/v1/upload/def456"

    # 列表接口应透传资质字段
    rows = client.get("/admin/v1/tenants", headers=admin_headers).json()["data"]
    me = next((t for t in rows if t["id"] == data["id"]), None)
    assert me, "新建租户应出现在列表"
    assert me["address_province"] == "上海市", f"省份应下发: {me.get('address_province')!r}"
    assert me["address_district"] == "浦东新区"
    assert me["contact_email"] == "lisi@example.com"
    assert me["license_medical"] == "/admin/v1/upload/def456"


def test_phone_landline_without_area_code_rejected(client, ensure_admin_in_db, admin_headers):
    """座机不带区号 → 422；手机号合法 → 通过"""
    bad = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_phone_{uuid.uuid4().hex[:8]}",
        "display_name": "电话校验测试",
        "scene": "health",
        "plan": "standard",
        "contact_name": "王五",
        "contact_phone": "12345678",  # 无区号座机
    }, headers=admin_headers)
    assert bad.status_code == 422, f"无区号座机应 422: {bad.text[:200]}"

    good = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_phoneok_{uuid.uuid4().hex[:8]}",
        "display_name": "电话校验通过",
        "scene": "health",
        "plan": "standard",
        "contact_name": "王五",
        "contact_phone": "+86-021-12345678",  # 国际前缀座机
    }, headers=admin_headers)
    assert good.status_code == 200, f"国际前缀座机应通过: {good.text[:200]}"


def test_upload_endpoint_stores_file(client, ensure_admin_in_db, admin_headers):
    """POST /admin/v1/upload 应保存文件并返回可访问 URL"""
    r = client.post(
        "/admin/v1/upload",
        files={"file": ("营业执照.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg")},
        data={"purpose": "license"},
        headers=admin_headers,
    )
    assert r.status_code == 200, f"上传应成功: {r.text[:300]}"
    data = r.json()["data"]
    assert data["file_id"], "应返回 file_id"
    assert data["url"].startswith("/admin/v1/upload/"), f"应返回可访问 URL: {data['url']}"

    # 下载端点应能取回文件
    dl = client.get(data["url"], headers=admin_headers)
    assert dl.status_code == 200, f"下载应成功: {dl.status_code}"
    assert dl.content == b"\xff\xd8\xff\xe0fake-jpeg", "文件内容应一致"


def test_org_intro_over_150_chars_rejected(client, ensure_admin_in_db, admin_headers):
    """机构介绍超过 150 字 → 422（2026-08-22 老黄要求限 150 字）"""
    r = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_intro_{uuid.uuid4().hex[:8]}",
        "display_name": "介绍超长测试",
        "scene": "health",
        "plan": "standard",
        "contact_name": "赵六",
        "contact_phone": "13800000002",
        "org_intro": "介" * 151,
    }, headers=admin_headers)
    assert r.status_code == 422, f"超150字应 422，实际 {r.status_code}: {r.text[:200]}"

    # 恰好 150 字应通过
    ok = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_introok_{uuid.uuid4().hex[:8]}",
        "display_name": "介绍刚好150字",
        "scene": "health",
        "plan": "standard",
        "contact_name": "赵六",
        "contact_phone": "13800000003",
        "org_intro": "介" * 150,
    }, headers=admin_headers)
    assert ok.status_code == 200, f"150字应通过: {ok.text[:200]}"


def test_address_detail_supported(client, ensure_admin_in_db, admin_headers):
    """详细地址字段应支持 200 字 + 列表接口透传（老黄 2026-08-22 凌晨提的：地址少详细地址框）"""
    r = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_addr_{uuid.uuid4().hex[:8]}",
        "display_name": "详细地址测试",
        "scene": "health", "plan": "standard",
        "contact_name": "孙七", "contact_phone": "13800000004",
        "address_country": "中国", "address_province": "上海市",
        "address_city": "上海市", "address_district": "浦东新区",
        "address_detail": "世纪大道 100 号 上海中心大厦 88 楼 8801 室",
    }, headers=admin_headers)
    assert r.status_code == 200, f"详细地址应通过: {r.text[:200]}"
    # 超长 201 字 → 422
    over = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_addrov_{uuid.uuid4().hex[:8]}",
        "display_name": "详细地址超长",
        "scene": "health", "plan": "standard",
        "contact_name": "孙七", "contact_phone": "13800000005",
        "address_detail": "详" * 201,
    }, headers=admin_headers)
    assert over.status_code == 422, f"详细地址 201 字应 422: {over.text[:200]}"


# ═══════════════════════════════════════════════════════════
# 2026-08-22 老黄拍板：3D 岐黄三境严格套餐门槛（体验/标准=灰，专业/企业=亮）
# ═══════════════════════════════════════════════════════════

def test_module_3d_forced_by_plan(client, ensure_admin_in_db, admin_headers):
    """套餐门槛强制：standard 传 module_3d=True → 落库 False；professional 传 False → 落库 True"""
    # ① 标准版 + 传 true → 强制 false
    r1 = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_3dstd_{uuid.uuid4().hex[:8]}",
        "display_name": "标准版3D门控测试",
        "scene": "health", "plan": "standard",
        "contact_name": "钱八", "contact_phone": "13800000006",
        "module_3d": True, "duration_months": 12,
    }, headers=admin_headers)
    assert r1.status_code == 200, f"标准版开户应成功: {r1.text[:300]}"
    d1 = r1.json()["data"]
    assert d1["module_3d"] is False, f"标准版传入 true 也必须强制 false，实际: {d1['module_3d']!r}"

    # 列表接口同样应为 false
    rows = client.get("/admin/v1/tenants", headers=admin_headers).json()["data"]
    me1 = next((t for t in rows if t["id"] == d1["id"]), None)
    assert me1 and me1["module_3d"] is False, "标准版租户列表 module_3d 应为 False"

    # ② 专业版 + 传 false → 强制 true
    r2 = client.post("/admin/v1/tenants/onboard", json={
        "name": f"t_3dpro_{uuid.uuid4().hex[:8]}",
        "display_name": "专业版3D门控测试",
        "scene": "health", "plan": "professional",
        "contact_name": "钱九", "contact_phone": "13800000007",
        "module_3d": False, "duration_months": 12,
    }, headers=admin_headers)
    assert r2.status_code == 200, f"专业版开户应成功: {r2.text[:300]}"
    d2 = r2.json()["data"]
    assert d2["module_3d"] is True, f"专业版传入 false 也必须强制 true（套餐已含自动开通），实际: {d2['module_3d']!r}"

    rows2 = client.get("/admin/v1/tenants", headers=admin_headers).json()["data"]
    me2 = next((t for t in rows2 if t["id"] == d2["id"]), None)
    assert me2 and me2["module_3d"] is True, "专业版租户列表 module_3d 应为 True"
