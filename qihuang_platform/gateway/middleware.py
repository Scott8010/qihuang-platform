"""
API Gateway - Starlette 中间件
Trace ID 注入 / 请求计时 / 错误处理 / 响应头注入
"""
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from qihuang_platform.gateway.metering import metering_store, CallLog
from qihuang_platform.gateway.ratelimit import rate_limiter


def _should_persist_call(path: str, status_code: int) -> bool:
    """判定本次请求是否真落库 call_log 表（防双写 + 只记成功）。

    - agent 业务路径由 agent 自身 record_call 落库，中间件不重复落库
    - 失败响应(>=400)不计入配额（与「成功才计」一致）
    """
    return (status_code < 400) and (not path.startswith("/api/v1/agent/"))


class TraceMiddleware(BaseHTTPMiddleware):
    """注入 trace_id + 记录响应头"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4())[:12])
        request.state.trace_id = trace_id

        response: Response = await call_next(request)

        # 注入 trace_id 到响应头
        response.headers["X-Trace-Id"] = trace_id
        # 注意：CORS 响应头统一由 CORSMiddleware 按白名单管控（#7 修复），
        # 此处不再强制写 "*"，否则会覆盖白名单导致任意源可跨域访问。
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """请求计时中间件"""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response: Response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000, 2)

        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        request.state.latency_ms = elapsed_ms
        return response


class MeteringMiddleware(BaseHTTPMiddleware):
    """计量埋点中间件（异步写入 call_log）"""

    EXCLUDED_PATHS = {"/platform/health", "/platform/status", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 排除健康检查等
        if request.url.path in self.EXCLUDED_PATHS:
            return response

        # 构造 call_log
        call = CallLog(
            id=str(uuid.uuid4()),
            trace_id=getattr(request.state, "trace_id", ""),
            endpoint=request.url.path,
            method=request.method,
            tenant_id=getattr(request.state, "tenant_id", None),
            user_id=getattr(request.state, "user_id", None),
            app_key=getattr(request.state, "app_key", None),
            org_id=getattr(request.state, "org_id", None),
            status_code=response.status_code,
            latency_ms=getattr(request.state, "latency_ms", 0),
            tokens_used=0,  # 实际由业务层写入(agent 端点由业务 record_call 带真实 token)
            cost_cents=0,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 防双写 + 只记成功调用：
        # - agent 业务路径由 agent 自身 record_call 落库，中间件置 persist=False
        # - 失败响应(>=400)不计入配额（与「成功才计」一致）
        path = request.url.path
        should_persist = _should_persist_call(path, response.status_code)
        await metering_store.log(call, persist=should_persist)
        return response


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """全局异常捕获，统一返回错误响应"""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            trace_id = getattr(request.state, "trace_id", str(uuid.uuid4())[:12])
            return JSONResponse(
                status_code=500,
                content={
                    "code": 5001,
                    "message": f"服务内部错误: {str(exc)}",
                    "data": None,
                    "trace_id": trace_id,
                }
            )


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """注入限流响应头 X-RateLimit-*"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 如果有 rate limit 信息就注入
        identity = getattr(request.state, "tenant_id", None) or "anonymous"
        endpoint = request.url.path

        # 检查这个请求的限流状态
        _, info = rate_limiter.check(
            identity=identity,
            endpoint=endpoint,
        )

        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(info["reset"])

        return response
