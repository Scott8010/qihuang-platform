"""
API Gateway - 双鉴权体系
- /api/v1/*, /admin/v1/*: JWT Token (access_token 2h + refresh_token 30d)
- /open/v1/*: API Key + HMAC-SHA256 签名
"""
import hashlib
import hmac
import os
import time
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import jwt
import logging

logger = logging.getLogger("gateway.auth")

# ---- 配置 ----
# 生产：JWT 签名密钥必须由环境变量 QH_JWT_SECRET 注入（强随机 ≥32 bytes）。
# 未设置时回退到内置开发默认值并打告警——禁止无密钥直接把可伪造 token 放上生产。
JWT_SECRET = os.environ.get("QH_JWT_SECRET")
if not JWT_SECRET:
    warnings.warn(
        "QH_JWT_SECRET 未设置，使用内置默认 JWT 密钥（仅限开发/测试环境；"
        "生产必须设置强随机值，否则 token 可被任意伪造）",
        stacklevel=2,
    )
    JWT_SECRET = "qihuang-jwt-secret-dev-32bytes-ok!"  # ≥32 bytes for HS256 (dev fallback)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2小时
REFRESH_TOKEN_EXPIRE_DAYS = 30    # 30天

# ---- 内存存储（开发阶段，后续替换为Redis/PostgreSQL）----
_users_db: Dict[str, dict] = {}        # user_id -> user_info
_api_keys_db: Dict[str, dict] = {}     # app_key -> {app_secret, tenant_id, ...}
_token_blacklist: set = set()          # 已撤销的token jti
_used_nonces: Dict[str, float] = {}    # nonce 防重放：app_key:nonce -> 使用时间戳


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


def revoke_token(jti: str, expires_ts: Optional[int] = None):
    """撤销 token（加入内存黑名单 + 持久化 DB，防重启复活）。

    expires_ts: token 的 exp（unix 秒）；未提供时按 refresh 最大有效期保守兜底。
    """
    if not jti:
        return
    _token_blacklist.add(jti)
    # 持久化到 DB（防服务重启后黑名单清空 → 已吊销 token 复活）
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import RevokedToken
        if expires_ts:
            exp = datetime.fromtimestamp(int(expires_ts), tz=timezone.utc)
        else:
            exp = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        db = SessionLocal()
        try:
            if not db.query(RevokedToken).filter_by(jti=jti).first():
                db.add(RevokedToken(jti=jti, expires_at=exp))
                db.commit()
        finally:
            db.close()
    except Exception as e:  # 持久化失败不阻断吊销（内存仍生效，仅失去重启恢复能力）
        logger.warning("[auth] 黑名单持久化失败: %s", e)


def load_token_blacklist() -> int:
    """启动冷加载：从 DB 恢复未过期的吊销 jti 到内存黑名单（防重启复活）。"""
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import RevokedToken
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            rows = db.query(RevokedToken).filter(RevokedToken.expires_at > now).all()
            for r in rows:
                _token_blacklist.add(r.jti)
            return len(rows)
        finally:
            db.close()
    except Exception as e:
        logger.warning("[auth] 黑名单冷加载失败: %s", e)
        return 0


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
    """按 user_id 取用户信息（#9 落库：内存优先，回退 DB，重启不丢真实用户身份）

    - 内存态覆盖微信/短信/mock 等开发登录（user_id 非 DB 主键，仅运行时存在）
    - DB 态覆盖 password 真实登录用户（user_id = User.id），服务重启后仍可鉴权
    - 已禁用/注销的用户在 DB 回退路径直接判为不存在（吊销即时生效）
    """
    u = _users_db.get(user_id)
    if u:
        return u
    # 回退 DB（适用于重启后真实用户态恢复）
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import User
        db = SessionLocal()
        try:
            row = db.query(User).filter_by(id=user_id).first()
            if row:
                if row.status != "active":
                    return None
                return {
                    "user_id": row.id,
                    "tenant_id": row.tenant_id,
                    "org_id": row.org_id,
                    "roles": (row.extra or {}).get("roles", []) if row.extra else [],
                    "status": row.status,
                }
        finally:
            db.close()
    except Exception:
        # DB 不可用时退回内存态结果（None），不阻断鉴权链
        pass
    return None


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

    # 验证签名（优先主密钥）
    expected = generate_api_signature(
        app_key, key_info["app_secret"], method, path, timestamp, nonce, body
    )
    if hmac.compare_digest(expected, signature):
        return _accept_and_record_nonce(app_key, nonce, key_info)

    # 密钥轮换并行期：旧密钥仅在 72h 内可被接受（带时间戳判断）
    now_ts = time.time()
    for old in key_info.get("prev_secrets", []):
        old_secret = old["secret"] if isinstance(old, dict) else old
        rotated_at = old["rotated_at"] if isinstance(old, dict) else None
        # 旧格式（无时间戳）或超过 72h 的旧密钥一律不再接受（安全优先）
        if rotated_at is None or (now_ts - rotated_at) > 72 * 3600:
            continue
        old_expected = generate_api_signature(
            app_key, old_secret, method, path, timestamp, nonce, body
        )
        if hmac.compare_digest(old_expected, signature):
            return _accept_and_record_nonce(app_key, nonce, key_info)

    return None


def _accept_and_record_nonce(app_key: str, nonce: str, key_info: dict) -> Optional[dict]:
    """签名通过后记录 nonce（5 分钟窗口内同 nonce 拒绝重放）。"""
    now_ts = time.time()
    key = f"{app_key}:{nonce}"
    last = _used_nonces.get(key)
    if last is not None and (now_ts - last) < 300:
        logger.warning("[auth] 检测到 nonce 重放: app_key=%s", app_key)
        return None
    _used_nonces[key] = now_ts
    # 惰性清理过期 nonce，防内存无限增长
    if len(_used_nonces) > 10000:
        expired = [k for k, v in _used_nonces.items() if now_ts - v >= 300]
        for k in expired:
            del _used_nonces[k]
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


def update_api_key_secret(app_key: str, new_secret: str,
                           prev_secret: Optional[str] = None,
                           status: Optional[str] = None) -> bool:
    """原地更新内存中的 API Key secret（用于密钥轮换）。

    - new_secret: 新密钥，立即在内存鉴权表生效（无需重启服务）。
    - prev_secret: 旧密钥原文，记入 prev_secrets 以支持轮换后 72h 并行期
      （旧密钥仍可被 verify_api_key 接受）。
    - status: 可选，更新状态（如 'revoked'）。
    返回是否找到该 key 并更新成功。
    """
    key_info = _api_keys_db.get(app_key)
    if not key_info:
        return False
    if prev_secret:
        prev_list = key_info.setdefault("prev_secrets", [])
        # 新版：prev_secrets 存 {secret, rotated_at}，供 verify 判断 72h 并行期
        existing = [x["secret"] if isinstance(x, dict) else x for x in prev_list]
        if prev_secret not in existing:
            prev_list.append({"secret": prev_secret, "rotated_at": time.time()})
            if len(prev_list) > 3:
                key_info["prev_secrets"] = prev_list[-3:]
    key_info["app_secret"] = new_secret
    if status:
        key_info["status"] = status
    key_info["updated_at"] = datetime.now(timezone.utc).isoformat()
    return True


# ========== 工具函数 ==========

def generate_nonce() -> str:
    """生成随机 nonce（防重放）"""
    return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]


def get_timestamp() -> str:
    """获取当前时间戳字符串"""
    return str(int(time.time()))
