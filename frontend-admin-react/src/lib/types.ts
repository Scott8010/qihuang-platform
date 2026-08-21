// ═══════════════════════════════════════════════════════
// 岐黄大脑·运营控制台 — 类型定义与视觉常量
// ═══════════════════════════════════════════════════════

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

export const keyStatus: Record<string, { label: string; cls: string }> = {
  ACTIVE: { label: "正常", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  ROTATING: { label: "轮换中", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  REVOKED: { label: "已吊销", cls: "bg-red-50 text-red-600 border-red-200" },
  EXPIRED: { label: "已过期", cls: "bg-gray-100 text-gray-500 border-gray-200" },
};

export const billStatus: Record<string, { label: string; cls: string }> = {
  DRAFT: { label: "待生成", cls: "bg-gray-100 text-gray-600 border-gray-200" },
  ISSUED: { label: "已出账", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  PAID: { label: "已支付", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  OVERDUE: { label: "已逾期", cls: "bg-red-50 text-red-600 border-red-200" },
};

// ═══ 类型 ═══

export interface Tenant {
  id: string; name: string; scene: "MED" | "HEALTH" | "EDU";
  plan: string; planId?: string; orgs: number; users: number;
  usedCalls: number; quotaCalls: number; status: string; expires: string; module3d: boolean;
  pendingPlan?: string | null;          // 待生效预约的目标套餐
  pendingEffectiveDate?: string | null; // 待生效日期（YYYY-MM-DD）
}

export interface RolePermission {
  code: string;    // API代码 admin:tenant:manage
  name: string;    // 中文名 租户管理
  perm_type: string;
  scene: string;
}

export interface RoleTpl {
  id: string;
  code: string;           // 角色代码 super_admin
  name: string;           // 中文名 超级管理员
  description: string;    // 说明
  is_system: boolean;
  users: number;
  permissions: RolePermission[];
}

/** GET /admin/v1/permissions 的单项（全量权限池） */
export interface PermissionItem {
  code: string;
  name: string;
  perm_type: string;
  scene: string;
}

/** GET /admin/v1/users 的单项（平台级用户，非租户下钻） */
export interface PlatformUser {
  id: string;
  username: string;
  displayName: string;
  phone: string;
  email: string;
  status: string;                                   // active / disabled
  orgId: string;
  tenantId: string;
  createdAt: string;
  roles: { id: string; name: string; displayName: string }[];
}

/** 权限按场景分组时的展示口径 */
export const permSceneMap: Record<string, { label: string; color: string; bg: string }> = {
  all: { label: "通用", color: "#4A5B54", bg: "#F3F6F4" },
  medical: { label: "医疗", color: "#B03A2E", bg: "#FDECEA" },
  health: { label: "大健康", color: "#2E5A4C", bg: "#EAF2EE" },
  edu: { label: "培训", color: "#8A6A1F", bg: "#FBF4E4" },
};

/** 权限按前缀分组的中文段名 */
export const permGroupMap: Record<string, string> = {
  admin: "平台管理",
  core: "核心能力",
  health: "大健康场景",
  edu: "培训场景",
  module: "增值模块",
};

export const userStatusMap: Record<string, { label: string; cls: string }> = {
  active: { label: "正常", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  disabled: { label: "已停用", cls: "bg-gray-100 text-gray-500 border-gray-200" },
};

export interface ApiKey {
  id: string; tenant: string; appKey: string; purpose: string;
  qps: number; used: number;
  /** 后端未返回配额字段时为 null → 页面显示「不限」，不得假造数值 */
  quota: number | null;
  status: string; expires: string;
}

export interface CallTrendItem {
  day: string; 大健康: number; 医疗: number; 培训: number;
}

export interface SceneDistItem {
  name: string; value: number; fill: string;
}

export interface AlertItem {
  level: string; text: string; time: string;
}

export interface TodoReviewItem {
  id: string; type: string; name: string; conf: number; source: string; reviewer: string;
  /** 原始 content JSON（后端列表接口已透传），用于详情抽屉展开 */
  content?: any;
}

export interface SceneUsageItem {
  scene: string; sceneKey: string; calls: number; tokens: number; cost: number;
}

export interface BillItem {
  id: string; tenant: string; tenantId: string; period: string;
  calls: string; tokens: string; amount: number; status: string;
}

/** 对应 GET /admin/v1/plans → {plan_name, display_name, features_json}
 *  注意：后端不提供价格 / QPS / 配额，页面只能展示特性矩阵 */
export interface PlanFeatures {
  module_3d: boolean;
  module_agent: boolean;
  report_export: boolean;
  priority_support: boolean;
  custom_skin: boolean;
}

export interface PlanItem {
  id: string;            // 套餐 UUID，升级接口 /tenants/{id}/subscription/upgrade 需要
  planName: string;      // trial / standard / professional / enterprise
  name: string;          // 体验版 / 标准版 / ...
  features: PlanFeatures;
}

/** 对应 GET /admin/v1/tenants-extended → data.items[]（套餐升级页用） */
export interface TenantPlanItem {
  id: string;
  name: string;            // display_name
  displayName: string;
  scene: string;           // HEALTH / MED / EDU
  status: string;
  plan: string;            // 当前套餐显示名（可能为空）
  planId: string;          // 当前套餐 UUID（可能为空）
  pendingPlan: string | null;          // 待生效预约的目标套餐
  pendingEffectiveDate: string | null; // 待生效日期（YYYY-MM-DD）
  orgs: number;
  users: number;
  usedCalls: number;
  quotaCalls: number;
  expires: string | null;
  module3d: boolean;
}

/** 对应 GET /admin/v1/subscriptions → data.items[] */
export interface SubscriptionItem {
  id: string;
  tenantId: string;
  planId: string;
  status: string;
  startDate: string;
  endDate: string;
  autoRenew: boolean;
}

/** 对应 GET /admin/v1/tenants/{id}/orgs → data.orgs[] */
export interface OrgItem {
  id: string; name: string; parentId: string | null; userCount: number; status: string;
}

/** 对应 GET /admin/v1/tenants/{id}/users → data.items[] */
export interface TenantUserItem {
  id: string; username: string; displayName: string;
  phone: string; email: string; orgName: string;
  status: string; roles: string[]; createdAt: string;
}

export const planFeatureLabels: { key: keyof PlanFeatures; label: string }[] = [
  { key: "module_3d", label: "3D 经络模块" },
  { key: "module_agent", label: "智能体能力" },
  { key: "report_export", label: "报告导出" },
  { key: "priority_support", label: "优先支持" },
  { key: "custom_skin", label: "定制皮肤" },
];

/** 首页任务卡片 — 由真实待办信号（待审知识 / 逾期账单 / 系统告警）派生，不使用预设文案 */
export interface DeckTask {
  id: string;
  type: string;
  title: string;
  desc: string;
  page: string;
  tone: "red" | "amber" | "blue" | "gold" | "green";
  tag: string;
}

/** 对应 GET /admin/v1/content/words → {id, scene, word, level, replacement, created_at} */
export interface SensitiveWordItem {
  id: string; word: string; scene: string;
  /** 后端 level 字段原样透出 */
  cat: string;
  /** 有 replacement → 替换；否则 → 拦截 */
  action: string;
  replacement: string;
  status: boolean;
}

export interface ServiceItem {
  name: string; status: string; latency: string; uptime: string; ok: boolean;
  is_demo?: boolean;
}

/** 对应 GET /admin/v1/monitor/llm-status → data.providers[]
 *  后端提供的是「模型可用性」而非 token 计量，故按可用性口径展示 */
export interface LlmProviderItem {
  name: string;
  available: boolean;
  failCount: number;
  lastError: string;
  lastCheck: string;
}

export interface AuditLogItem {
  time: string; op: string; action: string; target: string; ip: string;
}

// Dashboard 响应
export interface DashboardData {
  tenants: { total: number; active: number; new_this_month: number };
  users?: { total: number };
  api: { total_calls: number; total_tokens?: number; avg_latency_ms?: number; today_calls: number; call_diff?: number };
  revenue?: { total_cents: number };
  kg?: { pending: number };
  recent_ops?: { time: string; user: string; action: string; target: string }[];
  trend?: { dates: string[]; values: number[] };
  services?: { name: string; key?: string; status: string; latency_ms?: number; uptime?: string }[];
  recent_calls?: { endpoint?: string; method?: string; status_code?: number; latency_ms?: number; timestamp?: string; path?: string }[];
  scene_distribution?: Record<string, number>;
}
