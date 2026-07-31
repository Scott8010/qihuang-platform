// ═══════════════════════════════════════════════════════
// 岐黄智脑 — 权限映射表（中文 ↔ API代码 ↔ 场景）
// 后端 API 代码不变，此处作为"关联说明表"供前端显示
// ═══════════════════════════════════════════════════════

export interface PermDef {
  code: string;       // API代码（不可改，后端真实使用）
  name: string;       // 中文名称
  category: string;   // 分类：管理 / 核心 / 大健康 / 培训 / 增值
  scene: string;      // 场景白名单：all / medical / health / edu
  desc: string;       // 一句话说明
}

// ── 全部 17 个权限（与后端 PRESET_PERMISSIONS 一一对应） ──

export const ALL_PERMISSIONS: PermDef[] = [
  // 管理类（6个）
  { code: "admin:tenant:manage",      name: "租户管理",   category: "管理", scene: "all", desc: "创建/编辑/删除租户及套餐配置" },
  { code: "admin:org:manage",         name: "机构管理",   category: "管理", scene: "all", desc: "创建/编辑租户下的机构树" },
  { code: "admin:user:manage",        name: "用户管理",   category: "管理", scene: "all", desc: "创建/禁用/删除用户账号" },
  { code: "admin:billing:view",       name: "账单查看",   category: "管理", scene: "all", desc: "查看用量账单与费用明细" },
  { code: "admin:monitor:view",       name: "监控查看",   category: "管理", scene: "all", desc: "服务健康/时延/QPS 监控大盘" },
  { code: "admin:audit:view",         name: "审计查看",   category: "管理", scene: "all", desc: "操作日志审计追溯" },

  // 核心能力（5个）
  { code: "core:diagnose",            name: "辨证推理",   category: "核心", scene: "medical", desc: "四诊合参·AI辨证分型" },
  { code: "core:prescription:review", name: "处方审查",   category: "核心", scene: "medical", desc: "十八反十九畏·四级处方审查" },
  { code: "core:graph:query",         name: "图谱查询",   category: "核心", scene: "all",     desc: "TCM知识图谱·实体关系查询" },
  { code: "core:agent:chat",          name: "智能对话",   category: "核心", scene: "all",     desc: "岐黄大模型·多轮辨证问答" },
  { code: "core:literature:search",   name: "文献检索",   category: "核心", scene: "all",     desc: "古籍/现代文献·智能检索佐证" },

  // 大健康（2个）
  { code: "health:constitution:assess", name: "体质辨识", category: "大健康", scene: "health", desc: "九种体质·个性化辨识评估" },
  { code: "health:plan:generate",       name: "方案生成", category: "大健康", scene: "health", desc: "药膳/茶饮/导引·个性化调理方案" },

  // 培训（3个）
  { code: "edu:coach:session",  name: "AI陪练",   category: "培训", scene: "edu", desc: "模拟问诊·AI学员陪练对话" },
  { code: "edu:exam:manage",    name: "测评管理", category: "培训", scene: "edu", desc: "智能组卷·自动判分·题库管理" },
  { code: "edu:progress:view",  name: "学情查看", category: "培训", scene: "edu", desc: "学员学习进度看板" },

  // 增值模块（1个）
  { code: "module:3d", name: "岐黄三境3D", category: "增值", scene: "all", desc: "经络穴位·3D交互可视化" },
];

// ── 快捷查询 ──

// code → PermDef
export const permByCode: Record<string, PermDef> = {};
ALL_PERMISSIONS.forEach((p) => { permByCode[p.code] = p; });

// name → PermDef
export const permByName: Record<string, PermDef> = {};
ALL_PERMISSIONS.forEach((p) => { permByName[p.name] = p; });

// ── 场景中文映射 ──

export const SCENE_LABELS: Record<string, string> = {
  all: "全场景",
  medical: "医疗",
  health: "大健康",
  edu: "培训",
};

// ── 数据范围中文映射 ──

export const SCOPE_LABELS: Record<string, string> = {
  SELF: "仅本人",
  ORG: "本机构",
  TENANT: "本租户",
};
