"""
多租户能力中心（二期）— 模板中心 HTTP 端到端验证

覆盖：模板 CRUD / 编辑版本快照 / 克隆 / 提交审核 / 平台采纳·强下架 / 问卷→模板草稿。
鉴权：admin_token（super_admin）即可通过 get_current_user 与 get_current_admin。
"""
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    DbTemplate, TemplateOwnership, TemplateReviewSubmission, TemplateVersion,
    StoreQuestionnaire,
)


def _cleanup(db):
    db.query(TemplateReviewSubmission).delete()
    db.query(TemplateVersion).delete()
    db.query(TemplateOwnership).delete()
    db.query(DbTemplate).delete()
    db.query(StoreQuestionnaire).delete()
    db.commit()


def test_template_center_full_flow(client, admin_token):
    H = {"Authorization": f"Bearer {admin_token}"}

    # 1) 创建模板
    r = client.post("/admin/v1/template-center/templates", headers=H, json={
        "name": "风寒表实证模板", "kind": "syndrome",
        "content_json": {"fields": ["恶寒", "发热"]}, "visibility": "private",
    })
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    assert r.json()["data"]["ownership"]["source"] in ("self", "platform")

    # 2) 列表可见
    r = client.get("/admin/v1/template-center/templates", headers=H)
    assert r.status_code == 200
    assert r.json()["data"]["total"] >= 1

    # 3) 编辑（应生成 v2 + 版本快照）
    r = client.put(f"/admin/v1/template-center/templates/{tid}", headers=H, json={
        "content_json": {"fields": ["恶寒", "发热", "无汗"]},
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["current_version"] == "v2"
    db = SessionLocal()
    try:
        versions = db.query(TemplateVersion).filter(TemplateVersion.template_id == tid).all()
        assert len(versions) == 1
        assert versions[0].version_tag == "v1"
    finally:
        db.close()

    # 4) 克隆到机构
    r = client.post(f"/admin/v1/template-center/templates/{tid}/clone", headers=H, json={
        "target_org_id": "org_default", "visibility": "private",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["ownership"]["source"] == "clone"

    # 5) 提交平台审核
    r = client.post(f"/admin/v1/template-center/templates/{tid}/submit", headers=H)
    assert r.status_code == 200, r.text
    sub_id = r.json()["data"]["id"]
    assert r.json()["data"]["status"] == "PENDING"

    # 6) 平台采纳 → 可见性提升 public
    r = client.post(f"/admin/v1/template-center/review/submissions/{sub_id}/approve",
                    headers=H, json={"review_note": "通过"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "APPROVED"
    db = SessionLocal()
    try:
        own = db.query(TemplateOwnership).filter(
            TemplateOwnership.template_id == tid).first()
        assert own.visibility == "public", own.visibility
    finally:
        db.close()

    # 7) 再提交一单并强下架
    r = client.post(f"/admin/v1/template-center/templates/{tid}/submit", headers=H)
    sub_id2 = r.json()["data"]["id"]
    r = client.post(f"/admin/v1/template-center/review/submissions/{sub_id2}/reject",
                    headers=H, json={"review_note": "违规"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "REJECTED"
    db = SessionLocal()
    try:
        own = db.query(TemplateOwnership).filter(
            TemplateOwnership.template_id == tid).first()
        assert own.visibility == "private", own.visibility
    finally:
        db.close()

    # 8) 门店问卷 → 模板草稿
    r = client.post("/admin/v1/template-center/questionnaires", headers=H, json={
        "title": "体质采集问卷", "schema_json": {"kind": "herb", "fields": ["舌象"]},
    })
    assert r.status_code == 200, r.text
    qid = r.json()["data"]["id"]
    r = client.post(f"/admin/v1/template-center/questionnaires/{qid}/to-draft", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["kind"] == "herb"
    assert "from_questionnaire" in r.json()["data"]["content_json"]


def test_template_center_cleanup(client, admin_token):
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()
