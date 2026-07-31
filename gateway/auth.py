"""
API Gateway - 双鉴权体系
- /api/v1/*, /admin/v1/*: JWT Token (access_token 2h + refresh_token 30d)
- /open/v1/*: API Key + HMAC-SHA256 签名
"""
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import jwt

# ---- 配置 ----
JWT_SECRET = "qihuang-jwt-secret-dev-32bytes-ok!"  # ≥32 bytes for HS256, 生产从环境变量读取
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2小时
REFRESH_TOKEN_EXPIRE_DAYS = 30    # 30天

# ---- 内存存储（开发阶段，后续替换为Redis/PostgreSQL）----
_users_db: Dict[str, dict] = {}        # user_id -> user_info
_api_keys_db: Dict[str, dict] = {}     # app_key -> {app_secret, tenant_id, ...}
_token_blacklist: set = set()          # 已撤销的token jti


# ========== JWT Token 体系 ==========

def create_access_token(user_id: str, tenant_id: str, org_id: str,
                        roles: list[str], extra: dict = None) -> str:
    """签发 access_token (2h有效期)"""
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "roles": roles,
        "jti": jti,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, access_jti: str) -> str:
    """签发 refresh_token (30d有效期)，绑定一个access_token的jti"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": str(uuid.uuid4()),
        "type": "refresh",
        "bound_access_jti": access_jti,
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码并验证 token"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def verify_token(token: str, token_type: str = "access") -> Optional[dict]:
    """验证 token 有效性，返回 payload 或 None"""
    try:
        payload = decode_token(token)
        if payload.get("type") != token_type:
            return None
        if payload["jti"] in _token_blacklist:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def revoke_token(jti: str):
    """撤销 token（加入黑名单）"""
    _token_blacklist.add(jti)


def register_user(user_id: str, tenant_id: str, org_id: str,
                  roles: list[str], extra: dict = None) -> dict:
    """注册/更新用户信息（内存存储）"""
    user = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "roles": roles,
        "extra": extra or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _users_db[user_id] = user
    return user


def get_user(user_id: str) -> Optional[dict]:
    return _users_db.get(user_id)


# ========== API Key HMAC-SHA256 签名体系 ==========

def register_api_key(app_key: str, app_secret: str, tenant_id: str,
                     plan: str = "standard", extra: dict = None) -> dict:
    """注册 API Key"""
    key_info = {
        "app_key": app_key,
        "app_secret": app_secret,
        "tenant_id": tenant_id,
        "plan": plan,
        "status": "active",
        "extra": extra or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _api_keys_db[app_key] = key_info
    return key_info


def generate_api_signature(app_key: str, app_secret: str, method: str,
                           path: str, timestamp: str, nonce: str,
                           body: str = "") -> str:
    """生成 API Key HMAC-SHA256 签名"""
    message = f"{app_key}\n{method}\n{path}\n{timestamp}\n{nonce}\n{body}"
    return hmac.new(
        app_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_api_key(app_key: str, signature: str, method: str,
                   path: str, timestamp: str, nonce: str,
                   body: str = "") -> Optional[dict]:
    """验证 API Key 签名，返回 key_info 或 None"""
    key_info = _api_keys_db.get(app_key)
    if not key_info or key_info["status"] != "active":
        return None

    # 时间窗 ±5 分钟
    try:
        ts = int(timestamp)
        now_ts = int(time.time())
        if abs(now_ts - ts) > 300:
            return None
    except (ValueError, TypeError):
        return None

    # 验证签名
    expected = generate_api_signature(
        app_key, key_info["app_secret"], method, path, timestamp, nonce, body
    )
    # 常量时间比较防时序攻击
    if not hmac.compare_digest(expected, signature):
        return None

    return key_info


def get_api_key_info(app_key: str) -> Optional[dict]:
    return _api_keys_db.get(app_key)


def list_api_keys() -> list:
    """列出所有API Key"""
    return [
        {"id": k, "api_key": k, "status": v.get("status", "active"),
         "tenant_id": v.get("tenant_id"), "plan": v.get("plan"),
         "note": v.get("extra", {}).get("note", k[:16]),
         "created_at": v.get("created_at", "")}
        for k, v in _api_keys_db.items()
    ]


def delete_api_key(app_key: str) -> bool:
    """删除/吊销API Key"""
    if app_key in _api_keys_db:
        _api_keys_db[app_key]["status"] = "revoked"
        return True
    return False


# ========== 工具函数 ==========

def generate_nonce() -> str:
    """生成随机 nonce（防重放）"""
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]


def get_timestamp() -> str:
    """获取当前时间戳字符串"""
    return str(int(time.time()))
