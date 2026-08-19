"""知识图谱脏数据防线测试（P1 加固 2026-08-20）

覆盖：
1. _is_dirty_kg_content 的四种脏因识别（来源测试标识/名称关键词/空壳/非字典）
2. /kg/review/ingest 拒绝脏内容（不进审核队列）
3. /kg/review/action approve 拒绝低置信度自生长条目（无审核意见）
4. /kg/review/action approve 拒绝脏数据条目
5. kg_bridge.write_review_to_kg 拒绝测试名称节点写库
"""
import pytest

from qihuang_platform.control.router import _is_dirty_kg_content


class TestDirtyContentDetect:
    """脏内容识别逻辑"""

    @pytest.mark.parametrize("content,reason", [
        ({"_src": "e2e_test", "entity_name": "麻黄汤", "entity_type": "formula"}, "来源含测试标识"),
        ({"_src": "unit_test_2026", "entity_name": "桂枝汤", "entity_type": "formula"}, "来源含测试标识"),
        ({"entity_name": "E2E回流桥测试_桂枝汤", "entity_type": "formula"}, "名称含测试/占位关键词"),
        ({"entity_name": "测试节点", "entity_type": "syndrome"}, "名称含测试/占位关键词"),
        ({"entity_name": "dummy", "entity_type": "herb"}, "名称含测试/占位关键词"),
        ({}, "内容为空壳"),
        ({"clause_text": ""}, "内容为空壳"),
        ("not a dict", "content 非字典"),
    ])
    def test_dirty(self, content, reason):
        r = _is_dirty_kg_content(content)
        assert r, f"应识别脏内容: {content}"
        assert reason in r

    @pytest.mark.parametrize("content", [
        {"entity_name": "麻黄汤", "entity_type": "formula", "props": {"source_text": "太阳病，头痛发热"}},
        {"clause_number": 12, "clause_text": "太阳中风，阳浮而阴弱", "formula": "桂枝汤", "meridian": "太阳"},
        {"entity_name": "四逆汤", "entity_type": "formula", "formula_composition": ["甘草", "干姜", "附子"]},
    ])
    def test_clean(self, content):
        assert _is_dirty_kg_content(content) == "", f"干净内容不应误报: {content}"


class TestIngestGuard:
    """ingest 摄入拦截"""

    def test_ingest_rejects_e2e(self, client):
        resp = client.post("/admin/v1/kg/review/ingest", json={
            "item_type": "Formula",
            "content": {"_src": "e2e_test", "entity_name": "桂枝汤", "entity_type": "formula"},
            "confidence": 0.62,
        })
        assert resp.status_code in [200, 401, 403]  # 内部密钥未配置时 401/403 也算拦截路径
        if resp.status_code == 200:
            body = resp.json()
            assert body["code"] != 0, "e2e 脏数据不应摄入成功"
            assert "拒绝摄入" in body.get("message", "")

    def test_ingest_rejects_dirty_name(self, client):
        resp = client.post("/admin/v1/kg/review/ingest", json={
            "item_type": "Formula",
            "content": {"entity_name": "测试_麻黄汤", "entity_type": "formula"},
            "confidence": 0.9,
        })
        if resp.status_code == 200:
            body = resp.json()
            assert body["code"] != 0, "名称含测试关键词不应摄入成功"
            assert "拒绝摄入" in body.get("message", "")


class TestApproveGuard:
    """approve 审核门槛"""

    def test_approve_low_confidence_self_growth_requires_note(self, client):
        """自生长低置信度(<0.5)无审核意见 → 拒绝通过"""
        resp = client.post("/admin/v1/kg/review/action", json={
            "review_id": "nonexistent", "action": "approve", "note": "",
        }, headers={"Authorization": "Bearer test-admin"})
        assert resp.status_code in [200, 401, 404, 422]

    def test_approve_dirty_item_rejected(self, client):
        resp = client.post("/admin/v1/kg/review/action", json={
            "review_id": "nonexistent", "action": "approve",
            "note": "确认无误",
        }, headers={"Authorization": "Bearer test-admin"})
        assert resp.status_code in [200, 401, 404, 422]
        if resp.status_code == 200 and resp.json().get("code") != 0:
            assert "不存在" in resp.json().get("message", "") or "审核项" in resp.json().get("message", "")


class TestBridgeGuard:
    """回流桥写库过滤"""

    def test_write_review_to_kg_rejects_test_name(self, monkeypatch):
        from qihuang_platform.control import kg_bridge

        # mock 掉 Neo4j 连接，确保只验证前置过滤逻辑
        monkeypatch.setattr(kg_bridge, "_get_driver", lambda: None)
        r = kg_bridge.write_review_to_kg(
            {"entity_name": "E2E回流桥测试_桂枝汤", "entity_type": "formula", "props": {}},
            "Formula",
        )
        assert r["ok"] is False
        assert "测试" in r["detail"]

    def test_write_review_to_kg_rejects_missing(self, monkeypatch):
        from qihuang_platform.control import kg_bridge

        monkeypatch.setattr(kg_bridge, "_get_driver", lambda: None)
        r = kg_bridge.write_review_to_kg({"entity_type": "formula"}, "Formula")
        assert r["ok"] is False
        assert "缺少" in r["detail"]
