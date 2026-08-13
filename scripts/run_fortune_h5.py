# scripts/run_fortune_h5.py
# 本地验证启动器：加载真实 fortune router（鉴权重依赖 stub 化、免 token），
# 并把 fortune-h5.html 同源托管在 http://127.0.0.1:8000/ ，
# 这样浏览器打开后 fetch 同域 /api/v1/agent/fortune/* 不触发 CORS，可直接验证。
#
# 用法：cd 平台根目录(qihuang_platform/) && python scripts/run_fortune_h5.py
#      浏览器开 http://127.0.0.1:8000/ 即可。
# 生产指向：H5 里把 Base URL 填 https://yshealth.com.cn + 填 Token 即可走线上（需 CORS/代理，见说明）。
import importlib.abc
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------- 1) 通用空模块 loader（拦截平台重依赖子树） ----------
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

from fastapi import Request

async def _pass_user(request: Request):
    request.state.user_id = "local-dev"; request.state.tenant_id = "local-dev-tenant"
    return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}

def _success(data=None, **kw): return {"code": 0, "data": data, "msg": "ok", **kw}
def _error(code_key=None, message=None, **kw): return {"code": 1, "msg": message, "error_code": code_key, **kw}
async def _allow_agent(request: Request): return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}
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

# ---------- 2) import 真实 router + 挂载 H5 ----------
from qihuang_platform.agent.fortune.router import router
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="fortune-h5-local", version="local")
app.include_router(router, prefix="/api/v1/agent", tags=["fortune"])

_H5 = os.path.join(HERE, "fortune-h5.html")
@app.get("/", response_class=HTMLResponse)
async def index():
    with open(_H5, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import argparse, uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"[fortune-h5] H5  → http://127.0.0.1:{args.port}/")
    print(f"[fortune-h5] API → http://127.0.0.1:{args.port}/api/v1/agent/fortune/{{archive,cast,daily,report,geo}}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
