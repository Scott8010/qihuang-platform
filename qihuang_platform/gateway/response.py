"""
API Gateway - 统一响应包装
格式: {code, message, data, trace_id}
"""

import uuid
from typing import Any, Optional

from fastapi.responses import JSONResponse

# ---- 标准错误码 ----
ERROR_CODES = {
    # 通用 1xxx
    "SUCCESS":                {"code": 0, "message": "成功"},
    "INVALID_PARAM":          {"code": 1001, "message": "参数错误"},
    "MISSING_PARAM":          {"code": 1002, "message": "缺少必要参数"},
    "INVALID_FORMAT":         {"code": 1003, "message": "格式错误"},
    "ORG_ID_REQUIRED":        {"code": 1004, "message": "API Key 路径创建机构模板必须携带 org_id"},
    "INVALID_ORG":            {"code": 1005, "message": "机构不存在或不属于当前租户"},
    "ORG_MISMATCH":           {"code": 1006, "message": "机构级角色必须在其所属机构内分配"},

    # 认证 2xxx
    "UNAUTHORIZED":           {"code": 2001, "message": "未授权"},
    "TOKEN_EXPIRED":          {"code": 2002, "message": "Token已过期"},
    "TOKEN_INVALID":          {"code": 2003, "message": "Token无效"},
    "TOKEN_REVOKED":          {"code": 2004, "message": "Token已被撤销"},
    "API_KEY_INVALID":        {"code": 2005, "message": "API Key无效"},
    "SIGNATURE_MISMATCH":     {"code": 2006, "message": "签名验证失败"},
    "TIMESTAMP_EXPIRED":      {"code": 2007, "message": "时间戳过期"},
    "FORBIDDEN":              {"code": 2008, "message": "权限不足"},
    "AGENT_FORBIDDEN":       {"code": 2008, "message": "Agent 能力未授权（套餐未包含）"},
    "IP_NOT_ALLOWED":         {"code": 2009, "message": "IP不在白名单"},

    # 限流 3xxx
    "RATE_LIMITED":           {"code": 3001, "message": "请求过于频繁"},
    "QUOTA_EXCEEDED":         {"code": 3002, "message": "配额已用完"},

    # 服务 5xxx
    "INTERNAL_ERROR":         {"code": 5001, "message": "服务内部错误"},
    "SERVICE_UNAVAILABLE":    {"code": 5002, "message": "服务不可用"},
    "LLM_DOWN":               {"code": 5003, "message": "AI服务暂不可用"},
    "UPSTREAM_TIMEOUT":       {"code": 5004, "message": "上游服务超时"},

    # 业务 6xxx
    "NOT_FOUND":              {"code": 6001, "message": "资源不存在"},
    "DUPLICATE":              {"code": 6002, "message": "资源已存在"},
    "SCENE_DISABLED":         {"code": 6003, "message": "该场景未开通"},
    "COMPLIANCE_BLOCKED":    {"code": 6004, "message": "内容合规拦截（违规语料未落库）"},
}


def success(data: Any = None, message: str = None) -> dict:
    """成功响应"""
    return {
        "code": 0,
        "message": message or "成功",
        "data": data,
        "trace_id": str(uuid.uuid4())[:8],
    }


# 错误码 → 推荐 HTTP 状态码（B9：让错误响应带正确状态码，而非一律 200）
DEFAULT_STATUS_BY_CODE: dict = {
    1001: 400, 1002: 400, 1003: 400, 1004: 400, 1005: 400, 1006: 400,  # 参数类
    2001: 401, 2002: 401, 2003: 401, 2004: 401, 2005: 401, 2006: 401, 2007: 401,  # 认证
    2008: 403, 2009: 403,  # 权限/IP
    3001: 429, 3002: 402,  # 限流 / 配额
    5001: 500, 5002: 503, 5003: 503, 5004: 504,  # 服务
    6001: 404, 6002: 409, 6003: 403, 6004: 403,  # 业务资源
}


def fail(code_key: str, message: str = None, data: Any = None, http_status: int = None):
    """错误响应（带正确 HTTP 状态码，B9 修复）。

    与 error() 语义一致，但返回 JSONResponse 并带状态码；用于需要「HTTP 状态码≠200」
    的错误出口（如 onboard 失败、参数非法、资源不存在）。error() 仍返回纯 dict 供
    内部/旁路使用，两者不冲突。
    """
    info = ERROR_CODES.get(code_key, {"code": 5001, "message": "未知错误"})
    status = http_status or DEFAULT_STATUS_BY_CODE.get(info["code"], 400)
    return JSONResponse({
        "code": info["code"],
        "message": message or info["message"],
        "data": data,
        "trace_id": str(uuid.uuid4())[:8],
    }, status_code=status)


def error(code_key: str, message: str = None, data: Any = None,
          http_status: int = None) -> dict:
    """错误响应"""
    info = ERROR_CODES.get(code_key, {"code": 5001, "message": "未知错误"})
    return {
        "code": info["code"],
        "message": message or info["message"],
        "data": data,
        "trace_id": str(uuid.uuid4())[:8],
    }


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    """分页响应"""
    return {
        "code": 0,
        "message": "成功",
        "data": {
            "items": items,
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            }
        },
        "trace_id": str(uuid.uuid4())[:8],
    }
