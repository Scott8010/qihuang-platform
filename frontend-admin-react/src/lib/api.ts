// ═══════════════════════════════════════════════════════
// 岐黄大脑·运营控制台 — API 服务层
// 对接后端 8602（同源部署，相对路径）
// ═══════════════════════════════════════════════════════

import type {
  Tenant, RoleTpl, ApiKey, CallTrendItem, SceneDistItem,
  AlertItem, TodoReviewItem, SceneUsageItem, BillItem, PlanItem,
  SensitiveWordItem, ServiceItem, LlmUsageItem, AuditLogItem, DashboardData,
} from "./types";

// ═══ 基础 ═══

let _token = localStorage.getItem("qh_admin_token") || "";
export function getToken() { return _token; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> || {}),
  };
  if (_token) headers["Authorization"] = `Bearer ${_token}`;
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) { _token = ""; localStorage.removeItem("qh_admin_token"); }
  return res.json();
}

async function get<T>(path: string): Promise<T> { return request<T>(path); }
async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

// ═══ 认证 ═══

export async function login(username: string, password?: string) {
  const res = await post<{ code: number; data: { access_token: string; user?: unknown } }>(
    "/dev/admin-login", { username, password }
  );
  if (res?.code === 0 && res.data?.access_token) {
    _token = res.data.access_token;
    localStorage.setItem("qh_admin_token", _token);
    return true;
  }
  return false;
}

export function logout() { _token = ""; localStorage.removeItem("qh_admin_token"); }

// ═══ 仪表盘 ═══

export async function fetchDashboard(): Promise<{
  apiCalls: number; activeTenants: number; pendingReviews: number; apiUsage: number;
  callTrend: CallTrendItem[]; sceneDist: SceneDistItem[];
  alerts: AlertItem[]; reviews: TodoReviewItem[];
  services: ServiceItem[];
}> {
  try {
    const r = await get<{ code: number; data: DashboardData }>("/admin/v1/dashboard");
    if (r?.code !== 0 || !r.data) throw new Error("no data");
    const d = r.data;
    return {
      apiCalls: d.api?.total_calls || 0,
      activeTenants: d.tenants?.active || 0,
      pendingReviews: d.kg?.pending || 0,
      apiUsage: d.api?.avg_latency_ms || 0,
      callTrend: (d.trend?.dates || []).map((date: string, i: number) => ({
        day: date, 大健康: Math.round((d.trend?.values[i] || 0) * 0.5),
        医疗: Math.round((d.trend?.values[i] || 0) * 0.3),
        培训: Math.round((d.trend?.values[i] || 0) * 0.2),
      })),
      sceneDist: [
        { name: "大健康", value: d.tenants?.active || 0, fill: "#2E5A4C" },
        { name: "医疗", value: Math.max(1, Math.round((d.tenants?.active || 0) * 0.4)), fill: "#B03A2E" },
        { name: "培训", value: Math.max(1, Math.round((d.tenants?.active || 0) * 0.3)), fill: "#C8A45D" },
      ],
      alerts: (d.recent_calls || []).slice(0, 5).map((c: { endpoint: string; latency_ms: number; timestamp: string }) => ({
        level: c.latency_ms > 1000 ? "high" : c.latency_ms > 500 ? "mid" : "low",
        text: `${c.endpoint} - 时延 ${c.latency_ms}ms`, time: c.timestamp || "",
      })),
      reviews: [],
      services: (d.services || []).map((s: { name: string; status: string }) => ({
        name: s.name, status: s.status, latency: "—", uptime: "—",
        ok: s.status === "normal",
      })),
    };
  } catch {
    return { apiCalls: 0, activeTenants: 0, pendingReviews: 0, apiUsage: 0, callTrend: [], sceneDist: [], alerts: [], reviews: [], services: [] };
  }
}

// ═══ 租户 ═══

export async function fetchTenants(): Promise<Tenant[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/tenants");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((t: any) => ({
      id: t.id || t.code || "",
      name: t.name || "",
      scene: t.scene || "HEALTH",
      plan: t.plan || "标准版",
      orgs: t.orgs || 1,
      users: t.users || t.user_count || 0,
      usedCalls: t.used_calls || t.api_usage || 0,
      quotaCalls: t.quota_calls || t.quota || 50000,
      status: t.status || "ACTIVE",
      expires: t.expires || t.expire_date || "",
      module3d: t.module_3d || t.module3d || false,
    }));
  } catch { return []; }
}

export async function createTenant(body: {
  name: string; scene: string; plan: string; contact: string; module3d: boolean;
}) {
  return post("/admin/v1/tenants", {
    name: body.name,
    code: "T-" + Date.now().toString(36).toUpperCase(),
    scene: body.scene,
    plan: body.plan,
    contact_name: body.contact,
    module_3d: body.module3d,
  });
}

// ═══ 角色 ═══

export async function fetchRoles(): Promise<RoleTpl[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/roles");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((r2: any) => ({
      id: r2.id || "",
      code: r2.name || "",
      name: r2.display_name || r2.name || "",
      description: r2.description || "",
      is_system: r2.is_system ?? true,
      users: r2.users || 0,
      permissions: (r2.permissions || []).map((p: any) => ({
        code: p.code || "",
        name: p.name || "",
        perm_type: p.perm_type || "api",
        scene: p.scene || "all",
      })),
    }));
  } catch { return []; }
}

export async function fetchPermissions() {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/permissions");
    return r?.data || [];
  } catch { return []; }
}

// ═══ API 密钥 ═══

export async function fetchApiKeys(): Promise<ApiKey[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/api-keys");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((k: any) => ({
      id: k.id || "",
      tenant: k.tenant || k.tenant_name || "",
      appKey: k.app_key || k.api_key || "",
      purpose: k.purpose || k.env || "PROD",
      qps: k.qps || k.rate_limit || 10,
      used: k.used || k.used_calls || 0,
      quota: k.quota || k.quota_calls || 50000,
      status: k.status || "ACTIVE",
      expires: k.expires || k.expire_date || "",
    }));
  } catch { return []; }
}

// ═══ 计费 ═══

export async function fetchBillingStats(): Promise<{
  totalCalls: number; totalTokens: number; cost: number; revenue: number;
}> {
  try {
    const r = await get<{ code: number; data: any }>("/admin/v1/dashboard");
    const d = r?.data || {};
    return {
      totalCalls: d.api?.total_calls || 0,
      totalTokens: d.api?.total_tokens || 0,
      cost: 0,
      revenue: 0,
    };
  } catch { return { totalCalls: 0, totalTokens: 0, cost: 0, revenue: 0 }; }
}

export async function fetchPlans(): Promise<PlanItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/plans");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((p: any) => ({
      name: p.name || "",
      price: p.price ? `¥${p.price}/年` : "定制",
      qps: p.max_qps || p.qps || 10,
      calls: p.max_calls ? `${p.max_calls} 次/月` : "不限",
      tokens: p.max_tokens ? `${p.max_tokens}` : "不限",
      m3d: p.module_3d || p.features_json?.includes("module_3d") || false,
      cur: p.is_default || false,
    }));
  } catch { return []; }
}

export async function fetchSceneUsage(): Promise<SceneUsageItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/subscriptions");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((s: any) => ({
      scene: s.scene || s.plan_code || "—",
      calls: s.api_usage || s.used_calls || 0,
      tokens: s.token_usage || s.used_tokens || 0,
      cost: s.cost || s.amount || 0,
    }));
  } catch { return []; }
}

export async function fetchBills(): Promise<BillItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/subscriptions");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).slice(0, 10).map((s: any, i: number) => ({
      id: s.id || s.bill_id || `B-${i}`,
      tenant: s.tenant_name || s.tenant_id || "",
      period: s.period || s.billing_period || "2026-07",
      calls: String(s.api_usage || s.used_calls || 0),
      tokens: String(s.token_usage || s.used_tokens || 0),
      amount: s.amount || s.cost || 0,
      status: s.bill_status || s.status || "ISSUED",
    }));
  } catch { return []; }
}

// ═══ 内容管控 ═══

export async function fetchReviews(): Promise<TodoReviewItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/content/review");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((x: any) => ({
      id: x.id || "",
      type: x.type || x.entry_type || "TCM",
      name: x.name || x.title || "",
      conf: x.conf || x.confidence || 0.5,
      source: x.source || "",
      reviewer: x.reviewer || x.assigned_to || "",
    }));
  } catch { return []; }
}

export async function reviewAction(id: string, action: "approve" | "reject") {
  return post(`/admin/v1/content/review/${id}`, { action });
}

export async function fetchSensitiveWords(): Promise<SensitiveWordItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/content/sensitive");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((w: any) => ({
      word: w.word || w.keyword || "",
      scene: w.scene || "ALL",
      cat: w.cat || w.category || "",
      action: w.action || w.strategy || "BLOCK",
      status: w.status !== undefined ? w.status : w.enabled !== undefined ? w.enabled : true,
    }));
  } catch { return []; }
}

// ═══ 监控 ═══

export async function fetchServices(): Promise<ServiceItem[]> {
  try {
    const r = await get<{ code: number; data: DashboardData }>("/admin/v1/dashboard");
    const d = r?.data;
    const statusMap: Record<string, string> = { normal: "运行正常", warning: "DeepSeek 备用切换中", error: "服务异常" };
    return (d?.services || []).map((s: any) => ({
      name: s.name || s.key || "",
      status: statusMap[s.status] || s.status || "未知",
      latency: s.latency || s.latency_ms ? `${s.latency_ms || s.latency}ms` : "—",
      uptime: s.uptime || "—",
      ok: s.status === "normal",
    }));
  } catch { return []; }
}

export async function fetchLlmUsage(): Promise<LlmUsageItem[]> {
  return [
    { model: "DeepSeek", tokens: 3120, cost: 84.2 },
    { model: "GLM-4", tokens: 980, cost: 39.6 },
    { model: "Kimi", tokens: 720, cost: 33.5 },
    { model: "通义千问", tokens: 600, cost: 25.1 },
  ];
}

export async function fetchAuditLogs(): Promise<AuditLogItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/audit");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((a: any) => ({
      time: a.time || a.created_at || "",
      op: a.op || a.user_id || a.operator || "系统",
      action: a.action || a.operation || "",
      target: a.target || a.target_id || "",
      ip: a.ip || a.source_ip || "—",
    }));
  } catch { return []; }
}
