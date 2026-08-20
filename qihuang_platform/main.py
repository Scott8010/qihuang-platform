"""
岐黄智脑商业化平台 - FastAPI 主应用（独立端口 8602）
与现有 api/main.py（8601）并行运行，不碰现有代码。

Phase 0: 骨架搭建 + 健康检查 + Mock路由预留  [DONE]
Phase 1: API网关（JWT+APIKey+限流+计量+统一响应）[NOW]
Phase 1: RBAC + 管理端MVP [NEXT]
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


class NoCacheStaticFiles(StaticFiles):
    """静态文件挂载，但强制不缓存（入口 HTML 文件名固定，避免浏览器缓存旧版管理台）。"""

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp


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
        from qihuang_platform.billing.plans import seed_plans
        from qihuang_platform.db.config import SessionLocal
        # 1) RBAC 预置（幂等，失败不阻断后续步骤）
        db = SessionLocal()
        try:
            seed_preset_data(db)
            db.commit()
            print("[Platform] RBAC预置数据已初始化 (9角色+18权限)")
        except Exception as e:
            db.rollback()
            print(f"[Platform] RBAC预置跳过（可能已存在）: {e}")
        finally:
            db.close()

        # 2) 套餐预置（含 Agent 专家团组合合并）
        db = SessionLocal()
        try:
            seed_plans(db)
            print("[Platform] 套餐预置数据已初始化 (4档套餐)")
        except Exception as e:
            db.rollback()
            print(f"[Platform] 套餐预置跳过: {e}")
        finally:
            db.close()

        # 3) Agent 中台注册表落库同步（部署期样板 → DB，运营态热插拔）
        try:
            from qihuang_platform.agent.registry import sync_from_db
            n = sync_from_db()
            print(f"[Platform] Agent 中台注册表已同步 {n} 个能力")
        except Exception as e:
            print(f"[Platform] Agent 注册表同步失败: {e}")

        # 4) store-coach 平台级培训模板种数据（幂等：话术/产品/项目样例）
        db = SessionLocal()
        try:
            from qihuang_platform.agent.store_coach.seed import seed_platform_templates
            n = seed_platform_templates(db)
            print(f"[Platform] store-coach 培训模板已种入 {n} 个（幂等，已存在则跳过）")
        except Exception as e:
            db.rollback()
            print(f"[Platform] store-coach 培训模板种入跳过: {e}")
        finally:
            db.close()

        # 5) 默认租户订阅企业版（含 compliance），保证控制端/默认租户可调用 Agent 能力
        db = SessionLocal()
        try:
            from qihuang_platform.db.models import Subscription, Plan as _Plan
            ent = db.query(_Plan).filter_by(plan_name="enterprise").first()
            if ent and not db.query(Subscription).filter_by(
                tenant_id="tenant_default", status="active"
            ).first():
                db.add(Subscription(
                    tenant_id="tenant_default", plan_id=ent.id, status="active"
                ))
                db.commit()
                print("[Platform] 已为默认租户(tenant_default)订阅企业版套餐（含 Agent 能力）")
        except Exception as e:
            db.rollback()
            print(f"[Platform] 默认租户订阅跳过: {e}")
        finally:
            db.close()

        # API Key 冷启动加载：将 DB 中 active 的 key 恢复到内存鉴权表。
        # 否则服务重启后 _api_keys_db 被清空、而 list 接口仍从 DB 读取 →
        # 界面上看到的所有 key 实际鉴权全失败（空架子风险）。
        try:
            from qihuang_platform.gateway.auth import register_api_key
            from qihuang_platform.db.models import ApiKey as DBApiKey
            kdb = SessionLocal()
            try:
                active_keys = kdb.query(DBApiKey).filter_by(status="active").all()
                for k in active_keys:
                    register_api_key(
                        app_key=k.app_key,
                        app_secret=k.app_secret,
                        tenant_id=k.tenant_id,
                        plan="standard",
                    )
                print(f"[Platform] 已冷加载 {len(active_keys)} 个 active API Key 到内存鉴权表")
            finally:
                kdb.close()
        except Exception as e:
            print(f"[Platform] API Key 冷启动加载失败: {e}")

    except Exception as e:
        print(f"[Platform] 数据库初始化失败（可能已初始化）: {e}")

    # 活态化周期聚合调度（默认 T+1=24h 自动回写 8601 /kg/api；可用
    # QH_LIVING_AGG_INTERVAL_SECONDS 覆盖，开发期可设小值便于观察）
    try:
        from qihuang_platform.living.scheduler import start_living_scheduler
        _interval = int(os.getenv("QH_LIVING_AGG_INTERVAL_SECONDS", str(24 * 3600)))
        start_living_scheduler(_interval)
    except Exception as e:
        print(f"[Platform] 活态化调度启动失败: {e}")

    print(f"[Platform] Phase 0 — 骨架就绪，等待 Phase 1 挂载路由")
    yield
    print("[Platform] 平台已关闭")


# ─── 应用实例 ───
app = FastAPI(
    title="岐黄智脑商业化平台",
    description=(
        "一中台·三场景·一管理端的多租户商业化平台。\n"
        "Phase 0: 环境与契约就绪（骨架搭建）\n"
        "Phase 1: API网关 + RBAC + 管理端MVP + 中台封装"
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

# ─── 运营控制台 /admin 不缓存 ───
# 入口 index.html 文件名固定（不带 hash），浏览器一旦缓存旧版就看不到新构建
# （如 Agent 中台「套餐专家团组合」构件 B）。对 /admin 与 /admin-static 全路径禁用缓存。
@app.middleware("http")
async def no_cache_admin_console(request: Request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/admin" or p.startswith("/admin/") or p.startswith("/admin-static/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


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
            "gateway": "已挂载 (JWT+APIKey+限流+计量+统一响应+LLM降级链+监控)",
            "rbac": "已挂载 (24表+9角色+18权限+RBAC管理API)",
            "capability": "已挂载 (core 18+health 7+acupoint 6+med 7+edu 7=45端点)",
            "acupoint_3d": "已挂载 (6端点: model/guide/meridians/search/detail/list)",
            "billing": "已挂载 (plans+billing+quota: 套餐/账单/配额)",
            "control": "已挂载 (6大功能域: 套餐/账单/知识审核/监控/审计/敏感词)",
            "llm_fallback": "已挂载 (DeepSeek→GLM-4→规则引擎降级链)",
            "monitor": "已挂载 (QPS/延迟/错误率/Token/告警)",
            "capability": "已��载 (18+6=24端点: 辨证/方剂/安全/图谱/对话/文献/查询+3D穴位)",
            "acupoint_3d": "已挂载 (6端点: model/guide/meridians/search/detail/list)",
            "billing": "已挂载 (plans: features_json+module_3d门控)",
            "control": "已挂载 (React统一控制台: 工作台/租户/权限/密钥/计费/内容/监控, 入口合一数据同源)",
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
# 活态化反馈闭环路由挂载（P2：反馈采集 + 聚合回写 8601 /kg/api）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.living import router as living_router
    app.include_router(living_router)  # /api/v1/living/*
    print("[Platform] 活态化反馈闭环路由已挂载 → /api/v1/living")
except ImportError as e:
    print(f"[Platform] 活态化模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# Agent 中台路由挂载（第一个能力：内容合规审核 compliance）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.agent import agent_router
    app.include_router(agent_router)  # /api/v1/agent/compliance/*
    print("[Platform] Agent 中台路由已挂载 → /api/v1/agent")
except ImportError as e:
    print(f"[Platform] Agent 中台模块未就绪: {e}")


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
# Phase 3: 管理端全功能路由挂载（6大功能域）
# ═══════════════════════════════════════════════════════════════
try:
    from qihuang_platform.control import control_router
    if control_router:
        app.include_router(control_router)
        print("[Platform] 管理端全功能路由已挂载 → /admin/v1/billing, /admin/v1/kg, /admin/v1/monitor, /admin/v1/audit-logs, /admin/v1/content")

    # 客户管理路由
    try:
        from qihuang_platform.control.customer_mgr import router as customer_router
        app.include_router(customer_router)
        print("[Platform] 客户管理路由已挂载 → /admin/v1/customers")
    except ImportError as e:
        print(f"[Platform] 客户管理模块未就绪: {e}")

    # 报表管理路由
    try:
        from qihuang_platform.control.report_mgr import router as report_router
        app.include_router(report_router)
        print("[Platform] 报表管理路由已挂载 → /admin/v1/reports")
    except ImportError as e:
        print(f"[Platform] 报表管理模块未就绪: {e}")

    # 数据同步路由
    try:
        from qihuang_platform.control.sync_mgr import router as sync_router
        app.include_router(sync_router)
        print("[Platform] 数据同步路由已挂载 → /admin/v1/sync")
    except ImportError as e:
        print(f"[Platform] 数据同步模块未就绪: {e}")

    # 告警管理路由
    try:
        from qihuang_platform.control.alert_mgr import router as alert_router
        app.include_router(alert_router)
        print("[Platform] 告警管理路由已挂载 → /admin/v1/alerts, /admin/v1/cache")
    except ImportError as e:
        print(f"[Platform] 告警管理模块未就绪: {e}")

    # 成本中心路由
    try:
        from qihuang_platform.control.cost_mgr import router as cost_router2
        app.include_router(cost_router2)
        print("[Platform] 成本中心路由已挂载 → /admin/v1/cost")
    except ImportError as e:
        print(f"[Platform] 成本中心模块未就绪: {e}")

    # 机构管理路由
    try:
        from qihuang_platform.control.org_mgr import router as org_router2
        app.include_router(org_router2)
        print("[Platform] 机构管理路由已挂载 → /admin/v1/tenants/{id}/orgs, /admin/v1/orgs")
    except ImportError as e:
        print(f"[Platform] 机构管理模块未就绪: {e}")

    # 角色权限管理路由
    try:
        from qihuang_platform.control.roles_mgr import router as roles_router
        from qihuang_platform.control.roles_mgr import perm_router
        app.include_router(roles_router)
        app.include_router(perm_router)
        print("[Platform] 角色权限管理路由已挂载 → /admin/v1/roles-admin, /admin/v1/permissions")
    except ImportError as e:
        print(f"[Platform] 角色权限管理模块未就绪: {e}")

    # 多租户能力中心（二期）— 模板中心路由
    try:
        from qihuang_platform.template_center import template_center_router
        app.include_router(template_center_router)
        print("[Platform] 多租户能力中心路由已挂载 → /admin/v1/template-center")
    except ImportError as e:
        print(f"[Platform] 多租户能力中心模块未就绪: {e}")

    # 多租户能力中心 — 开放接口（HMAC 友好，供颐掌柜 HB 等外部系统接入）
    try:
        from qihuang_platform.template_center.open_router import template_center_open_router
        app.include_router(template_center_open_router)
        print("[Platform] 能力中心开放接口已挂载 → /api/v1/template-center (HMAC/JWT)")
    except ImportError as e:
        print(f"[Platform] 能力中心开放接口未就绪: {e}")
except ImportError as e:
    print(f"[Platform] 管理端全功能模块未就绪: {e}")


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
        admin_auth_router,
        dev_router,
    )
    app.include_router(auth_router)          # /api/v1/auth/*
    app.include_router(resource_router)      # /api/v1/protected/*
    app.include_router(ratelimit_router)     # /api/v1/test/*
    app.include_router(open_router)          # /open/v1/*
    app.include_router(api_key_router)       # /admin/v1/api-keys/*
    app.include_router(admin_auth_router)    # /admin/v1/login (生产正式登录)
    print("[Platform] 网关路由已挂载 → /api/v1/auth, /api/v1/protected, /open/v1, /admin/v1")
    # 开发辅助端点：仅当 ENABLE_DEV_ROUTES=1 时挂载（生产默认关闭，堵住 /dev/admin-login 后门）
    if os.getenv("ENABLE_DEV_ROUTES") == "1":
        app.include_router(dev_router)       # /dev/* (仅开发环境)
        print("[Platform] 开发辅助路由已挂载 → /dev (ENABLE_DEV_ROUTES=1)")
    else:
        print("[Platform] 开发辅助路由未挂载（生产模式，ENABLE_DEV_ROUTES 未开启）")
except ImportError as e:
    print(f"[Platform] 网关模块未就绪: {e}")

# API Key 管理路由扩展(注册在网关之后，使DB版GET /覆盖网关内存版)
try:
    from qihuang_platform.control.apikey_mgr import router as apikey_mgr_router
    app.include_router(apikey_mgr_router)
    print("[Platform] API Key管理路由已挂载 → /admin/v1/api-keys/ (DB版)")
except ImportError as e:
    print(f"[Platform] API Key管理模块未就绪: {e}")


# ═══════════════════════════════════════════════════════════════
# 运营控制台静态页面托管（React SPA 统一入口）
# 入口合一，数据同源 → 通过角色/权限区分各场景管理
# ═══════════════════════════════════════════════════════════════
ADMIN_DIR = Path(__file__).resolve().parent.parent / "frontend-admin-react" / "dist"
LEGACY_ADMIN_DIR = Path(__file__).resolve().parent / "frontend-admin"

if ADMIN_DIR.exists():
    app.mount("/admin", NoCacheStaticFiles(directory=str(ADMIN_DIR), html=True), name="admin-console")
    print(f"[Platform] 运营控制台(React)已挂载 → /admin/ (目录: {ADMIN_DIR})")

if LEGACY_ADMIN_DIR.exists():
    # 旧版 HTML 入口（控制端反馈审核台等）始终并行挂载，不依赖 React 是否存在
    app.mount("/admin-static", NoCacheStaticFiles(directory=str(LEGACY_ADMIN_DIR)), name="admin-static")
    print(f"[Platform] 管理端(旧版HTML)已挂载 → /admin-static/ (目录: {LEGACY_ADMIN_DIR})")


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_redirect():
    """根路径重定向到新版 React 运营控制台（主入口）"""
    if ADMIN_DIR.exists():
        return RedirectResponse(url="/admin/")
    return RedirectResponse(url="/admin-static/admin.html")


@app.api_route("/ops", methods=["GET", "HEAD"], include_in_schema=False)
async def ops_page():
    """运维端 → 统一控制台"""
    if ADMIN_DIR.exists():
        return RedirectResponse(url="/admin/")
    return JSONResponse({"detail": "请访问 /admin"}, status_code=404)


@app.api_route("/business", methods=["GET", "HEAD"], include_in_schema=False)
async def business_page():
    """运营端 → 统一控制台"""
    if ADMIN_DIR.exists():
        return RedirectResponse(url="/admin/")
    return JSONResponse({"detail": "请访问 /admin"}, status_code=404)


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


