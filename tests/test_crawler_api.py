"""
tests/test_crawler_api · 爬虫摄入 HTTP 触发端点接线测试

验证：POST /admin/v1/crawler/run
  - dry_run=True：返回正确计数（total/ingested/skipped/by_type），不落库
  - 未知 source_key：400 + code=400 统一格式
  - allow_network=False 时 HttpPageAdapter 不联网（tcm-encyclopedia 返回 0 条，不报错）
"""
import pytest


def test_crawler_run_dry_run(client):
    resp = client.post(
        "/admin/v1/crawler/run",
        json={"source_key": "static-demo", "dry_run": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    d = body["data"]
    assert d["total"] == 5, d
    assert d["ingested"] == 5, d
    assert d["skipped"] == 0, d
    assert d["by_type"] == {"herb": 1, "formula": 1, "disease": 1, "syndrome": 1, "drug": 1}, d
    assert d["persisted"] is False
    assert d["ids"] == []


def test_crawler_run_unknown_source(client):
    resp = client.post(
        "/admin/v1/crawler/run",
        json={"source_key": "not-a-real-source", "dry_run": True},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == 400, body
    assert "未知数据源" in body["message"], body


def test_crawler_run_network_off_by_default(client):
    # tcm-encyclopedia 真实抓取适配器默认 allow_network=False → 不联网、返回 0 条、不报错
    resp = client.post(
        "/admin/v1/crawler/run",
        json={"source_key": "tcm-encyclopedia", "dry_run": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    assert body["data"]["total"] == 0, body
    assert body["data"]["ingested"] == 0, body
