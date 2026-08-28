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
# 必须在 import app 之前设置，路由模块读取环境变量。
# 注意：密码须满足 validate_password 策略（大小写+数字+特殊字符），
# 否则 create_user 会拒绝，导致测试库无法 seed 库内 admin 账号。
TEST_ADMIN_USER = os.environ.setdefault("QH_ADMIN_USER", "admin")
TEST_ADMIN_PASS = os.environ.setdefault("QH_ADMIN_PASS", "TestAdmin@2026")

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
def ensure_admin_in_db(client):
    """测试库默认无 admin 用户（seed_preset_data 只 seed 角色/权限，不建账号）。

    此处幂等创建库内 admin 账号并绑定 super_admin，等价于服务器端的
    bootstrap_rbac.py。作用：
    1. 让 /admin/v1/login 走 DB 通道（而非 env 应急回退），token sub = 真实用户 id；
    2. 使 change-password 等依赖用户实体的端点能按 id 查到当前用户。
    会话级、幂等：重复调用安全。
    """
    # 1) env 应急登录（库无 admin 时回退，恒可用，且口令即 TEST_ADMIN_PASS）
    resp = client.post("/admin/v1/login", json={
        "username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS,
    })
    assert resp.status_code == 200, f"env 登录失败: {resp.status_code} {resp.text[:200]}"
    tok = resp.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    # 2) 是否已存在（幂等）
    users = client.get("/admin/v1/users", headers=H).json()["data"]
    if any(u["username"] == TEST_ADMIN_USER for u in users):
        yield
        return
    # 3) 创建库内 admin 账号
    r = client.post("/admin/v1/users", json={
        "username": TEST_ADMIN_USER,
        "password": TEST_ADMIN_PASS,
        "tenant_id": "tenant_default",
    }, headers=H)
    assert r.status_code == 200, f"创建 admin 失败: {r.status_code} {r.text[:200]}"
    uid = r.json()["data"]["id"]
    # 4) 绑定 super_admin（摘掉自动挂的 health_user 默认角色已在服务端处理）
    client.post("/admin/v1/roles/assign", json={
        "user_id": uid, "role_name": "super_admin",
    }, headers=H)
    yield


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
    """API Key 签名请求头工厂：api_key_headers(method, path, body="") -> dict

    使用与网关 verify_api_key 完全一致的 HMAC-SHA256 规范报文签名
    （message = f"{app_key}\\n{method}\\n{path}\\n{timestamp}\\n{nonce}\\n{body}"），
    替代原先错误的 sha256(app_secret:ts:nonce) 写法，使 401 鉴权测试可信。
    """
    from qihuang_platform.gateway.auth import generate_api_signature

    app_key = api_key_info["app_key"]
    app_secret = api_key_info["app_secret"]

    def _sign(method: str, path: str, body: str = "") -> dict:
        import time
        import uuid

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex[:16]
        signature = generate_api_signature(app_key, app_secret, method, path, timestamp, nonce, body)
        return {
            "X-App-Key": app_key,
            "X-Signature": signature,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
        }

    return _sign


def pytest_configure(config):
    """注册自定义 marker"""
    config.addinivalue_line("markers", "slow: 慢速测试（需要 LLM 调用的）")
    config.addinivalue_line("markers", "integration: 集成测试")
    config.addinivalue_line("markers", "unit: 单元测试")
