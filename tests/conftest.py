"""
tests/conftest.py — 测试全局 fixtures
FastAPI TestClient + 独立测试数据库 + 预置认证Token
"""
import os
import sys
from pathlib import Path

# ─── 项目路径注入 ───
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── 测试数据库 — 优先环境变量，默认 SQLite ───
if "QH_DATABASE_URL" not in os.environ:
    os.environ["QH_DATABASE_URL"] = "sqlite:///./test_qihuang_platform.db"
if "QH_REDIS_URL" not in os.environ:
    os.environ["QH_REDIS_URL"] = ""  # 空=降级到内存

# ─── 管理员口令（正式登录通道，dev 后门已下线）───
# 必须在 import app 之前设置，路由模块读取环境变量
TEST_ADMIN_USER = os.environ.setdefault("QH_ADMIN_USER", "admin")
TEST_ADMIN_PASS = os.environ.setdefault("QH_ADMIN_PASS", "test_admin_pass_2026")

# dev 路由默认关闭（与生产一致）；需要时用 ENABLE_DEV_ROUTES=1 显式打开
DEV_ROUTES_ENABLED = os.environ.setdefault("ENABLE_DEV_ROUTES", "0") == "1"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """会话级 TestClient（使用 ASGITransport，无需启动服务器）"""
    from qihuang_platform.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    """获取管理员 JWT Token（走正式登录通道 /admin/v1/login，会话级复用）"""
    resp = client.post("/admin/v1/login", json={
        "username": TEST_ADMIN_USER,
        "password": TEST_ADMIN_PASS,
    })
    assert resp.status_code == 200, f"管理员登录失败: {resp.status_code} {resp.text[:200]}"
    return resp.json()["data"]["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """管理员请求头"""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="function")
def user_token(client):
    """获取普通用户 JWT Token（function级，防止logout撤销影响后续测试）"""
    resp = client.post("/api/v1/auth/login", json={
        "login_type": "wechat",
        "code": "mock_test_code",
    })
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


@pytest.fixture(scope="function")
def user_headers(user_token):
    """普通用户请求头"""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture(scope="session")
def api_key_info(client, admin_headers):
    """创建 API Key（会话级）"""
    resp = client.post("/admin/v1/api-keys/", json={
        "tenant_id": "tenant_default",
        "plan": "standard",
    }, headers=admin_headers)
    assert resp.status_code == 200
    return resp.json()["data"]


@pytest.fixture(scope="session")
def api_key_headers(api_key_info):
    """API Key 签名请求头"""
    import hashlib
    import time
    import uuid

    app_key = api_key_info["app_key"]
    app_secret = api_key_info["app_secret"]
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]
    # 简单签名: HMAC-SHA256(path+timestamp+nonce+body)
    signature = hashlib.sha256(
        f"{app_secret}:{timestamp}:{nonce}".encode()
    ).hexdigest()

    return {
        "X-App-Key": app_key,
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
    }


def pytest_configure(config):
    """注册自定义 marker"""
    config.addinivalue_line("markers", "slow: 慢速测试（需要 LLM 调用的）")
    config.addinivalue_line("markers", "integration: 集成测试")
    config.addinivalue_line("markers", "unit: 单元测试")
