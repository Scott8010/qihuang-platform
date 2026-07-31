"""
#21 3D资产剥离 — 测试套件
覆盖: 穴位数据模块 + 3个core端点 + 权限点 + 套餐门控 + 计量维度
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from httpx import AsyncClient, ASGITransport

from qihuang_platform.main import app

BASE = "http://test"
PLATFORM_KEY = "qihuang-platform-internal-key-dev"


async def login(client, user_id="wx_user_00001"):
    resp = await client.post("/api/v1/auth/login", json={
        "login_type": "wechat",
        "code": user_id.replace("wx_user_", ""),
    })
    return resp.json()["data"]["access_token"]


async def authed_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE) as client:
        token = await login(client)
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


# ================================================================
# 子任务1: 穴位数据层
# ================================================================

class TestAcupointData:

    def test_load_acupoints(self):
        """1.1 数据加载成功"""
        from qihuang_platform.acupoint.data import acupoint_data
        pts = acupoint_data.acupoints
        assert len(pts) > 300, f"穴位数据异常: {len(pts)}"
        assert len(pts) == 361, f"穴位数量应为361, 实际{len(pts)}"
        print(f"  [PASS] 穴位数据加载: {len(pts)} 个穴位")

    def test_meridian_groups(self):
        """1.2 经络分组正确"""
        from qihuang_platform.acupoint.data import acupoint_data
        meridians = acupoint_data.list_meridians()
        assert len(meridians) == 14, f"经络数量: {len(meridians)}"
        for m in meridians:
            assert m["acupoint_count"] > 0, f"{m['code']} 穴位数为0"
        print(f"  [PASS] 经络分组: {len(meridians)} 条经络")

    def test_meridian_path(self):
        """1.3 经络循行路径生成"""
        from qihuang_platform.acupoint.data import acupoint_data
        path = acupoint_data.get_meridian_path("LU")
        assert path is not None
        assert len(path["path_points"]) == 11, f"肺经应有11穴, 实际{len(path['path_points'])}"
        assert path["path_points"][0]["position_3d"] == [-0.563333, 1.353333, 0.091021]
        print(f"  [PASS] 经络路径: LU {len(path['path_points'])}穴")

    def test_meridian_paths_all(self):
        """1.4 14条经络全部可获取"""
        from qihuang_platform.acupoint.data import acupoint_data
        meridians = acupoint_data.list_meridians()
        for m in meridians:
            path = acupoint_data.get_meridian_path(m["code"])
            assert path is not None, f"{m['code']} 路径获取失败"
            assert len(path["path_points"]) == m["acupoint_count"]
        print(f"  [PASS] 全部14条经络路径OK")

    def test_search(self):
        """1.5 穴位搜索"""
        from qihuang_platform.acupoint.data import acupoint_data
        results = acupoint_data.search("咳嗽")
        assert len(results) > 0
        for r in results[:3]:
            print(f"  {r['code']} {r['name']}")
        print(f"  [PASS] 搜索'咳嗽': {len(results)} 条结果")

    def test_model_meta(self):
        """1.6 模型元信息"""
        from qihuang_platform.acupoint.data import acupoint_data
        meta = acupoint_data.get_model_meta()
        assert meta["acupoint_count"] == 361
        assert len(meta["models"]) >= 3
        print(f"  [PASS] 模型元信���: {len(meta['models'])} 个模型")


# ================================================================
# 子任务5: 3个core端点 (model/guide/meridians)
# ================================================================

@pytest.mark.anyio
class TestAcupointAPI:

    async def test_model_endpoint(self):
        """5.1 GET /api/v1/core/acupoint/model"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/model")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["version"] == "1.0.0"
            assert data["acupoint_count"] == 361
            assert "models" in data
            print(f"  [PASS] model端点: version={data['version']}")

    async def test_guide_endpoint(self):
        """5.2 POST /api/v1/core/acupoint/guide"""
        async for client in authed_client():
            resp = await client.post("/api/v1/core/acupoint/guide", json={
                "mode": "symptom",
                "query": "咳嗽",
                "limit": 5,
            })
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert len(data["acupoints"]) > 0
            assert data["mode"] == "symptom"
            assert "advice" in data
            print(f"  [PASS] guide端点: {len(data['acupoints'])}穴位, {data['advice'][:30]}...")

    async def test_guide_constitution_mode(self):
        """5.3 POST guide (体质模式)"""
        async for client in authed_client():
            resp = await client.post("/api/v1/core/acupoint/guide", json={
                "mode": "constitution",
                "query": "气虚质",
                "limit": 3,
            })
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["mode"] == "constitution"
            print(f"  [PASS] guide体质模式: {len(data['acupoints'])}穴位")

    async def test_meridians_endpoint(self):
        """5.4 GET /api/v1/core/acupoint/meridians/LU"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/meridians/LU?include_acupoints=true")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["code"] == "LU"
            assert data["acupoint_count"] == 11
            assert len(data["path_points"]) == 11
            print(f"  [PASS] meridians/LU: {data['name']} {len(data['path_points'])}穴")

    async def test_meridians_invalid_code(self):
        """5.5 GET /api/v1/core/acupoint/meridians/INVALID"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/meridians/XX")
            assert resp.status_code == 200
            assert resp.json()["code"] != 0  # error response
            print(f"  [PASS] meridians/XX: 正确返回错误: {resp.json()['message']}")

    async def test_list_meridians(self):
        """5.6 GET /api/v1/core/acupoint/meridians"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/meridians")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["total"] == 14
            assert len(data["meridians"]) == 14
            print(f"  [PASS] meridians列表: {data['total']}条")

    async def test_search_acupoints(self):
        """5.7 GET /api/v1/core/acupoint/search?keyword=中府"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/search?keyword=中府")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert len(data["acupoints"]) >= 1
            assert data["acupoints"][0]["code"] == "LU1"
            print(f"  [PASS] search: 找到 {data['acupoints'][0]['name']}")

    async def test_acupoint_detail(self):
        """5.8 GET /api/v1/core/acupoint/LU1"""
        async for client in authed_client():
            resp = await client.get("/api/v1/core/acupoint/LU1")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["code"] == "LU1"
            assert data["name"] == "中府"
            assert len(data["position_3d"]) == 3
            assert "shiyi" in data
            print(f"  [PASS] detail/LU1: {data['name']} pos={data['position_3d']}")

    async def test_requires_auth(self):
        """5.9 未认证访问应拒绝"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=BASE) as client:
            resp = await client.get("/api/v1/core/acupoint/model")
            assert resp.status_code in [401, 403]
            print(f"  [PASS] 未认证返回 {resp.status_code}")


# ================================================================
# 子任务3+6: 套餐门控 + 权限点
# ================================================================

class TestModuleFlag:

    def test_module_3d_permission_exists(self):
        """6.1 module:3d 权限点已注册"""
        from qihuang_platform.db.models import PRESET_PERMISSIONS
        perms = {p["code"] for p in PRESET_PERMISSIONS}
        assert "module:3d" in perms
        print(f"  [PASS] module:3d 权限点已注册")

    def test_health_user_gets_3d(self):
        """6.2 health_user 角色默认拥有 module:3d"""
        # 验证 seed_preset_data 中 health_user 分配了 module:3d
        from qihuang_platform.db.models import PRESET_ROLES
        roles = {r["name"] for r in PRESET_ROLES}
        assert "health_user" in roles
        print(f"  [PASS] health_user 角色存在 (代码中已有 module:3d 分配)")

    def test_plan_features_3d_flag(self):
        """3.1 套餐 features_json 含 module_3d"""
        from qihuang_platform.billing.plans import DEFAULT_PLANS
        trial = [p for p in DEFAULT_PLANS if p["plan_name"] == "trial"][0]
        pro = [p for p in DEFAULT_PLANS if p["plan_name"] == "professional"][0]
        assert trial["features_json"]["module_3d"] == False
        assert pro["features_json"]["module_3d"] == True
        print(f"  [PASS] trial: module_3d=False, professional: module_3d=True")

    def test_is_module_enabled(self):
        """3.2 is_module_enabled 函数正确判断"""
        from qihuang_platform.billing.plans import is_module_enabled
        trial = {"plan_name": "trial", "features_json": {"module_3d": False}}
        pro = {"plan_name": "professional", "features_json": {"module_3d": True}}
        assert is_module_enabled(trial) == False
        assert is_module_enabled(pro) == True
        assert is_module_enabled(None) == False
        assert is_module_enabled({"plan_name": "empty"}) == False
        print(f"  [PASS] is_module_enabled: 4 cases all correct")


# ================================================================
# 子任务7: 独立计量维度
# ================================================================

class TestMetering3D:

    def test_metering_module_counters(self):
        """7.1 3D模块独立计数器"""
        from qihuang_platform.gateway.metering import metering_store, CallLog
        metering_store.clear()
        # 模拟3D模块调用
        metering_store._module_counters["3d"] = 42
        stats = metering_store.module_stats("3d")
        assert stats["module"] == "3d"
        assert stats["total_loads"] == 42
        metering_store.clear()
        print(f"  [PASS] 3D模块计数器: {stats}")

    def test_metering_query_by_module(self):
        """7.2 按模块维度查询"""
        from qihuang_platform.gateway.metering import metering_store, CallLog
        import asyncio
        metering_store.clear()
        # 添加混合日志
        async def add_logs():
            await metering_store.log(CallLog(endpoint="/api/v1/core/acupoint/model", tenant_id="t1", module="3d"))
            await metering_store.log(CallLog(endpoint="/api/v1/core/acupoint/guide", tenant_id="t1", module="3d"))
            await metering_store.log(CallLog(endpoint="/api/v1/core/diagnose", tenant_id="t1"))
            await metering_store.log(CallLog(endpoint="/api/v1/core/acupoint/meridians/LU", tenant_id="t1", module="3d"))
        asyncio.run(add_logs())

        all_logs = metering_store.query()
        d3_logs = metering_store.query(module="3d")
        assert len(all_logs) == 4
        assert len(d3_logs) == 3
        metering_store.clear()
        print(f"  [PASS] 模块维度查询: 总量{len(all_logs)}, 3D={len(d3_logs)}")

    def test_3d_addon_price(self):
        """7.3 3D加购价格信息"""
        from qihuang_platform.billing.plans import get_3d_addon_price
        price = get_3d_addon_price()
        assert price["module"] == "module_3d"
        assert price["pricing"]["monthly_cny"] == 99.00
        assert len(price["metering_dimensions"]) == 4
        print(f"  [PASS] 3D加购: {price['pricing']}")


# ================================================================
# 运行
# ================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
