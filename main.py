"""
岐黄智脑商业化平台 - FastAPI 主应用（独立端口 8602）
与现有 api/main.py（8601）并行运行，不碰现有代码。

Phase 0: 骨架搭建 + 健康检查 + Mock路由预留  [DONE]
Phase 1: API网关（JWT+APIKey+限流+计量+统一响应）[NOW]
Phase 1: RBAC + 控制端MVP [NEXT]
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException
from dotenv import load_dotenv

from qihuang_platform.gateway.middleware import (
    TraceMiddleware,
    TimingMiddleware,
    MeteringMiddleware,
    ExceptionHandlerMiddleware,
    RateLimitHeaderMiddleware,
)

# ─── 路径配置 ───
BASE_DIR = Path(__file__).resolve().parent.parent  # Claw/qihuang-brain/
load_dotenv(BASE_DIR / ".env")

PLATFORM_PORT = int(os.getenv("PLATFORM_PORT", "8602"))
PLATFORM_HOST = os.getenv("PLATFORM_HOST", "0.0.0.0")

# ─── 生命周期 ───
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[Platform] 岐黄智脑商业化平台启动中... (端口 {PLATFORM_PORT})")
    # 数据库初始化
    try:
        from qihuang_platform.db.config import init_db
        from qihuang_platform.db.models import Base
        init_db()
        print("[Platform] 数据库表已初始化")
        # RBAC预置数据
        from qihuang_platform.db.models import seed_preset_data
        from qihuang_platform.db.config import SessionLocal
        db = SessionLocal()
        try:
            seed_preset_data(db)
            db.commit()
            print("[Platform] RBAC预置数据已初始化 (9角色+18权限)")
        finally:
            db.close()
    except Exception as e:
        print(f"[Platform] 数据库初始化失败（可能已初始化）: {e}")

    # API Key 环境变量播种（解决内存 _api_keys_db 重启即丢的问题）
    try:
        from qihuang_platform.gateway.auth import register_api_key
        ak = os.getenv("QH_API_KEY_APP_KEY")
        sk = os.getenv("QH_API_KEY_APP_SECRET")
        tid = os.getenv("QH_API_KEY_TENANT_ID")
        if ak and sk and tid:
            register_api_key(
                app_key=ak,
                app_secret=sk,
                tenant_id=tid,
                plan=os.getenv("QH_API_KEY_PLAN", "standard"),
                extra={"note": "env-seeded", "purpose": "HB-A2"},
            )
            print(f"[Platform] 已从环境变量播种 API Key (tenant={tid})")
        else:
            print("[Platform] 未检测到 QH_API_KEY_* 环境变量，跳过 API Key 播种")
    except Exception as e:
        print(f"[Platform] API Key 播种失败（不影响其他启动）: {e}")

    print(f"[Platform] Phase 0 — 骨架就绪，等待 Phase 1 挂载路由")
    yield
    print("[Platform] 平台已关闭")


# ─── 应用实例 ───
app = FastAPI(
    title="岐黄智脑商业化平台",
    description=(
        "一中台·三场景·一控制端的多租户商业化平台。\n"
        "Phase 0: 环境与契约就绪（骨架搭建）\n"
        "Phase 1: API网关 + RBAC + 控制端MVP + 中台封装"
    ),
    version="0.1.0-alpha",
    docs_url="/platform/docs",
    redoc_url="/platform/redoc",
    openapi_url="/platform/openapi.json",
    lifespan=lifespan,
)

# ─── 全局异常处理：HTTPException 转统一格式 ───
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """将 HTTPException.detail 转为我们统一的 {code, message, data, trace_id} 格式"""
    import uuid
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        # 已经是我们的格式，直接使用
        body = detail
    else:
        body = {
            "code": exc.status_code,
            "message": str(detail) if detail else str(exc.detail),
            "data": None,
            "trace_id": str(uuid.uuid4())[:8],
        }
    return JSONResponse(status_code=exc.status_code, content=body)

# ─── CORS ───
ALLOWED_ORIGINS = os.getenv(
    "QH_CORS_ORIGINS",
    "http://localhost:8688,http://localhost:8080,http://192.168.7.107:8688"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# ─── 网关中间件（洋葱模型，先加后执行） ───
app.add_middleware(ExceptionHandlerMiddleware)   # 最外层：异常捕获
app.add_middleware(TimingMiddleware)             # 计时
app.add_middleware(TraceMiddleware)              # Trace ID
app.add_middleware(MeteringMiddleware)           # 计量埋点
app.add_middleware(RateLimitHeaderMiddleware)    # 限流响应头


# ═══════════════════════════════════════════════════════════════
# Phase 0 基础端点
# ═══════════════════════════════════════════════════════════════

@app.get("/platform/health")
async def platform_health():
    """平台健康检查"""
    return {
        "service": "岐黄智脑商业化平台",
        "version": "0.1.0-alpha",
        "phase": "Phase 0 - 环境与契约就绪",
        "status": "ok",
        "port": PLATFORM_PORT,
        "existing_api": "http://localhost:8601",
    }


@app.get("/platform/status")
async def platform_status():
    """平台状态详情"""
    return {
        "version": "0.1.0-alpha",
        "phase": "Phase 1 - API网关已挂载 + RBAC已挂载",
        "milestones": {
            "M0": "云上跑通现有中台 + HTTPS + 备份就位",
            "M1": "开户→登录→调辨证→有计量全链路（W8）",
            "M2": "真实用户全流程 + 租户维度账单（W14）",
            "M3": "医疗报告通过医师评审 + L2稳定性（W22）",
        },
        "modules": {
            "gateway": "已挂载 (JWT+APIKey+限流+计量+统一响应)",
            "rbac": "已挂载 (24表+9角色+18权限+RBAC管理API)",
            "capability": "已��载 (18+6=24端点: 辨证/方剂/安全/图谱/对话/文献/查询+3D穴位)",
            "acupoint_3d": "已挂载 (6端点: model/guide/meridians/search/detail/list)",
            "billing": "已挂载 (plans: features_json+module_3d门控)",
            "control": "已挂载 (admin.html 5+1标签页: 仪表盘/租户/用户/密钥/3D模块/用量)",
            "db": "待迁移（PostgreSQL 24表）",
        },
    }


# ═══════════════════════════════════════════════════════════════
# Phase 1: 中台能力路由挂载（透传现有 API 核心能力）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.capability import capability_router
    app.include_router(capability_router)  # /api/v1/core/*, /api/v1/health/*
    print("[Platform] 中台能力路由已挂载 → /api/v1/core, /api/v1/health")
except ImportError as e:
    print(f"[Platform] 中台能力模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# Phase 1: RBAC 路由挂载（数据库租户/用户/角色/权限管理）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.rbac.router import rbac_router
    app.include_router(rbac_router)  # /admin/v1/*
    print("[Platform] RBAC 路由已挂载 → /admin/v1/tenants, /admin/v1/users, /admin/v1/roles, /admin/v1/permissions")
except ImportError as e:
    print(f"[Platform] RBAC 模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# Agent 中台路由挂载（内容合规审核 = 第一个能力；横向隔离知识库范式）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.agent import agent_router
    app.include_router(agent_router)  # /api/v1/agent/compliance/*
    print("[Platform] Agent 中台路由已挂载 → /api/v1/agent/compliance (内容合规审核)")
except ImportError as e:
    print(f"[Platform] Agent 中台模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# Phase 0: Mock 路由挂载（契约冻结后，前端并行开发用）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.mock import mock_router
    app.include_router(mock_router, prefix="/mock")
    print("[Platform] Mock 服务已挂载 → /mock/*")
except ImportError:
    print("[Platform] Mock 模块未就绪，跳过硬编码挂载")


# ═══════════════════════════════════════════════════════════════
# Phase 1: API网关路由挂载
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.gateway.router import (
        router as auth_router,
        resource_router,
        rate_limit_test as ratelimit_router,
        open_router,
        api_key_router,
        dev_router,
    )
    app.include_router(auth_router)          # /api/v1/auth/*
    app.include_router(resource_router)      # /api/v1/protected/*
    app.include_router(ratelimit_router)     # /api/v1/test/*
    app.include_router(open_router)          # /open/v1/*
    app.include_router(api_key_router)       # /admin/v1/api-keys/*
    app.include_router(dev_router)           # /dev/* (仅开发环境)
    print("[Platform] 网关路由已挂载 → /api/v1/auth, /api/v1/protected, /open/v1, /admin/v1, /dev")
except ImportError as e:
    print(f"[Platform] 网关模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# 控制端静态页面托管（解决 file:// 协议 Failed to fetch 问题）
# ═══════════════════════════════════════════════════════════════
ADMIN_DIR = Path(__file__).resolve().parent / "frontend-admin"
if ADMIN_DIR.exists():
    app.mount("/admin-static", StaticFiles(directory=str(ADMIN_DIR)), name="admin-static")
    print(f"[Platform] 控制端静态文件已挂载 → /admin-static/ (目录: {ADMIN_DIR})")

@app.get("/")
async def root_redirect():
    """根路径重定向到控制端"""
    return RedirectResponse(url="/admin")

@app.get("/admin")
async def admin_page():
    """返回控制端 HTML"""
    html_path = ADMIN_DIR / "admin.html"
    if html_path.exists():
        return RedirectResponse(url="/admin-static/admin.html")
    return JSONResponse({"detail": "控制端页面未找到"}, status_code=404)


# ═══════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "qihuang_platform.main:app",
        host=PLATFORM_HOST,
        port=PLATFORM_PORT,
        reload=False,
        log_level="info",
    )
