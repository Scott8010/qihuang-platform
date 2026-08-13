# scripts/local_fortune_dev.py
# 本地开发验证用脚手架：零 pip 依赖、零数据库，起「真实 fortune router」做端到端 curl 验证。
# 原理：用 import hook 把平台重依赖子树（gateway/db/rbac/...）全部 stub 成空模块，
#       仅对 fortune 端点真正需要的几个叶子（gateway.deps / gateway.response /
#       agent.deps / db.config / sqlalchemy）注入放行 stub，从而 import 真实 router.py 并起服务。
# 注意：本脚本仅用于本地开发验证，不进生产路径；生产仍走真实依赖 + 真 DB。
import importlib.abc
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 项目根 = qihuang_platform/
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------- 1) 通用空模块 loader（用于拦截平台重依赖子树） ----------
class _NullLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        pass


class _DevFinder(importlib.abc.MetaPathFinder):
    """拦截平台重依赖子树：除 special 外一律返回空模块，避免拉真依赖/连库。"""

    def __init__(self, roots):
        self.roots = roots

    def find_spec(self, name, path, target=None):
        for r in self.roots:
            if name == r or name.startswith(r + "."):
                return importlib.util.spec_from_loader(name, _NullLoader())
        return None


# ---------- 2) 构造真正需要的 stub 叶子模块 ----------
def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    return m


from fastapi import Request  # noqa: E402


async def _pass_user(request: Request):
    request.state.user_id = "local-dev"
    request.state.tenant_id = "local-dev-tenant"
    return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}


def _success(data=None, **kw):
    return {"code": 0, "data": data, "msg": "ok", **kw}


def _error(code_key=None, message=None, **kw):
    return {"code": 1, "msg": message, "error_code": code_key, **kw}


async def _allow_agent(request: Request):
    return {"user_id": "local-dev", "tenant_id": "local-dev-tenant"}


def _get_db():
    return None


gw_deps = _mod(
    "qihuang_platform.gateway.deps",
    get_current_user=_pass_user,
    get_current_admin=_pass_user,
    get_api_key=_pass_user,
)
gw_resp = _mod(
    "qihuang_platform.gateway.response",
    success=_success,
    error=_error,
)
agent_deps = _mod(
    "qihuang_platform.agent.deps",
    require_agent_in_plan=lambda key: _allow_agent,
)
db_cfg = _mod(
    "qihuang_platform.db.config",
    get_db=_get_db,
    SessionLocal=lambda: None,
)

# sqlalchemy stub：仅满足 router 顶层 `from sqlalchemy.orm import Session` 类型导入
_sa_orm = _mod("sqlalchemy.orm", Session=object)
_sa = _mod("sqlalchemy", orm=_sa_orm)


# ---------- 3) 预先注入 sys.modules（命中优先，不读真实文件） ----------
for _m in (gw_deps, gw_resp, agent_deps, db_cfg, _sa_orm, _sa):
    sys.modules.setdefault(_m.__name__, _m)

# 父包置空包（带 __path__，否则子模块 import 报 "not a package"），拦截其下重依赖子模块
for _pkg in (
    "qihuang_platform.gateway",
    "qihuang_platform.db",
    "qihuang_platform.rbac",
    "qihuang_platform.billing",
    "qihuang_platform.control",
    "qihuang_platform.middleware",
):
    _m = _mod(_pkg)
    _m.__path__ = []  # 标记为空包，子模块 import 走下方 _DevFinder 返回空模块
    sys.modules.setdefault(_pkg, _m)

# qihuang_platform.agent 包：stub 为「指向真实目录的包」但【不执行真实 __init__】，
# 这样既不会触发真实 __init__ 对 compliance.router 的重依赖 import，
# 又能让 fortune.router 子模块走真实文件被加载。
_AGENT_DIR = os.path.join(ROOT, "qihuang_platform", "agent")
_agent_pkg = _mod("qihuang_platform.agent")
_agent_pkg.__path__ = [_AGENT_DIR]
sys.modules.setdefault("qihuang_platform.agent", _agent_pkg)

# 注册拦截 hook（处理 compliance.router 等可能 import 的未知子模块）
sys.meta_path.insert(
    0,
    _DevFinder(
        [
            "qihuang_platform.gateway",
            "qihuang_platform.db",
            "qihuang_platform.rbac",
            "qihuang_platform.billing",
            "qihuang_platform.control",
            "qihuang_platform.middleware",
        ]
    ),
)


# ---------- 4) 现在 import 真实 router（触发 agent/__init__ → fortune.router 等） ----------
from qihuang_platform.agent.fortune.router import router  # noqa: E402

from fastapi import FastAPI  # noqa: E402

app = FastAPI(title="fortune-local-dev", version="local")
app.include_router(router, prefix="/api/v1/agent", tags=["fortune"])


if __name__ == "__main__":
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(
        f"[local-dev] 真实 fortune router 已挂载 → "
        f"http://127.0.0.1:{args.port}/api/v1/agent/fortune/{{archive,cast,daily,report,dashboard}}"
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
