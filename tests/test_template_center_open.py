"""
多租户能力中心 — 开放接口（HMAC 友好）端到端验证

覆盖：/api/v1/template-center 下的列表 / 详情 / 建模板 / 提交审核。
鉴权沿用 admin_token（get_current_principal 在无 X-App-Key 时回退 JWT）。
API Key 签名通道在集成测试中验证（generate_api_signature 已在 gateway.auth）。
"""
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    DbTemplate, TemplateOwnership, TemplateReviewSubmission,
)


def _cleanup(db):
    db.query(TemplateReviewSubmission).delete()
    db.query(TemplateOwnership).delete()
    db.query(DbTemplate).delete()
    db.commit()


def test_open_template_center_create_submit(client, admin_token):
    H = {"Authorization": f"Bearer {admin_token}"}

    # 1) 机构自建模板（HB 视角：带 org_id=org_default，CI PG 该 org 已存在）
    r = client.post("/api/v1/template-center/templates", headers=H, json={
        "name": "HB 测试模板·艾灸话术",
        "kind": "herb",
        "content_json": {"intro": "回传测试"},
        "org_id": "org_default",
        "visibility": "private",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0 or body.get("success") is True
    tid = body["data"]["id"]
    assert body["data"]["ownership"]["owner_org_id"] == "org_default"
    assert body["data"]["ownership"]["source"] == "self"
    assert body["data"]["ownership"]["visibility"] == "private"

    # 2) 列表能查到
    r = client.get("/api/v1/template-center/templates?org_id=org_default", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total"] >= 1

    # 3) 详情
    r = client.get(f"/api/v1/template-center/templates/{tid}", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == tid

    # 4) 提交审核
    r = client.post(f"/api/v1/template-center/templates/{tid}/submit", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PENDING"
    assert r.json()["data"]["submitter_org_id"] == "org_default"

    # 5) 幂等：再 submit 返回已有 PENDING
    r = client.post(f"/api/v1/template-center/templates/{tid}/submit", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PENDING"


def test_open_template_center_body_org_id_overrides_state(client, admin_token):
    """JWT 路径：state.org_id 与 body.org_id 同时有值时，body 优先。"""
    H = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/template-center/templates", headers=H, json={
        "name": "覆盖归属测试", "kind": "herb",
        "content_json": {}, "org_id": "org_default", "visibility": "private",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["ownership"]["owner_org_id"] == "org_default"
    assert body["data"]["ownership"]["source"] == "self"
    # 注：API Key 路径下 state.org_id 为 None，body 不传 org_id 时 source=platform。
    # 该路径在代码层走通（open_router.py open_create_template 第 84 行判断），
    # 集成测试中以 HMAC 签名方式覆盖。


def test_open_template_center_404(client, admin_token):
    H = {"Authorization": f"Bearer {admin_token}"}
    r = client.get("/api/v1/template-center/templates/not_exist_id", headers=H)
    assert r.status_code == 404


def test_open_template_center_cleanup(client, admin_token):
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()
