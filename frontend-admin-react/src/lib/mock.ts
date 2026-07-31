// 岐黄智脑·运营控制台 —— 演示数据（真实数据接口见《接口规范与数据字典》4.3 节 /admin/v1）
export const C = {
  primary: "#2E5A4C",
  primaryLight: "#3D7363",
  accent: "#C8A45D",
  gold: "#8A6A1F",
  ink: "#22312B",
  mid: "#4A5B54",
  light: "#8FA9A0",
  bg: "#F3F6F4",
  soft: "#EAF2EE",
  border: "#E3ECE8",
};

export const sceneMap: Record<string, { label: string; color: string; bg: string }> = {
  MED: { label: "医疗", color: "#B03A2E", bg: "#FDECEA" },
  HEALTH: { label: "大健康", color: "#2E5A4C", bg: "#EAF2EE" },
  EDU: { label: "培训", color: "#8A6A1F", bg: "#FBF4E4" },
};

export const statusMap: Record<string, { label: string; cls: string }> = {
  TRIAL: { label: "试用", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  ACTIVE: { label: "正常", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  READONLY: { label: "只读降级", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  EXPIRED: { label: "已到期", cls: "bg-red-50 text-red-600 border-red-200" },
  CLOSED: { label: "已关闭", cls: "bg-gray-100 text-gray-500 border-gray-200" },
};

export interface Tenant {
  id: string; name: string; scene: "MED" | "HEALTH" | "EDU";
  plan: string; orgs: number; users: number;
  usedCalls: number; quotaCalls: number; status: string; expires: string; module3d: boolean;
}

export const tenants: Tenant[] = [
  { id: "T-10240001", name: "颐森汇健康集团", scene: "HEALTH", plan: "专业版", orgs: 36, users: 1284, usedCalls: 386200, quotaCalls: 500000, status: "ACTIVE", expires: "2027-06-30", module3d: true },
  { id: "T-10240002", name: "沪上云杉中医馆（连锁）", scene: "MED", plan: "标准版", orgs: 8, users: 64, usedCalls: 42100, quotaCalls: 50000, status: "ACTIVE", expires: "2026-12-31", module3d: false },
  { id: "T-10240003", name: "滇南康养之家", scene: "HEALTH", plan: "标准版", orgs: 5, users: 402, usedCalls: 18900, quotaCalls: 50000, status: "ACTIVE", expires: "2026-11-30", module3d: true },
  { id: "T-10240004", name: "杏林在线教育学院", scene: "EDU", plan: "专业版", orgs: 12, users: 3560, usedCalls: 610400, quotaCalls: 500000, status: "READONLY", expires: "2026-07-31", module3d: true },
  { id: "T-10240005", name: "徐汇区田林社区卫生服务站", scene: "MED", plan: "体验版", orgs: 1, users: 9, usedCalls: 2870, quotaCalls: 3000, status: "TRIAL", expires: "2026-08-24", module3d: false },
  { id: "T-10240006", name: "岐黄师承研习社", scene: "EDU", plan: "标准版", orgs: 3, users: 218, usedCalls: 12600, quotaCalls: 50000, status: "ACTIVE", expires: "2027-03-31", module3d: false },
  { id: "T-10240007", name: "松江区方松社区卫生服务站", scene: "MED", plan: "体验版", orgs: 1, users: 6, usedCalls: 3012, quotaCalls: 3000, status: "EXPIRED", expires: "2026-07-20", module3d: false },
  { id: "T-10240008", name: "天津颐和堂大药房连锁", scene: "HEALTH", plan: "标准版", orgs: 22, users: 96, usedCalls: 33800, quotaCalls: 50000, status: "ACTIVE", expires: "2026-10-15", module3d: false },
];

export const callTrend = Array.from({ length: 30 }, (_, i) => {
  const base = 8200 + Math.sin(i / 3.2) * 1800 + i * 120;
  return {
    day: `07-${String(i + 1).padStart(2, "0")}`,
    大健康: Math.round(base * 0.52),
    医疗: Math.round(base * 0.28),
    培训: Math.round(base * 0.2),
  };
});

export const sceneDist = [
  { name: "大健康", value: 3, fill: "#2E5A4C" },
  { name: "医疗", value: 3, fill: "#B03A2E" },
  { name: "培训", value: 2, fill: "#C8A45D" },
];

export const alerts = [
  { level: "high", text: "杏林在线教育学院：月调用量已超配额 122%，已触发只读降级", time: "10 分钟前" },
  { level: "mid", text: "田林社区卫生服务站：体验版将于 2026-08-24 到期", time: "2 小时前" },
  { level: "mid", text: "方松社区卫生服务站：配额耗尽且已到期，待商务跟进", time: "5 小时前" },
  { level: "low", text: "LLM 日成本 ¥182.40，环比 +6.2%（预算阈值 80%）", time: "今天 08:00" },
];

export const todoReview = [
  { id: "KR-8812", type: "Herb", name: "炒酸枣仁", conf: 0.58, source: "自生长·文献雷达", reviewer: "小张" },
  { id: "KR-8811", type: "Syndrome", name: "少阳郁热证", conf: 0.44, source: "自生长·PubMed", reviewer: "大张" },
  { id: "KR-8809", type: "MedicalCase", name: "桂枝汤治自汗案（共享回流）", conf: 0.61, source: "租户医案回流", reviewer: "大张" },
  { id: "KR-8806", type: "ClassicText", name: "《温病条辨》上焦篇第十四条校注", conf: 0.37, source: "专家手工提交", reviewer: "小张" },
];

export interface RoleTpl {
  code: string; name: string; scene: string; users: number; scope: string;
  menus: string[]; apis: string[];
}

export const roleTpls: RoleTpl[] = [
  { code: "PLATFORM_OPS", name: "运营管理员", scene: "平台", users: 4, scope: "全部数据", menus: ["全部菜单"], apis: ["admin:*"] },
  { code: "MED_DOCTOR", name: "执业医师", scene: "MED", users: 58, scope: "本人及授权患者", menus: ["辅助辨证", "处方审查", "医案管理", "报告中心"], apis: ["med:diagnose", "med:rx:review", "med:case:write", "med:report", "module:3d"] },
  { code: "MED_DIRECTOR", name: "科室主任", scene: "MED", users: 9, scope: "本科室", menus: ["医生全部", "科室看板"], apis: ["med:*（不含代开方）"] },
  { code: "MED_ORG_ADMIN", name: "机构管理员", scene: "MED", users: 12, scope: "本机构", menus: ["账号管理", "用量报表"], apis: ["org:manage", "usage:read"] },
  { code: "HEALTH_MEMBER", name: "C端用户", scene: "HEALTH", users: 1680, scope: "仅本人", menus: ["体质辨识", "调理方案", "健康档案", "穴位指导"], apis: ["health:assess", "health:plan", "health:archive", "module:3d"] },
  { code: "HEALTH_ADVISOR", name: "健康顾问", scene: "HEALTH", users: 96, scope: "所管用户", menus: ["会员管理", "跟进记录"], apis: ["health:advisor"] },
  { code: "EDU_TEACHER", name: "教师", scene: "EDU", users: 42, scope: "本班级", menus: ["课程管理", "题库", "学情看板"], apis: ["edu:exam:write", "edu:progress"] },
  { code: "EDU_STUDENT", name: "学员", scene: "EDU", users: 3560, scope: "仅本人", menus: ["经典学习", "AI陪练", "测评"], apis: ["edu:classic", "edu:coach", "edu:exam"] },
  { code: "EDU_RESEARCHER", name: "教研专家", scene: "EDU", users: 6, scope: "全租户题库", menus: ["教师全部", "题库审校", "图谱标注"], apis: ["edu:*", "kg:review", "module:3d"] },
];

export interface ApiKey {
  id: string; tenant: string; appKey: string; purpose: string;
  qps: number; used: number; quota: number; status: string; expires: string;
}

export const apiKeys: ApiKey[] = [
  { id: "K-01", tenant: "颐森汇健康集团", appKey: "qh_9f2k****8d1x", purpose: "PROD", qps: 50, used: 386200, quota: 500000, status: "ACTIVE", expires: "2027-06-30" },
  { id: "K-02", tenant: "颐森汇健康集团", appKey: "qh_test****3c7a", purpose: "TEST", qps: 5, used: 1240, quota: 10000, status: "ACTIVE", expires: "2026-12-31" },
  { id: "K-03", tenant: "沪上云杉中医馆", appKey: "qh_7h4m****2f9e", purpose: "PROD", qps: 10, used: 42100, quota: 50000, status: "ACTIVE", expires: "2026-12-31" },
  { id: "K-04", tenant: "杏林在线教育学院", appKey: "qh_3j8p****6k2b", purpose: "PROD", qps: 50, used: 610400, quota: 500000, status: "ROTATING", expires: "2026-07-31" },
  { id: "K-05", tenant: "杏林在线教育学院", appKey: "qh_new5****9q4w", purpose: "PROD", qps: 50, used: 0, quota: 500000, status: "ACTIVE", expires: "2026-07-31" },
  { id: "K-06", tenant: "天津颐和堂大药房", appKey: "qh_5t6y****1z8c", purpose: "PROD", qps: 10, used: 33800, quota: 50000, status: "REVOKED", expires: "2026-10-15" },
];

export const keyStatus: Record<string, { label: string; cls: string }> = {
  ACTIVE: { label: "正常", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  ROTATING: { label: "轮换中", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  REVOKED: { label: "已吊销", cls: "bg-red-50 text-red-600 border-red-200" },
  EXPIRED: { label: "已过期", cls: "bg-gray-100 text-gray-500 border-gray-200" },
};

export const sceneUsage = [
  { scene: "大健康", calls: 405100, tokens: 1820, cost: 69.2 },
  { scene: "医疗", calls: 45100, tokens: 640, cost: 24.3 },
  { scene: "培训", calls: 623000, tokens: 2960, cost: 88.9 },
];

export const bills = [
  { id: "B-202607-01", tenant: "颐森汇健康集团", period: "2026-07", calls: "38.6万", tokens: "1,240万", amount: 48600, status: "ISSUED" },
  { id: "B-202607-02", tenant: "杏林在线教育学院", period: "2026-07", calls: "61.0万", tokens: "2,960万", amount: 39800, status: "OVERDUE" },
  { id: "B-202607-03", tenant: "沪上云杉中医馆", period: "2026-07", calls: "4.2万", tokens: "640万", amount: 12000, status: "PAID" },
  { id: "B-202607-04", tenant: "滇南康养之家", period: "2026-07", calls: "1.9万", tokens: "280万", amount: 12000, status: "PAID" },
  { id: "B-202607-05", tenant: "岐黄师承研习社", period: "2026-07", calls: "1.3万", tokens: "190万", amount: 12000, status: "DRAFT" },
];

export const billStatus: Record<string, { label: string; cls: string }> = {
  DRAFT: { label: "待生成", cls: "bg-gray-100 text-gray-600 border-gray-200" },
  ISSUED: { label: "已出账", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  PAID: { label: "已支付", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  OVERDUE: { label: "已逾期", cls: "bg-red-50 text-red-600 border-red-200" },
};

export const plans = [
  { name: "体验版", price: "免费 30 天", qps: 2, calls: "3,000 次/月", tokens: "10 万", m3d: false, cur: false },
  { name: "标准版", price: "¥12,000/年", qps: 10, calls: "5 万次/月", tokens: "200 万", m3d: false, cur: false },
  { name: "专业版", price: "¥39,800/年", qps: 50, calls: "50 万次/月", tokens: "2,000 万", m3d: true, cur: true },
  { name: "私有化", price: "项目制", qps: -1, calls: "不限", tokens: "客户自采", m3d: true, cur: false },
];

export const sensitiveWords = [
  { word: "根治", scene: "HEALTH", cat: "MEDICAL_CLAIM", action: "BLOCK", status: true },
  { word: "治愈", scene: "HEALTH", cat: "MEDICAL_CLAIM", action: "BLOCK", status: true },
  { word: "包治百病", scene: "ALL", cat: "AD_LAW", action: "BLOCK", status: true },
  { word: "代替医生", scene: "HEALTH", cat: "MEDICAL_CLAIM", action: "REVIEW", status: true },
  { word: "最先进", scene: "ALL", cat: "AD_LAW", action: "REPLACE", status: false },
];

export const services = [
  { name: "API 网关", status: "运行正常", latency: "42ms", uptime: "99.98%", ok: true },
  { name: "中台应用（FastAPI）", status: "运行正常", latency: "186ms", uptime: "99.95%", ok: true },
  { name: "Neo4j 图谱库", status: "运行正常", latency: "12ms", uptime: "99.99%", ok: true },
  { name: "PostgreSQL 业务库", status: "运行正常", latency: "8ms", uptime: "99.99%", ok: true },
  { name: "LLM 共识集群", status: "DeepSeek 备用切换中", latency: "1240ms", uptime: "99.91%", ok: false },
];

export const llmUsage = [
  { model: "DeepSeek", tokens: 3120, cost: 84.2 },
  { model: "GLM-4", tokens: 980, cost: 39.6 },
  { model: "Kimi", tokens: 720, cost: 33.5 },
  { model: "通义千问", tokens: 600, cost: 25.1 },
];

export const auditLogs = [
  { time: "2026-07-26 14:32", op: "王运营", action: "api_key.rotate", target: "K-04（杏林在线）", ip: "10.8.0.12" },
  { time: "2026-07-26 11:05", op: "李商务", action: "tenant.create", target: "天津颐和堂大药房连锁", ip: "10.8.0.15" },
  { time: "2026-07-26 09:47", op: "张内容", action: "content.review.approve", target: "KR-8805 麸炒白术", ip: "10.8.0.21" },
  { time: "2026-07-25 18:20", op: "王运营", action: "tenant.status.readonly", target: "杏林在线教育学院", ip: "10.8.0.12" },
  { time: "2026-07-25 16:08", op: "系统", action: "billing.bill.generate", target: "2026-07 账期 x 5", ip: "—" },
];

// ============================================================
// 下层详情数据（租户详情 / 账单明细 / 审核详情 / 密钥日志 / 告警规则）
// ============================================================

export interface Org { id: string; name: string; type: string; users: number; status: string }

const orgPool: Record<string, Org[]> = {
  "T-10240001": [
    { id: "O-3101", name: "颐森汇·静安旗舰馆", type: "康养门店", users: 86, status: "ACTIVE" },
    { id: "O-3102", name: "颐森汇·浦东分馆", type: "康养门店", users: 64, status: "ACTIVE" },
    { id: "O-3103", name: "颐森汇·线上健康商城", type: "线上渠道", users: 31, status: "ACTIVE" },
  ],
  "T-10240002": [
    { id: "O-3201", name: "云杉中医馆·徐汇总院", type: "中医门诊", users: 28, status: "ACTIVE" },
    { id: "O-3202", name: "云杉中医馆·虹桥分院", type: "中医门诊", users: 19, status: "ACTIVE" },
  ],
  "T-10240004": [
    { id: "O-3401", name: "杏林在线·执业医师班", type: "教学班级", users: 1240, status: "ACTIVE" },
    { id: "O-3402", name: "杏林在线·经典研读班", type: "教学班级", users: 980, status: "ACTIVE" },
    { id: "O-3403", name: "杏林在线·师承研修班", type: "教学班级", users: 356, status: "ACTIVE" },
  ],
};

export const getOrgs = (t: Tenant): Org[] =>
  orgPool[t.id] ?? [
    { id: "O-3901", name: `${t.name}·总部`, type: "默认机构", users: t.users, status: "ACTIVE" },
  ];

export interface TenantUser {
  id: string; name: string; phone: string; role: string; org: string; status: string; lastActive: string;
}

const userPool: Record<string, TenantUser[]> = {
  "T-10240001": [
    { id: "U-90001", name: "林晚晴", phone: "138****2201", role: "健康顾问", org: "静安旗舰馆", status: "ACTIVE", lastActive: "10 分钟前" },
    { id: "U-90002", name: "赵启铭", phone: "139****8812", role: "机构管理员", org: "总部", status: "ACTIVE", lastActive: "1 小时前" },
    { id: "U-90003", name: "苏念", phone: "186****0093", role: "C端用户", org: "线上商城", status: "ACTIVE", lastActive: "刚刚" },
    { id: "U-90004", name: "陈默", phone: "135****7745", role: "健康顾问", org: "浦东分馆", status: "DISABLED", lastActive: "3 天前" },
    { id: "U-90005", name: "何雨桐", phone: "150****3319", role: "C端用户", org: "静安旗舰馆", status: "ACTIVE", lastActive: "26 分钟前" },
  ],
  "T-10240002": [
    { id: "U-91001", name: "沈知微", phone: "137****5540", role: "执业医师", org: "徐汇总院", status: "ACTIVE", lastActive: "5 分钟前" },
    { id: "U-91002", name: "吴其仁", phone: "136****9982", role: "科室主任", org: "徐汇总院", status: "ACTIVE", lastActive: "42 分钟前" },
    { id: "U-91003", name: "郑半夏", phone: "158****1167", role: "执业医师", org: "虹桥分院", status: "ACTIVE", lastActive: "2 小时前" },
  ],
};

export const getUsers = (t: Tenant): TenantUser[] =>
  userPool[t.id] ?? [
    { id: "U-99001", name: "管理员", phone: "—", role: "机构管理员", org: "总部", status: "ACTIVE", lastActive: "1 天前" },
  ];

export const userStatusMap: Record<string, { label: string; cls: string }> = {
  ACTIVE: { label: "正常", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  DISABLED: { label: "已禁用", cls: "bg-gray-100 text-gray-500 border-gray-200" },
  LOCKED: { label: "已锁定", cls: "bg-amber-50 text-amber-700 border-amber-200" },
};

// 租户近 30 天调用趋势（按租户规模缩放）
export const tenantTrend = (t: Tenant) =>
  Array.from({ length: 30 }, (_, i) => {
    const daily = t.usedCalls / 30;
    return {
      day: `07-${String(i + 1).padStart(2, "0")}`,
      calls: Math.round(daily * (0.75 + Math.sin(i / 3.5) * 0.2 + i * 0.012)),
    };
  });

// 端点级用量（租户详情·概览）
export const endpointUsage = [
  { endpoint: "/health/v1/assess", name: "体质辨识", calls: 142300, avg: "1.8s", err: "0.12%" },
  { endpoint: "/health/v1/plan", name: "调理方案", calls: 98400, avg: "2.4s", err: "0.09%" },
  { endpoint: "/core/v1/graph/query", name: "图谱查询", calls: 76200, avg: "0.3s", err: "0.02%" },
  { endpoint: "/core/v1/acupoint/guide", name: "穴位指导(3D)", calls: 41800, avg: "0.6s", err: "0.05%" },
  { endpoint: "/health/v1/archive", name: "健康档案", calls: 27500, avg: "0.4s", err: "0.01%" },
];

// 功能开关（features_json）
export const featureFlags = (t: Tenant) => [
  { key: "report", name: "报告中心", desc: "辨证/调理报告生成与 PDF 导出", on: true, locked: false },
  { key: "module_3d", name: "岐黄三境·3D 模块", desc: "穴位 3D 可视化，单独计量计费", on: t.module3d, locked: false, addon: true },
  { key: "api_access", name: "开放 API 接入", desc: "允许以 API Key 方式调用", on: t.plan !== "体验版", locked: t.plan === "体验版" },
  { key: "case_share", name: "医案共享回流", desc: "脱敏医案回流中台图谱（审核后入库）", on: t.scene === "MED", locked: false },
  { key: "data_export", name: "数据导出", desc: "业务数据批量导出（留痕）", on: t.plan === "专业版" || t.plan === "私有化", locked: false },
];

// 账单明细行项目
export interface BillLine { item: string; spec: string; qty: string; unit: string; amount: number }
export const billLines: Record<string, BillLine[]> = {
  "B-202607-01": [
    { item: "套餐费", spec: "专业版·年付分摊", qty: "1", unit: "月", amount: 39800 },
    { item: "岐黄三境 3D 模块", spec: "组件加载 8,412 次 x ¥0.6", qty: "8,412", unit: "次", amount: 5047 },
    { item: "超量 Token", spec: "超出 2,000 万部分 x ¥1.2/万", qty: "240", unit: "万", amount: 288 },
    { item: "CDN 流量", spec: "3D 资产分发 41.2GB", qty: "41.2", unit: "GB", amount: 465 },
    { item: "年付优惠", spec: "年付 95 折", qty: "1", unit: "项", amount: -1000 },
  ],
  "B-202607-02": [
    { item: "套餐费", spec: "专业版·年付分摊", qty: "1", unit: "月", amount: 39800 },
    { item: "超量调用", spec: "超出 50 万次部分 x ¥0.08", qty: "110,400", unit: "次", amount: 8832 },
    { item: "岐黄三境 3D 模块", spec: "组件加载 5,230 次 x ¥0.6", qty: "5,230", unit: "次", amount: 3138 },
    { item: "逾期前减免", spec: "商务审批单 SO-2211", qty: "1", unit: "项", amount: -11970 },
  ],
};
export const defaultLines = (amount: number): BillLine[] => [
  { item: "套餐费", spec: "标准版·年付分摊", qty: "1", unit: "月", amount },
];

// 知识审核详情
export interface ReviewDetail {
  content: string;
  evidence: { src: string; snippet: string }[];
  conf: { dim: string; score: number }[];
  similar: { node: string; rel: string; sim: string }[];
}
export const reviewDetails: Record<string, ReviewDetail> = {
  "KR-8812": {
    content: "炒酸枣仁：甘、酸，平。归心、肝、胆经。养心补肝，宁心安神，敛汗，生津。用于虚烦不眠，惊悸多梦，体虚多汗，津伤口渴。炒制后安神作用增强，兼能醒脾。",
    evidence: [
      { src: "《中国药典》2020 年版一部", snippet: "酸枣仁…养心补肝，宁心安神，敛汗，生津…" },
      { src: "文献雷达·CNKI 2024-117", snippet: "炒制对酸枣仁皂苷 A 溶出率提升约 23%，镇静催眠活性增强…" },
    ],
    conf: [
      { dim: "来源权威性", score: 0.92 },
      { dim: "多源一致性", score: 0.61 },
      { dim: "图谱冲突检测", score: 0.38 },
      { dim: "抽取模型置信", score: 0.55 },
    ],
    similar: [
      { node: "酸枣仁（生）", rel: "炮制变体", sim: "0.94" },
      { node: "柏子仁", rel: "功效相似·安神", sim: "0.71" },
      { node: "夜交藤", rel: "常相须为用", sim: "0.66" },
    ],
  },
  "KR-8811": {
    content: "少阳郁热证：少阳枢机不利，郁而化热。症见往来寒热，胸胁苦满，口苦咽干，心烦喜呕，舌红苔薄黄，脉弦数。治宜和解少阳、清泄郁热，方选小柴胡汤加减。",
    evidence: [
      { src: "PubMed PMID-3822****", snippet: "Shaoyang syndrome with heat transformation pattern shows…" },
      { src: "《伤寒论》第 96 条", snippet: "伤寒五六日，中风，往来寒热，胸胁苦满…" },
    ],
    conf: [
      { dim: "来源权威性", score: 0.71 },
      { dim: "多源一致性", score: 0.42 },
      { dim: "图谱冲突检测", score: 0.35 },
      { dim: "抽取模型置信", score: 0.48 },
    ],
    similar: [
      { node: "少阳证", rel: "父证型", sim: "0.91" },
      { node: "胆郁痰扰证", rel: "鉴别诊断", sim: "0.68" },
    ],
  },
};
export const defaultReview = (name: string): ReviewDetail => ({
  content: `${name}：条目全文由自生长引擎自动抽取，待人工核对原文。`,
  evidence: [{ src: "待补充", snippet: "证据链抽取中…" }],
  conf: [
    { dim: "来源权威性", score: 0.5 },
    { dim: "多源一致性", score: 0.4 },
    { dim: "图谱冲突检测", score: 0.4 },
    { dim: "抽取模型置信", score: 0.45 },
  ],
  similar: [{ node: "—", rel: "暂无相似节点", sim: "—" }],
});

// 密钥调用日志
export const callLogs = [
  { time: "2026-07-27 10:42:18", endpoint: "/health/v1/assess", status: 200, latency: "1.72s", ip: "118.31.**.**" },
  { time: "2026-07-27 10:41:55", endpoint: "/core/v1/acupoint/guide", status: 200, latency: "0.58s", ip: "118.31.**.**" },
  { time: "2026-07-27 10:41:02", endpoint: "/health/v1/plan", status: 200, latency: "2.31s", ip: "118.31.**.**" },
  { time: "2026-07-27 10:39:47", endpoint: "/health/v1/plan", status: 429, latency: "0.02s", ip: "118.31.**.**" },
  { time: "2026-07-27 10:38:11", endpoint: "/core/v1/graph/query", status: 200, latency: "0.31s", ip: "47.101.**.**" },
  { time: "2026-07-27 10:36:58", endpoint: "/health/v1/assess", status: 200, latency: "1.94s", ip: "47.101.**.**" },
  { time: "2026-07-27 10:35:26", endpoint: "/health/v1/archive", status: 401, latency: "0.01s", ip: "203.119.**.**" },
];

// 密钥近 14 天用量
export const keyTrend = Array.from({ length: 14 }, (_, i) => ({
  day: `07-${String(i + 14).padStart(2, "0")}`,
  calls: Math.round(11500 + Math.sin(i / 2.2) * 3200 + i * 260),
}));

// 告警规则
export const alertRulesSeed = [
  { id: "R-01", name: "配额超 90% 预警", target: "租户·月调用量", cond: "使用率 >= 90%", channel: "控制台 + 邮件", enabled: true },
  { id: "R-02", name: "超配额自动降级", target: "租户·月调用量", cond: "使用率 >= 100% -> 只读", channel: "控制台 + 短信", enabled: true },
  { id: "R-03", name: "LLM 日成本预警", target: "共识集群·成本", cond: ">= 预算 80%", channel: "控制台", enabled: true },
  { id: "R-04", name: "API 错误率告警", target: "网关·5xx 比例", cond: ">= 1% 持续 5 分钟", channel: "控制台 + 短信", enabled: false },
  { id: "R-05", name: "密钥异地调用", target: "API Key·来源 IP", cond: "非常用 IP 段", channel: "邮件", enabled: false },
];

// 服务 24h 延迟曲线（监控详情）
export const svcLatency = Array.from({ length: 24 }, (_, i) => ({
  h: `${String(i).padStart(2, "0")}:00`,
  p50: Math.round(150 + Math.sin(i / 4) * 40),
  p99: Math.round(420 + Math.sin(i / 3) * 130 + (i > 13 && i < 16 ? 300 : 0)),
}));

// 工作台·多任务卡片堆
export interface DeckTask {
  id: string; type: string; title: string; desc: string;
  page: string; tone: "red" | "amber" | "blue" | "gold" | "green"; tag: string;
}

export const taskDeck: DeckTask[] = [
  { id: "D1", type: "知识审核", title: "炒酸枣仁 · 自生长入库审核", desc: "置信度 0.58，图谱冲突检测仅 0.38；来源《药典》+ CNKI 双证据，建议合并至酸枣仁条目", page: "content", tone: "red", tag: "4 条待审" },
  { id: "D2", type: "账单逾期", title: "杏林在线教育学院 · ¥39,800", desc: "2026-07 账期已逾期 5 天，超配额 122% 已只读降级；逾期满 7 天将自动升级催收", page: "billing", tone: "red", tag: "1 张逾期" },
  { id: "D3", type: "密钥轮换", title: "杏林在线 PROD 密钥轮换中", desc: "72h 新旧并行期剩余约 41 小时，旧 Key 到期自动失效；需确认客户端已切换新 Key", page: "keys", tone: "blue", tag: "剩 41h" },
  { id: "D4", type: "租户到期", title: "田林社区卫生服务站 · 体验版", desc: "2026-08-24 到期，用量已达配额 96%，转化意向高；建议商务提前 2 周跟进", page: "tenants", tone: "amber", tag: "3 家将到期" },
  { id: "D5", type: "增值申请", title: "滇南康养之家申请开通 3D 模块", desc: "module_3d 加购待审批：标准版 + 3D 增值，预计月增收约 ¥1,800", page: "tenants", tone: "gold", tag: "待审批" },
  { id: "D6", type: "内容合规", title: "敏感词「最先进」替换策略复核", desc: "广告法违禁词，当前为停用状态；培训场景文案抽检命中 2 处，建议启用替换策略", page: "content", tone: "green", tag: "2 处命中" },
];
