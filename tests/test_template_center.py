"""
多租户能力中心（二期）— 模板中心 HTTP 端到端验证

覆盖：模板 CRUD / 编辑版本快照 / 克隆 / 提交审核 / 平台采纳·强下架 / 问卷→模板草稿。
鉴权：admin_token（super_admin）即可通过 get_current_user 与 get_current_admin。
"""
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import (
    DbTemplate, TemplateOwnership, TemplateReviewSubmission, TemplateVersion,
    StoreQuestionnaire, CrossTenantSyncLog, PluginDisableRequest,
)


def _cleanup(db):
    db.query(TemplateReviewSubmission).delete()
    db.query(TemplateVersion).delete()
    db.query(CrossTenantSyncLog).delete()
    db.query(PluginDisableRequest).delete()
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


def _open_hmac_headers(api_key_info, method, path, payload):
    """按服务端 HMAC-SHA256 规范逐请求签名（app_key\\nmethod\\npath\\nts\\nnonce\\nbody）。"""
    import json
    import time
    import uuid
    from qihuang_platform.gateway.auth import generate_api_signature
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]
    body = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    sig = generate_api_signature(
        api_key_info["app_key"], api_key_info["app_secret"],
        method, path, ts, nonce, body)
    return {
        "X-App-Key": api_key_info["app_key"],
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "Content-Type": "application/json",
    }, body


def test_cross_tenant_sync_and_disable_request(client, admin_token, api_key_info):
    """⑤ 跨租户双向同步 + ⑤-a 关插件审核流端到端。"""
    H = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    try:
        # ── ⑤ 平台→机构批量下发 ──
        r = client.post("/admin/v1/template-center/templates", headers=H, json={
            "name": "官方辨证模板", "kind": "syndrome",
            "content_json": {"fields": ["寒热"]}, "visibility": "public",
        })
        assert r.status_code == 200, r.text
        src_id = r.json()["data"]["id"]

        # 下发到 org_default + 一个不存在的机构（应跳过不报错）
        r = client.post(
            f"/admin/v1/template-center/templates/{src_id}/push", headers=H,
            json={"target_org_ids": ["org_default", "org_not_exist_xyz"],
                  "visibility": "private"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["pushed_count"] == 1

        # 该机构列表应出现副本，且血缘指向源
        clones = db.query(DbTemplate).filter(
            DbTemplate.parent_template_id == src_id).all()
        assert len(clones) == 1, f"血缘副本数={len(clones)}"
        own = db.query(TemplateOwnership).filter(
            TemplateOwnership.template_id == clones[0].id).first()
        assert own.owner_org_id == "org_default"
        assert own.source == "clone"

        # 血缘视图
        r = client.get(
            f"/admin/v1/template-center/templates/{src_id}/lineage", headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["clone_count"] == 1

        # 审计日志
        logs = db.query(CrossTenantSyncLog).filter(
            CrossTenantSyncLog.action == "push").all()
        assert len(logs) == 1 and logs[0].to_org_id == "org_default"

        # ── ⑤ 机构→平台贡献 ──
        r = client.post("/admin/v1/template-center/templates", headers=H, json={
            "name": "门店自研模板", "kind": "herb",
            "content_json": {"fields": ["舌象"]}, "org_id": "org_default",
            "visibility": "private",
        })
        assert r.status_code == 200, r.text
        org_tpl_id = r.json()["data"]["id"]
        r = client.post(
            f"/admin/v1/template-center/templates/{org_tpl_id}/contribute",
            headers=H, json={"visibility": "public", "submit_for_review": True})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["ownership"]["source"] == "clone"
        # 平台池模板（tenant_id=None）应可见
        contrib = db.query(DbTemplate).filter(
            DbTemplate.parent_template_id == org_tpl_id).first()
        assert contrib is not None and contrib.tenant_id is None
        assert r.json()["data"].get("review_status") == "PENDING"

        # ── ⑤-a 关插件申请（开放通道，HB 视角，HMAC 真签名）──
        disable_path = "/api/v1/template-center/plugins/disable-request"
        hh, body = _open_hmac_headers(api_key_info, "POST", disable_path, {
            "org_id": "org_default",
            "plugin_key": "health-advisor",
            "reason": "暂时不用"})
        r = client.post(disable_path, headers=hh, content=body)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "PENDING"
        req_id = r.json()["data"]["id"]

        # 幂等：重复提交不新建（同样签名参数）
        hh, body = _open_hmac_headers(api_key_info, "POST", disable_path, {
            "org_id": "org_default",
            "plugin_key": "health-advisor"})
        r = client.post(disable_path, headers=hh, content=body)
        assert r.json()["data"]["id"] == req_id

        # 平台列表可见
        r = client.get("/admin/v1/template-center/plugin-disable-requests",
                       headers=H, params={"status": "PENDING"})
        assert r.status_code == 200, r.text
        assert any(x["id"] == req_id for x in r.json()["data"]["items"])

        # 平台批准
        r = client.post(
            f"/admin/v1/template-center/plugin-disable-requests/{req_id}/approve",
            headers=H, json={"review_note": "同意"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "APPROVED"

        # 批准后再申请 → 新 PENDING
        hh, body = _open_hmac_headers(api_key_info, "POST", disable_path, {
            "org_id": "org_default",
            "plugin_key": "health-advisor"})
        r = client.post(disable_path, headers=hh, content=body)
        assert r.json()["data"]["status"] == "PENDING"
    finally:
        db.close()


def test_template_export_import(client, admin_token):
    """⑥ Stage C：导出模板 JSON → 再导入为新模板（版本快照随之克隆）。"""
    H = {"Authorization": f"Bearer {admin_token}"}

    # 1) 建模板并编辑一次（产生 v1→v2 版本快照）
    r = client.post("/admin/v1/template-center/templates", headers=H, json={
        "name": "待导出模板", "kind": "herb",
        "content_json": {"fields": ["a"]}, "visibility": "private",
    })
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    r = client.put(f"/admin/v1/template-center/templates/{tid}", headers=H, json={
        "content_json": {"fields": ["a", "b"]},
    })
    assert r.status_code == 200, r.text

    # 2) 导出
    r = client.get(f"/admin/v1/template-center/templates/{tid}/export", headers=H)
    assert r.status_code == 200, r.text
    payload = r.json()["data"]
    assert payload["template"]["content_json"] == {"fields": ["a", "b"]}
    assert len(payload["versions"]) >= 1

    # 3) 导入为新模板（机构私有）
    r = client.post("/admin/v1/template-center/templates/import", headers=H, json={
        "export": payload, "target_org_id": "org_default", "visibility": "private",
    })
    assert r.status_code == 200, r.text
    new_id = r.json()["data"]["id"]
    assert new_id != tid
    assert r.json()["data"]["ownership"]["source"] == "self"
    assert r.json()["data"]["content_json"] == {"fields": ["a", "b"]}
    # 版本快照应随导入克隆
    assert len(r.json()["data"]["versions"]) >= 1


def test_template_center_cleanup(client, admin_token):
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()
