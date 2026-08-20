# scripts/fortune_proxy.py
# =====================================================================
# C 端命理风水 H5 的「中间小后端」（安全代理）
# ---------------------------------------------------------------------
# 架构：
#   C 端 H5  ──(同源, 无敏感 token)──▶  本代理  ──(Bearer, 服务端env)──▶  岐黄平台 fortune Agent
#
# 为什么需要它：
#   平台端点要 require_agent_in_plan("fortune") 的 JWT。若 H5 直连平台，
#   token 就得放浏览器，F12 即可扒到，并顺手调 billing/kg/audit 等全部后台。
#   本代理把 token 锁在服务端环境变量，浏览器只跟代理说话，代理带 token 去平台。
#
# 两种运行模式（自动判定）：
#   1) REMOTE（默认，有 FORTUNE_BEARER 时）：反向代理到 PLATFORM_BASE，注入 Bearer。
#      适合部署：本代理 + H5 放一个公网/内网域名，代理持有令牌，安全。
#   2) LOCAL（无 FORTUNE_BEARER 时）：加载真实 fortune router（重依赖 stub 化、免 token），
#      同源托管 H5。适合本地自测，不连平台。
#
# 环境变量：
#   FORTUNE_BEARER  平台 JWT（带 fortune 套餐的调用方 token）。有值=REMOTE 模式。
#   PLATFORM_BASE   平台地址，默认 https://yshealth.com.cn
#   FORTUNE_LOCAL   任意值 → 强制 LOCAL 模式（即便有 BEARER）
#   PORT            监听端口，默认 8000
#
# 用法：
#   本地自测：  python scripts/fortune_proxy.py
#   部署线上：  FORTUNE_BEARER=xxxx PORT=8000 python scripts/fortune_proxy.py
#   浏览器开：  http://127.0.0.1:8000/   （H5 的 Base URL / Token 留空即可，走同域）
# =====================================================================
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

PLATFORM_BASE = os.getenv("PLATFORM_BASE", "https://yshealth.com.cn").rstrip("/")
BEARER = os.getenv("FORTUNE_BEARER", "")
FORCE_LOCAL = bool(os.getenv("FORTUNE_LOCAL"))
MODE = "local" if (FORCE_LOCAL or not BEARER) else "remote"

app = FastAPI(title="fortune-c-end-proxy", version="1.0")
_BAZI = os.path.join(ROOT, "fortune-h5", "bazi.html")
_FENG = os.path.join(ROOT, "fortune-h5", "fengshui.html")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_BAZI, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/fengshui", response_class=HTMLResponse)
async def fengshui():
    with open(_FENG, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
async def healthz():
    return {"mode": MODE, "platform": PLATFORM_BASE if MODE == "remote" else "local-engine"}


# ---------------------------------------------------------------------
# REMOTE 模式：反向代理到平台，注入 Bearer
# ---------------------------------------------------------------------
if MODE == "remote":
    import httpx
    _client = httpx.AsyncClient(timeout=60.0)

    @app.api_route(
        "/api/v1/agent/fortune/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    async def proxy_to_platform(path: str, request: Request):
        target = f"{PLATFORM_BASE}/api/v1/agent/fortune/{path}"
        body = await request.body()
        headers = {
            "Authorization": f"Bearer {BEARER}",
            "Content-Type": request.headers.get("content-type", "application/json"),
        }
        resp = await _client.request(request.method, target, content=body, headers=headers)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"content-type": resp.headers.get("content-type", "application/json")},
        )


# ---------------------------------------------------------------------
# LOCAL 模式：加载真实 fortune router（重依赖 stub 化、免 token）
# ---------------------------------------------------------------------
else:
    import importlib.abc
    import importlib.util
    import types

    class _NullLoader(importlib.abc.Loader):
        def create_module(self, spec): return None
        def exec_module(self, module): pass

    class _DevFinder(importlib.abc.MetaPathFinder):
        def __init__(self, roots): self.roots = roots
        def find_spec(self, name, path, target=None):
            for r in self.roots:
                if name == r or name.startswith(r + "."):
                    return importlib.util.spec_from_loader(name, _NullLoader())
            return None

    def _mod(name, **attrs):
        m = types.ModuleType(name); m.__dict__.update(attrs); return m

    from fastapi import Request as _Req  # noqa

    async def _pass_user(request: _Req):
        request.state.user_id = "local-dev"; request.state.tenant_id = "local-dev-tenant"
        return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}

    def _success(data=None, **kw): return {"code": 0, "data": data, "msg": "ok", **kw}
    def _error(code_key=None, message=None, **kw): return {"code": 1, "msg": message, "error_code": code_key, **kw}
    async def _allow_agent(request: _Req): return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}
    def _get_db(): return None

    gw_deps = _mod("qihuang_platform.gateway.deps", get_current_user=_pass_user,
                   get_current_admin=_pass_user, get_api_key=_pass_user)
    gw_resp = _mod("qihuang_platform.gateway.response", success=_success, error=_error)
    agent_deps = _mod("qihuang_platform.agent.deps", require_agent_in_plan=lambda key: _allow_agent)
    db_cfg = _mod("qihuang_platform.db.config", get_db=_get_db, SessionLocal=lambda: None)
    _sa_orm = _mod("sqlalchemy.orm", Session=object)
    _sa = _mod("sqlalchemy", orm=_sa_orm)

    for _m in (gw_deps, gw_resp, agent_deps, db_cfg, _sa_orm, _sa):
        sys.modules.setdefault(_m.__name__, _m)

    for _pkg in ("qihuang_platform.gateway", "qihuang_platform.db", "qihuang_platform.rbac",
                 "qihuang_platform.billing", "qihuang_platform.control", "qihuang_platform.middleware"):
        _m = _mod(_pkg); _m.__path__ = []; sys.modules.setdefault(_pkg, _m)

    _AGENT_DIR = os.path.join(ROOT, "qihuang_platform", "agent")
    _agent_pkg = _mod("qihuang_platform.agent"); _agent_pkg.__path__ = [_AGENT_DIR]
    sys.modules.setdefault("qihuang_platform.agent", _agent_pkg)

    sys.meta_path.insert(0, _DevFinder([
        "qihuang_platform.gateway", "qihuang_platform.db", "qihuang_platform.rbac",
        "qihuang_platform.billing", "qihuang_platform.control", "qihuang_platform.middleware",
    ]))

    from qihuang_platform.agent.fortune.router import router
    app.include_router(router, prefix="/api/v1/agent", tags=["fortune"])


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = ap.parse_args()
    mode_tip = (
        f"REMOTE → 平台 {PLATFORM_BASE}（Bearer 已注入）"
        if MODE == "remote" else "LOCAL → 真实 fortune 引擎（免 token，自测）"
    )
    print(f"[fortune-proxy] 模式：{mode_tip}")
    print(f"[fortune-proxy] H5  → http://127.0.0.1:{args.port}/  （H5 的 Base URL/Token 留空即可）")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
