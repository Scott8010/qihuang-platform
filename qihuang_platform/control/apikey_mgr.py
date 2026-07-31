"""
P2第二批: API Key 管理端点 — 密钥轮换/详情/趋势/日志/IP白名单

在 gateway/router.py 已有的 POST/GET/DELETE 基础能力之上，补充5个交互端点。
使用 DB ApiKey 模型 + CallLog 模型，与 gateway 的内存存储并存。
"""
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from qihuang_platform.gateway.deps import get_current_admin
from qihuang_platform.gateway.response import success, error, paginated
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import ApiKey, CallLog, Tenant

router = APIRouter(prefix="/admin/v1/api-keys", tags=["API Key管理"])

def _uid():
    import uuid
    return uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════
# P2-AK1: 密钥详情
# ═══════════════════════════════════════════════════════════

@router.get("/{key_id}", summary="获取密钥详情")
async def get_api_key_detail(
    key_id: str,
    admin: dict = Depends(get_current_admin),
):
    """
    返回单个 API Key 的完整详情：基本信息 + 扩展字段(purpose/QPS/expires/IP白名单) + 最近使用时间
    """
    db = SessionLocal()
    try:
        k = db.query(ApiKey).filter_by(id=key_id).first()
        if not k:
            # 兼容: 也用 app_key 查找
            k = db.query(ApiKey).filter_by(app_key=key_id).first()
        if not k:
            return error("NOT_FOUND", message="密钥不存在")

        tenant = db.query(Tenant).filter_by(id=k.tenant_id).first()

        # 近30天调用量
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        recent_calls = db.query(func.count(CallLog.id)).filter(
            CallLog.app_key == k.app_key,
            CallLog.timestamp >= thirty_days_ago,
        ).scalar() or 0

        extra = k.extra or {}
        return success(data={
            "id": k.id,
            "app_key": k.app_key,
            "tenant_id": k.tenant_id,
            "tenant_name": tenant.display_name if tenant else "",
            "plan_id": k.plan_id,
            "status": k.status,
            "purpose": extra.get("purpose", "PROD"),
            "qps": extra.get("qps", 10),
            "expires": extra.get("expires", ""),
            "ip_whitelist": extra.get("ip_whitelist", []),
            "note": extra.get("note", ""),
            "used_calls": recent_calls,
            "created_at": k.created_at.isoformat() if k.created_at else "",
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else "",
        })
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-AK2: 密钥轮换
# ═══════════════════════════════════════════════════════════

class RotateResponse(BaseModel):
    old_app_key: str = ""
    old_secret: str = ""
    new_app_key: str = ""
    new_secret: str = ""
    overlap_end: str = ""  # 新旧并行截止时间 (72h)


@router.post("/{key_id}/rotate", summary="轮换密钥")
async def rotate_api_key(
    key_id: str,
    admin: dict = Depends(get_current_admin),
):
    """
    密钥轮换: 生成新 app_secret，旧密钥 72h 内仍然有效。
    存储旧密钥到 extra.prev_secrets 数组用于验证。
    """
    db = SessionLocal()
    try:
        k = db.query(ApiKey).filter_by(id=key_id).first()
        if not k:
            k = db.query(ApiKey).filter_by(app_key=key_id).first()
        if not k:
            return error("NOT_FOUND", message="密钥不存在")
        if k.status != "active":
            return error("INVALID_STATE", message="只能轮换活跃密钥")

        import uuid, hashlib, secrets

        old_secret = k.app_secret
        old_key = k.app_key

        # 生成新 secret
        new_secret = f"sk_{secrets.token_hex(32)}"
        new_app_key = k.app_key  # 保持 app_key 不变，仅换 secret

        overlap_end = datetime.now(timezone.utc) + timedelta(hours=72)

        extra = k.extra or {}
        prev = extra.get("prev_secrets", [])
        prev.append({
            "secret_hash": hashlib.sha256(old_secret.encode()).hexdigest()[:16],
            "expire_at": overlap_end.isoformat(),
            "rotated_at": datetime.now(timezone.utc).isoformat(),
        })
        # 只保留最近3个旧密钥
        if len(prev) > 3:
            prev = prev[-3:]
        extra["prev_secrets"] = prev

        k.app_secret = new_secret
        k.extra = extra
        k.updated_at = datetime.now(timezone.utc)
        db.commit()

        return success(data={
            "old_app_key": old_key,
            "old_secret": old_secret,  # 仅此一次返回旧密钥原文
            "new_app_key": new_app_key,
            "new_secret": new_secret,  # 仅此一次返回新密钥原文
            "overlap_end": overlap_end.isoformat(),
        }, message="密钥已轮换，旧密钥72小时内仍有效")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-AK3: 近14天调用趋势
# ═══════════════════════════════════════════════════════════

@router.get("/{key_id}/trend", summary="密钥调用趋势")
async def get_key_trend(
    key_id: str,
    admin: dict = Depends(get_current_admin),
):
    """
    返回近14天每天调用量，用于绘制趋势图 (AreaChart)
    """
    db = SessionLocal()
    try:
        k = db.query(ApiKey).filter_by(id=key_id).first()
        if not k:
            k = db.query(ApiKey).filter_by(app_key=key_id).first()
        if not k:
            return error("NOT_FOUND", message="密钥不存在")

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        trends = []
        for i in range(13, -1, -1):
            day_start = today - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            cnt = db.query(func.count(CallLog.id)).filter(
                CallLog.app_key == k.app_key,
                CallLog.timestamp >= day_start,
                CallLog.timestamp < day_end,
            ).scalar() or 0
            trends.append({
                "date": day_start.strftime("%m-%d"),
                "calls": cnt,
            })

        return success(data={"trends": trends})
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-AK4: 密钥调用日志
# ═══════════════════════════════════════════════════════════

@router.get("/{key_id}/logs", summary="密钥调用日志")
async def get_key_logs(
    key_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
):
    """
    分页返回密钥最近调用日志 (endpoint/IP/latency/tokens/cost/时间)
    """
    db = SessionLocal()
    try:
        k = db.query(ApiKey).filter_by(id=key_id).first()
        if not k:
            k = db.query(ApiKey).filter_by(app_key=key_id).first()
        if not k:
            return error("NOT_FOUND", message="密钥不存在")

        q = db.query(CallLog).filter(CallLog.app_key == k.app_key).order_by(CallLog.timestamp.desc())

        total = q.count()
        items = q.offset((page - 1) * page_size).limit(page_size).all()

        return paginated(
            items=[{
                "id": l.id,
                "trace_id": l.trace_id,
                "endpoint": l.endpoint,
                "method": l.method,
                "status_code": l.status_code,
                "latency_ms": l.latency_ms,
                "tokens_used": l.tokens_used,
                "cost_cents": l.cost_cents,
                "ip": l.ip,
                "timestamp": l.timestamp.isoformat() if l.timestamp else "",
            } for l in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P2-AK5: IP 白名单管理
# ═══════════════════════════════════════════════════════════

class IPWhitelistRequest(BaseModel):
    ip_list: list[str] = Field(default=[], description="IP/CIDR 白名单，空列表表示关闭白名单")
    enabled: bool = Field(default=True, description="是否启用白名单")


@router.put("/{key_id}/ip-whitelist", summary="管理IP白名单")
async def update_ip_whitelist(
    key_id: str,
    req: IPWhitelistRequest,
    admin: dict = Depends(get_current_admin),
):
    """
    设置/更新密钥的 IP 白名单。enabled=false 时关闭白名单检查。
    """
    db = SessionLocal()
    try:
        k = db.query(ApiKey).filter_by(id=key_id).first()
        if not k:
            k = db.query(ApiKey).filter_by(app_key=key_id).first()
        if not k:
            return error("NOT_FOUND", message="密钥不存在")

        extra = k.extra or {}
        extra["ip_whitelist"] = req.ip_list
        extra["ip_whitelist_enabled"] = req.enabled
        k.extra = extra
        db.commit()

        return success(data={
            "ip_whitelist": req.ip_list,
            "enabled": req.enabled,
        }, message=f"IP白名单已更新 ({len(req.ip_list)} 条规则)")
    except Exception as e:
        db.rollback()
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# P1-A: API Key 列表（DB）
# ═══════════════════════════════════════════════════════════

@router.get("/", summary="列出所有API Key（DB）")
async def list_api_keys_db(
    tenant_id: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin),
):
    """
    从数据库列出所有 API Key，支持按租户过滤。
    因 apikey_mgr 先于 gateway 注册，此端点优先于网关内存版本。
    """
    db = SessionLocal()
    try:
        q = db.query(ApiKey)
        if tenant_id:
            q = q.filter(ApiKey.tenant_id == tenant_id)
        keys = q.order_by(ApiKey.created_at.desc()).all()

        items = []
        for k in keys:
            tenant = db.query(Tenant).filter_by(id=k.tenant_id).first()
            extra = k.extra or {}
            items.append({
                "id": k.id,
                "app_key": k.app_key,
                "tenant_id": k.tenant_id,
                "tenant_name": tenant.display_name if tenant else "",
                "plan_id": k.plan_id,
                "status": k.status,
                "purpose": extra.get("purpose", "PROD"),
                "qps": extra.get("qps", 10),
                "expires": extra.get("expires", ""),
                "ip_whitelist": extra.get("ip_whitelist", []),
                "note": extra.get("note", ""),
                "used_calls": 0,
                "created_at": k.created_at.isoformat() if k.created_at else "",
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else "",
            })

        return success(data={"total": len(items), "items": items})
    except Exception as e:
        return error("INTERNAL_ERROR", message=str(e))
    finally:
        db.close()
