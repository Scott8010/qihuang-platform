"""
Mock 路由 — 模拟 auth + core 全部端点响应
Phase 0 前端并行开发用，Phase 1 对接真实后端后废弃。
"""
import time
import uuid
from fastapi import APIRouter, Query

router = APIRouter(tags=["Mock"])

# ─── 通用工具 ───
def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

def _resp(code: int = 0, message: str = "ok", data: dict = None):
    return {
        "code": code,
        "message": message,
        "data": data or {},
        "trace_id": str(uuid.uuid4())[:8],
    }


# ═══════════════════════════════════════════════════════════
# Auth 认证端点（7个）
# 对应接口规范 2.1-2.7
# ═══════════════════════════════════════════════════════════

@router.post("/auth/wechat-login")
async def mock_wechat_login(code: str = "mock_wx_code"):
    """微信小程序登录 → JWT token"""
    return _resp(data={
        "access_token": "mock_jwt_access_xxxx",
        "refresh_token": "mock_jwt_refresh_xxxx",
        "expires_in": 7200,
        "user": {
            "user_id": "mock_uid_001",
            "nickname": "测试用户",
            "avatar": "https://example.com/avatar.png",
            "tenant_id": "mock_tid_001",
            "tenant_name": "测试租户",
        },
    })


@router.post("/auth/sms-code")
async def mock_sms_send(phone: str = "13800138000"):
    """发送短信验证码"""
    return _resp(data={"expires_in": 300, "phone": f"{phone[:3]}****{phone[-4:]}"})


@router.post("/auth/phone-login")
async def mock_phone_login(phone: str = "13800138000", code: str = "123456"):
    """手机验证码登录"""
    return _resp(data={
        "access_token": "mock_jwt_access_xxxx",
        "refresh_token": "mock_jwt_refresh_xxxx",
        "expires_in": 7200,
    })


@router.post("/auth/refresh")
async def mock_refresh_token(refresh_token: str = "mock_jwt_refresh_xxxx"):
    """刷新 access_token"""
    return _resp(data={
        "access_token": "mock_jwt_access_new_xxxx",
        "expires_in": 7200,
    })


@router.get("/auth/profile")
async def mock_user_profile():
    """获取当前用户信息"""
    return _resp(data={
        "user_id": "mock_uid_001",
        "nickname": "测试用户",
        "phone": "138****8000",
        "tenant_id": "mock_tid_001",
        "tenant_name": "测试租户",
        "org_id": "mock_oid_001",
        "org_name": "默认机构",
        "roles": ["TENANT_ADMIN"],
        "plan": "trial",
        "usage_today": 3,
        "quota_daily": 10,
        "created_at": _now_iso(),
    })


@router.post("/auth/switch-org")
async def mock_switch_org(org_id: str = "mock_oid_002"):
    """切换登录机构"""
    return _resp(data={
        "org_id": org_id,
        "org_name": f"机构-{org_id[-4:]}",
        "roles": ["ORG_ADMIN"],
    })


@router.post("/auth/logout")
async def mock_logout():
    """登出（Token失效）"""
    return _resp(message="已登出")


# ═══════════════════════════════════════════════════════════
# Core 中台能力端点（7个）
# 对应接口规范 4.1.1-4.1.7
# ═══════════════════════════════════════════════════════════

@router.post("/core/reasoning/diagnose")
async def mock_diagnose():
    """综合辨证推理"""
    return _resp(data={
        "session_id": "mock_sess_001",
        "syndromes": [
            {"name": "肝郁气滞证", "confidence": 0.85, "reasoning": "Mock: 症见胸胁胀痛、情绪抑郁、脉弦，符合……"},
            {"name": "脾虚湿盛证", "confidence": 0.62, "reasoning": "Mock: 兼见纳差、便溏、舌淡胖有齿痕……"},
        ],
        "recommendations": ["逍遥散加减", "柴胡疏肝散"],
        "token_used": 1520,
        "cost_cents": 0.3,
    })


@router.post("/core/reasoning/{system}")
async def mock_reasoning_system(system: str):
    """单体系辨证: bagang / liujing / zangfu / zabing / wenbing"""
    return _resp(data={
        "system": system,
        "result": f"Mock {system} 辨证结果",
        "evidence": [{"source": "伤寒论·第X条", "quote": "……（条文节选）"}],
        "confidence": 0.78,
    })


@router.post("/core/safety/check")
async def mock_safety_check():
    """用药安全四级审查"""
    return _resp(data={
        "level": "LOW",
        "warnings": [],
        "contraindications": [],
        "detail": {
            "shibafan": [],       # 十八反
            "shijiouwei": [],     # 十九畏
            "xiangwu": [],        # 相恶配伍
            "zheng_hou": [],      # 证候禁忌
            "special_population": [],  # 特殊人群
        },
        "safe": True,
    })


@router.post("/core/graph/query")
async def mock_graph_query(intent: str = "search", keyword: str = "柴胡"):
    """图谱语义查询"""
    return _resp(data={
        "nodes": [
            {"id": "n001", "name": "柴胡", "type": "Herb", "properties": {"性": "微寒", "味": "苦辛"}},
            {"id": "n002", "name": "小柴胡汤", "type": "Formula"},
        ],
        "edges": [
            {"from": "n001", "to": "n002", "type": "CONTAINS", "properties": {"剂量": "12g"}},
        ],
        "total": 2,
        "cypher": "MATCH (n:Herb {name: '柴胡'})-[r]-(m) RETURN n,r,m LIMIT 10",
    })


@router.get("/core/graph/entities/{entity_type}/{entity_id}")
async def mock_entity_detail(entity_type: str, entity_id: str):
    """实体详情（18类：Herb/Formula/Syndrome/Disease/Symptom/Meridian/...）"""
    return _resp(data={
        "id": entity_id,
        "type": entity_type,
        "name": f"Mock-{entity_type}-{entity_id}",
        "properties": {"key": "value"},
        "relations": [],
    })


@router.post("/core/agent/chat")
async def mock_agent_chat():
    """智能对话（SSE流式，Mock返回静态结果）"""
    return _resp(data={
        "session_id": "mock_chat_001",
        "agent": "倪师",
        "reply": "Mock回答：中医讲究辨证论治，不可执一方而治百病。\n\n具体还需结合舌脉二便等信息综合判断。",
        "token_used": 890,
        "cost_cents": 0.18,
    })


@router.get("/core/literature/search")
async def mock_literature_search(q: str = "伤寒论", page: int = 1, page_size: int = 10):
    """文献检索（17源聚合Mock）"""
    results = [
        {
            "id": f"lit_{i:03d}", "title": f"Mock文献 {i}: 关于{q}的研究",
            "source": ["PubMed", "CNKI", "万方"][i % 3],
            "year": 2020 + i % 5,
            "abstract": f"本文探讨了{q}在中医临床中的应用……",
            "doi": f"10.1234/mock.{i}"
        }
        for i in range(min(page_size, 5))
    ]
    return _resp(data={
        "total": 87,
        "page": page,
        "page_size": page_size,
        "results": results,
    })


# ═══════════════════════════════════════════════════════════
# Core/3D 穴位端点（3个）
# 对应接口规范新增 /core/acupoint/*
# ═══════════════════════════════════════════════════════════

@router.get("/core/acupoint/model")
async def mock_acupoint_model():
    """获取3D模型元数据"""
    return _resp(data={
        "version": "1.0.0",
        "models": {
            "body": "https://cdn.mock.qihuang/3d/body_v1.glb",
            "meridians": "https://cdn.mock.qihuang/3d/meridians_v1.glb",
        },
        "acupoint_count": 361,
        "meridian_count": 14,
        "cdn_base": "https://cdn.mock.qihuang/3d/",
    })


@router.post("/core/acupoint/guide")
async def mock_acupoint_guide(acupoints: list = None):
    """穴位保健指导"""
    return _resp(data={
        "acupoints": acupoints or ["足三里", "合谷"],
        "guide": [
            {"name": "足三里", "location": "外膝眼下3寸", "massage": "按揉3-5分钟", "effect": "健脾和胃"},
        ],
    })


@router.get("/core/acupoint/meridians/{meridian_code}")
async def mock_meridian_detail(meridian_code: str = "LU"):
    """经络详情与循行路径"""
    return _resp(data={
        "code": meridian_code,
        "name": {"LU": "手太阴肺经"}.get(meridian_code, "未知"),
        "path_3d": [[0.0, 0.0, 0.0], [0.1, 0.2, 0.0]],  # 3D坐标数组
        "acupoints": ["中府", "云门", "天府", "尺泽", "列缺", "太渊", "少商"],
    })
