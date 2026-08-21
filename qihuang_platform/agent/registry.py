"""
Agent 能力注册表 — Agent 中台的资源池（控制面的「能力清单」）。

每个能力是一个融入业务流的模块（business_embedded），由某个底层引擎驱动，
通过 8602 的 tenant_id 注入与嵌套多租户隔离机制接入运营平台。

落库设计（老黄 2026-08-12 拍板「注册式 + 运营态热插拔」）：
  - AGENT_REGISTRY 为运行时缓存；agent_def 表为持久化真相源；
  - 启动期 sync_from_db() 把 DB 载入缓存，DB 为空则用 BUILTIN_AGENTS 播种；
  - 控制端启停/编辑走 register_agent / set_agent_status，写 DB + 缓存双写。
新增能力：register_agent(key, spec) 并在 agent/__init__.py 挂载其 router。
"""
from typing import Any

# 内置样板能力（部署期注册；运营态可在控制端编辑/启停）
BUILTIN_AGENTS: dict[str, dict[str, Any]] = {
    "compliance": {
        "name": "内容合规审核",
        "kind": "business_embedded",          # 融入业务流的能力模块，非对话窗口型
        "engine": "hb-compliance-guard",       # 纯规则引擎（32 条 A~F 类规则，四态判定）
        "router_prefix": "/api/v1/agent/compliance",
        "capabilities": ["scan", "feedback", "dashboard"],
        "status": "active",
        "category": "content",
        "desc": "门店经营文案送审：广告法/医疗夸大/禁忌缺失等规则四态判定，"
                "回写钉业务实体（material_key→MAT-XXXX 幂等），客观真实可反哺。",
    },
    "fortune": {
        "name": "命理运程",
        "kind": "business_embedded",          # 功能业务型，非对话窗口型
        "engine": "hb-fortune-rules",          # 纯规则引擎（八字/六爻/日签/年运）
        "router_prefix": "/api/v1/agent/fortune",
        "capabilities": ["archive", "cast", "daily", "report", "dashboard"],
        "status": "active",
        "category": "mystic",                  # 玄学大类之「看人」（与 geo_fengshui「看空间」并列）
        "desc": "命理运程趣味钩子：八字排盘/六爻起卦/每日日签(五行穿衣茶)/年运报告，"
                "独立 JSONL 落盘（不入 Neo4j），钉业务实体（material_key→FOR-XXXX 幂等），"
                "附免责声明，仅作传统文化娱乐参考。",
    },
    "geo": {
        "name": "风水堪舆",
        "kind": "business_embedded",          # 功能业务型，非对话窗口型（与 fortune 平级，看空间）
        "engine": "hb-geo-fengshui",           # 纯规则引擎（坐向/八宅/九宫/峦头）
        "router_prefix": "/api/v1/agent/geo",
        "capabilities": ["analysis", "dashboard"],
        "status": "active",
        "category": "mystic",                  # 玄学大类之「看空间」（与 fortune「看人」并列）
        "desc": "风水堪舆趣味钩子：坐向(罗盘/24山)+GPS(磁偏角校正)+户型峦头 → 宅卦/八宅吉凶方/九宫，"
                "独立 JSONL 落盘（不混 fortune 库），钉业务实体（material_key→GEO-XXXX 幂等），"
                "附免责声明，仅作传统人居环境文化娱乐参考。",
    },
    "health-advisor": {
        "name": "中医健康顾问",
        "kind": "business_embedded",          # 融入业务流的能力模块
        "engine": "qihuang-health-advisor",    # 编排层（调 8601 四诊合参引擎）
        "router_prefix": "/api/v1/agent/health-advisor",
        "capabilities": ["consult", "report", "dashboard"],
        "status": "active",
        "category": "health",
        "desc": "中医健康顾问：固定专业辨证链（体质辨识→辨证→方剂→调理），"
                "基于 8601 四诊合参引擎，partial 降级 + 免责必带，"
                "回写钉业务实体（material_key→HA-XXXX 幂等），仅作辅助参考。",
    },
    "tongue": {
        "name": "舌象健康特征分析",
        "kind": "business_embedded",          # 融入业务流的能力模块（MindSen 路 A，非对话窗口型）
        "engine": "qihuang-vision-tongue",     # 共享视觉网关（GEO_VISION_*=qwen-vl-plus）+ 15 类标签结构化 prompt
        "router_prefix": "/api/v1/agent/tongue",
        "capabilities": ["analyze"],
        "status": "active",
        "category": "health",
        "desc": "舌象健康特征分析（MindSen 舌面诊线）：舌面照片 → 视觉网关 + 15 类标签结构化 prompt "
                "→ 舌色/舌形/苔色/苔质/瘀斑瘀点等 TongueAnalysis 字段（对齐 tongue_face_analysis.md §3.5），"
                "fail-closed 不造假，去医疗化仅供健康评估参考。",
    },
    "coach": {
        "name": "中医辨证教练",
        "kind": "business_embedded",          # 融入业务流的能力模块
        "engine": "qihuang-coach",             # 复用 8602 既有 edu/coach 能力（AI 出题陪练 + 四档评分）
        "router_prefix": "/api/v1/agent/coach",
        "capabilities": ["session", "evaluate", "dashboard"],
        "status": "active",
        "category": "edu",
        "desc": "中医辨证 AI 陪练/评分：上收 8602 既有 edu/coach 能力到 Agent 中台，"
                "AI 出题陪练 + 基于推理链四档评分(PERFECT/GOOD/PARTIAL/WRONG)，"
                "回写 EduCoachSession（本店行级隔离），供业务 Agent B3 员工军师调用。",
    },
    "content-writer": {
        "name": "文案生成",
        "kind": "business_embedded",          # 融入业务流的能力模块
        "engine": "qihuang-content-writer",    # 8602 自有 4 引擎 LLM 客户端（DeepSeek→Qwen→GLM→Kimi）
        "router_prefix": "/api/v1/agent/content-writer",
        "capabilities": ["generate", "dashboard"],
        "status": "active",
        "category": "content",
        "desc": "中医健康营销文案生成：8602 自建 4 引擎 LLM 客户端（复用 refine_llm 验证过的 key 链路），"
                "默认注入合规约束 system prompt（不夸大疗效/不承诺治愈/符合广告法），"
                "支持多版本输出，与 compliance-guard 审核链路咬合（B2 营销智能 = content-writer + compliance），"
                "供业务 Agent B2 营销/拓客、经营管理等调用。",
    },
    "insight": {
        "name": "数据诊断",
        "kind": "business_embedded",          # 融入业务流的能力模块
        "engine": "qihuang-insight",          # 8602 自有 4 引擎 LLM 客户端（DeepSeek→Qwen→GLM→Kimi）
        "router_prefix": "/api/v1/agent/insight",
        "capabilities": ["diagnose", "dashboard"],
        "status": "active",
        "category": "business",
        "desc": "经营数据诊断：接收门店/租户经营指标快照（流水/客流/会员/转化/复购），"
                "AI 给出「哪有问题+为什么+怎么救」，每条结论附数据依据，"
                "护栏：只做数据诊断与经营建议、不做医疗/辨证、不承诺经营效果、决策权在人，"
                "供业务 Agent B1 经营风控 / 经营管理调用。",
    },
    "store-coach": {
        "name": "门店话术教练",
        "kind": "business_embedded",          # 融入业务流的能力模块
        "engine": "qihuang-store-coach",       # 8602 自有 4 引擎 LLM 双角色（顾客扮演 + 话术评估）
        "router_prefix": "/api/v1/agent/store-coach",
        "capabilities": ["sessions", "evaluate", "dashboard"],
        "status": "active",
        "category": "business",
        "desc": "门店话术训练：AI 扮演顾客角色，店员练习接待/推荐/异议处理/促成话术，"
                "四维话术评分（完整性/专业性/亲和力/合规性）+ 合规横切（违规标红拦截），"
                "内容模板化（DbTemplate kind=script/product/project），"
                "独立于 theory-coach（中医辨证对练，edu/coach）不混表不混语义，"
                "供业务 Agent B3 员工军师调用。",
    },
}

# 运行时缓存（与 agent_def 表最终一致）
AGENT_REGISTRY: dict[str, dict[str, Any]] = {}


def _row_to_spec(row) -> dict[str, Any]:
    return {
        "agent_key": row.agent_key,
        "name": row.name,
        "kind": row.kind,
        "engine": row.engine,
        "category": row.category,
        "router_prefix": row.router_prefix,
        "capabilities": row.capabilities or [],
        "status": row.status,
        "desc": row.desc,
        "features_json": row.features_json or {},
    }


def sync_from_db() -> int:
    """把 agent_def 表载入内存缓存；若表为空则用 BUILTIN_AGENTS 播种。

    返回载入/播种的 agent 数量。DB 不可用时静默跳过（返回 0），不阻断启动。
    """
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import AgentDef
    except Exception:
        return 0

    try:
        db = SessionLocal()
    except Exception as e:
        print(f"[AgentRegistry] DB 会话创建失败，跳过同步: {e}")
        return 0

    try:
        rows = db.query(AgentDef).all()
        existing_keys = {r.agent_key for r in rows}

        # 回补：已播种库若缺新增内置能力（如 geo），将 BUILTIN_AGENTS 中缺失项补入 DB + 缓存
        backfilled = []
        for key, spec in BUILTIN_AGENTS.items():
            if key in existing_keys:
                continue
            db.add(AgentDef(
                agent_key=key,
                name=spec.get("name", key),
                kind=spec.get("kind", "business_embedded"),
                engine=spec.get("engine"),
                category=spec.get("category", "general"),
                router_prefix=spec.get("router_prefix"),
                capabilities=spec.get("capabilities", []),
                status=spec.get("status", "active"),
                desc=spec.get("desc"),
                features_json=spec.get("features_json", {}),
            ))
            backfilled.append(key)
        if backfilled:
            db.commit()
            print(f"[AgentRegistry] 已回补新增内置能力：{', '.join(backfilled)}")

        # 回写：DB 已存在的能力，BUILTIN_AGENTS 中的「registry 控字段」必须以真值为准（防止历史 DB
        # 旧值反向覆盖代码侧的改名/desc/能力列表等）。status 保留运营态（运营手动改过的不回退）。
        # 触发场景：coach 改名「话术陪练教练」→「中医辨证教练」时，仅改 registry 源码不够，
        # 已存在 DB 行会反向覆盖；这里强制以源码真值更新 DB。
        rows = db.query(AgentDef).all()
        rewritten = []
        for row in rows:
            spec = BUILTIN_AGENTS.get(row.agent_key)
            if not spec:
                continue
            changed = False
            for f in ("name", "kind", "engine", "category", "router_prefix", "capabilities", "desc", "features_json"):
                new_val = spec.get(f) if f != "features_json" else spec.get("features_json") or {}
                if f == "name" and not new_val:
                    new_val = row.agent_key
                if getattr(row, f) != new_val:
                    setattr(row, f, new_val)
                    changed = True
            if changed:
                rewritten.append(row.agent_key)
        if rewritten:
            db.commit()
            print(f"[AgentRegistry] 已同步代码真值到 DB：{', '.join(rewritten)}")

        rows = db.query(AgentDef).all()
        AGENT_REGISTRY.clear()
        for row in rows:
            AGENT_REGISTRY[row.agent_key] = _row_to_spec(row)
        return len(AGENT_REGISTRY)
    except Exception as e:
        print(f"[AgentRegistry] 同步失败（可能表未创建）: {e}")
        # 回退到内置常量，保证进程内接口可用
        AGENT_REGISTRY.clear()
        for k, v in BUILTIN_AGENTS.items():
            AGENT_REGISTRY[k] = {**v, "agent_key": k}
        return len(AGENT_REGISTRY)
    finally:
        db.close()


def register_agent(key: str, spec: dict[str, Any]) -> None:
    """注册/更新一个 Agent 能力（写 DB + 缓存双写）。"""
    spec = dict(spec)
    spec["agent_key"] = key
    AGENT_REGISTRY[key] = spec
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import AgentDef
        db = SessionLocal()
        try:
            row = db.query(AgentDef).filter_by(agent_key=key).first()
            if row is None:
                db.add(AgentDef(
                    agent_key=key,
                    name=spec.get("name", key),
                    kind=spec.get("kind", "business_embedded"),
                    engine=spec.get("engine"),
                    category=spec.get("category", "general"),
                    router_prefix=spec.get("router_prefix"),
                    capabilities=spec.get("capabilities", []),
                    status=spec.get("status", "active"),
                    desc=spec.get("desc"),
                    features_json=spec.get("features_json", {}),
                ))
            else:
                row.name = spec.get("name", row.name)
                row.kind = spec.get("kind", row.kind)
                row.engine = spec.get("engine", row.engine)
                row.category = spec.get("category", row.category)
                row.router_prefix = spec.get("router_prefix", row.router_prefix)
                row.capabilities = spec.get("capabilities", row.capabilities)
                row.status = spec.get("status", row.status)
                row.desc = spec.get("desc", row.desc)
                row.features_json = spec.get("features_json", row.features_json)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[AgentRegistry] 注册 {key} 写库失败（仅缓存生效）: {e}")


def set_agent_status(key: str, status: str) -> bool:
    """启停某个 Agent 能力（写 DB + 缓存双写）。返回是否存在。"""
    if key not in AGENT_REGISTRY:
        # 尝试从 DB 加载
        try:
            from qihuang_platform.db.config import SessionLocal
            from qihuang_platform.db.models import AgentDef
            db = SessionLocal()
            try:
                row = db.query(AgentDef).filter_by(agent_key=key).first()
                if row:
                    AGENT_REGISTRY[key] = _row_to_spec(row)
            finally:
                db.close()
        except Exception:
            pass
    if key not in AGENT_REGISTRY:
        return False
    AGENT_REGISTRY[key]["status"] = status
    try:
        from qihuang_platform.db.config import SessionLocal
        from qihuang_platform.db.models import AgentDef
        db = SessionLocal()
        try:
            row = db.query(AgentDef).filter_by(agent_key=key).first()
            if row:
                row.status = status
                db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[AgentRegistry] 启停 {key} 写库失败（仅缓存生效）: {e}")
    return True


def get_agent(key: str) -> dict[str, Any] | None:
    return AGENT_REGISTRY.get(key)


def list_agents() -> dict[str, dict[str, Any]]:
    return AGENT_REGISTRY


def is_active(key: str) -> bool:
    spec = AGENT_REGISTRY.get(key)
    return bool(spec and spec.get("status") == "active")
