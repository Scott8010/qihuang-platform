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
  plan: string; orgs: number; users: number;
  usedCalls: number; quotaCalls: number; status: string; expires: string; module3d: boolean;
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

export interface ApiKey {
  id: string; tenant: string; appKey: string; purpose: string;
  qps: number; used: number; quota: number; status: string; expires: string;
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
}

export interface SceneUsageItem {
  scene: string; calls: number; tokens: number; cost: number;
}

export interface BillItem {
  id: string; tenant: string; period: string; calls: string; tokens: string; amount: number; status: string;
}

export interface PlanItem {
  name: string; price: string; qps: number; calls: string; tokens: string; m3d: boolean; cur: boolean;
}

export interface SensitiveWordItem {
  word: string; scene: string; cat: string; action: string; status: boolean;
}

export interface ServiceItem {
  name: string; status: string; latency: string; uptime: string; ok: boolean;
}

export interface LlmUsageItem {
  model: string; tokens: number; cost: number;
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
