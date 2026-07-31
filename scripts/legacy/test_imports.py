import sys
sys.path.insert(0, ".")

modules = [
    ("gateway.router", "from qihuang_platform.gateway.router import router as auth_router, resource_router, rate_limit_test as ratelimit_router, open_router, api_key_router, dev_router"),
    ("rbac.router", "from qihuang_platform.rbac.router import rbac_router"),
    ("capability", "from qihuang_platform.capability import capability_router"),
    ("control", "from qihuang_platform.control import control_router"),
]

for name, stmt in modules:
    try:
        exec(stmt)
        print(f"[OK] {name}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        import traceback
        traceback.print_exc()
        print()
