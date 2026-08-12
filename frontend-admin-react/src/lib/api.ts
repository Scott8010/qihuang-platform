// ═══════════════════════════════════════════════════════
// 岐黄大脑·运营控制台 — API 服务层
// 对接后端 8602（同源部署，相对路径）
// ═══════════════════════════════════════════════════════

import type {
  Tenant, RoleTpl, ApiKey, CallTrendItem, SceneDistItem,
  AlertItem, TodoReviewItem, BillItem, PlanItem, SubscriptionItem, SceneUsageItem,
  OrgItem, TenantUserItem, PermissionItem, PlatformUser,
  SensitiveWordItem, ServiceItem, LlmProviderItem, AuditLogItem, DashboardData,
} from "./types";

// ═══ 基础 ═══

let _token = localStorage.getItem("qh_admin_token") || "";
export function getToken() { return _token; }

/** 登录成功后保留的基础身份（后端 /admin/v1/login data 字段），供改密等端点使用 */
export interface AdminIdentity {
  user_id: string;
  username: string;
  display_name: string;
  tenant_id: string;
  roles: string[];
  auth_source: string;
}
let _identity: AdminIdentity | null = (() => {
  try { const s = localStorage.getItem("qh_admin_user"); return s ? (JSON.parse(s) as AdminIdentity) : null; }
  catch { return null; }
})();
export function getIdentity(): AdminIdentity | null { return _identity; }
export function getUserId(): string { return _identity?.user_id || ""; }

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

/** 写操作统一返回体：成功与否 + 后端原话 + 数据，页面据此弹提示，不再假装成功 */
export interface MutateResult<T = any> { ok: boolean; msg: string; data?: T }

async function mutate<T = any>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<MutateResult<T>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (_token) headers["Authorization"] = `Bearer ${_token}`;
  try {
    const res = await fetch(path, {
      method, headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) { _token = ""; localStorage.removeItem("qh_admin_token"); }
    let j: any = {};
    try { j = await res.json(); } catch { /* 空响应体 */ }
    if (res.ok && (j?.code === 0 || j?.code === undefined)) {
      return { ok: true, msg: j?.msg || "操作成功", data: j?.data };
    }
    const msg = j?.detail?.msg || j?.detail?.message || j?.msg
      || (typeof j?.detail === "string" ? j.detail : "") || `请求失败（HTTP ${res.status}）`;
    return { ok: false, msg };
  } catch (e: any) {
    return { ok: false, msg: e?.message || "网络异常" };
  }
}

// ═══ 认证 ═══

export async function login(username: string, password?: string) {
  const res = await post<{
    code: number;
    data: {
      access_token: string; user_id: string; username: string;
      display_name: string; tenant_id: string; roles: string[]; auth_source: string;
    };
  }>("/admin/v1/login", { username, password });
  if (res?.code === 0 && res.data?.access_token) {
    _token = res.data.access_token;
    localStorage.setItem("qh_admin_token", _token);
    _identity = {
      user_id: res.data.user_id,
      username: res.data.username,
      display_name: res.data.display_name || res.data.username,
      tenant_id: res.data.tenant_id,
      roles: res.data.roles || [],
      auth_source: res.data.auth_source,
    };
    localStorage.setItem("qh_admin_user", JSON.stringify(_identity));
    return true;
  }
  return false;
}

export function logout() {
  _token = "";
  localStorage.removeItem("qh_admin_token");
  localStorage.removeItem("qh_admin_user");
  _identity = null;
}

/**
 * POST /admin/v1/me/change-password — 当前登录用户自助改密（后端验原密码）。
 * 返回 { ok, msg }，页面据此弹提示。
 */
export async function changePassword(old_password: string, new_password: string): Promise<{ ok: boolean; msg: string }> {
  const r = await mutate<{ user_id: string; changed: boolean }>(
    "POST", "/admin/v1/me/change-password", { old_password, new_password }
  );
  return { ok: r.ok, msg: r.msg };
}

// ═══ 仪表盘 ═══

export async function fetchDashboard(): Promise<{
  totalTenants: number; activeTenants: number; totalUsers: number;
  apiCalls: number; todayCalls: number; apiUsage: number; revenueCents: number;
  callTrend: CallTrendItem[]; sceneDist: SceneDistItem[];
  alerts: AlertItem[]; reviews: TodoReviewItem[];
  services: ServiceItem[]; recentOps: { time: string; user: string; action: string; target: string }[];
}> {
  try {
    const r = await get<{ code: number; data: DashboardData }>("/admin/v1/dashboard");
    if (r?.code !== 0 || !r.data) throw new Error("no data");
    const d = r.data;
    const totalTenants = d.tenants?.total || 0;
    const activeTenants = d.tenants?.active || 0;
    const totalUsers = d.users?.total || 0;
    const totalCalls = d.api?.total_calls || 0;
    const todayCalls = d.api?.today_calls || 0;
    const revenueCents = d.revenue?.total_cents || 0;

    // 场景分布：按真实租户 scene 聚合；若后端未返回则按 active 租户数拆分
    const sceneCounts: Record<string, number> = {};
    if (d.scene_distribution && typeof d.scene_distribution === "object") {
      Object.entries(d.scene_distribution).forEach(([k, v]) => { sceneCounts[k] = Number(v) || 0; });
    }
    const sceneDist: SceneDistItem[] = [
      { name: "大健康", value: sceneCounts.HEALTH || sceneCounts.health || Math.max(0, Math.round(activeTenants * 0.5)), fill: "#2E5A4C" },
      { name: "医疗", value: sceneCounts.MED || sceneCounts.med || Math.max(0, Math.round(activeTenants * 0.3)), fill: "#B03A2E" },
      { name: "培训", value: sceneCounts.EDU || sceneCounts.edu || Math.max(0, Math.round(activeTenants * 0.2)), fill: "#C8A45D" },
    ].filter((s) => s.value > 0);

    // 告警：优先用 recent_calls， fallback 到 recent_ops
    const alerts: AlertItem[] = [];
    if (d.recent_calls && Array.isArray(d.recent_calls)) {
      d.recent_calls.slice(0, 5).forEach((c: any) => {
        const latency = c.latency_ms || c.latency || 0;
        alerts.push({
          level: latency > 1000 ? "high" : latency > 500 ? "mid" : "low",
          text: `${c.endpoint || c.path || ""} - 时延 ${latency}ms`,
          time: c.timestamp || "",
        });
      });
    }
    if (alerts.length === 0 && d.recent_ops) {
      d.recent_ops.slice(0, 5).forEach((op: any) => {
        alerts.push({ level: "low", text: `${op.user || "系统"} ${op.action} ${op.target || ""}`, time: op.time || "" });
      });
    }

    return {
      totalTenants, activeTenants, totalUsers,
      apiCalls: totalCalls, todayCalls,
      apiUsage: d.api?.avg_latency_ms || 0,
      revenueCents,
      callTrend: (d.trend?.dates || []).map((date: string, i: number) => ({
        day: date,
        大健康: Math.round((d.trend?.values[i] || 0) * 0.5),
        医疗: Math.round((d.trend?.values[i] || 0) * 0.3),
        培训: Math.round((d.trend?.values[i] || 0) * 0.2),
      })),
      sceneDist,
      alerts,
      reviews: [],
      services: (d.services || []).map((s: any) => ({
        name: s.name, status: s.status === "normal" ? "运行正常" : s.status === "warning" ? "DeepSeek 备用切换中" : s.status || "未知",
        latency: s.latency_ms ? `${s.latency_ms}ms` : "—",
        uptime: s.uptime || "—",
        ok: s.status === "normal",
      })),
      recentOps: (d.recent_ops || []).slice(0, 8),
    };
  } catch (e) {
    console.error("fetchDashboard error", e);
    return { totalTenants: 0, activeTenants: 0, totalUsers: 0, apiCalls: 0, todayCalls: 0, apiUsage: 0, revenueCents: 0, callTrend: [], sceneDist: [], alerts: [], reviews: [], services: [], recentOps: [] };
  }
}

// ═══ 租户 ═══

export async function fetchTenants(): Promise<Tenant[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/tenants");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((t: any) => {
      const sceneUpper = (t.scene || "HEALTH").toUpperCase();
      const planName = t.plan_name || t.plan || "体验版";
      const statusUpper = (t.status || "active").toUpperCase();
      return {
        id: t.id || t.code || "",
        name: t.display_name || t.name || "",
        scene: sceneUpper === "MED" ? "MED" : sceneUpper === "EDU" ? "EDU" : "HEALTH",
        plan: planName,
        orgs: t.orgs || t.org_count || 1,
        users: t.users || t.user_count || 0,
        usedCalls: t.used_calls || t.api_usage || 0,
        // 后端未下发配额时为 0 → 页面显示「不限」，不假造默认额度
        quotaCalls: t.quota_calls ?? t.quota ?? 0,
        status: ["TRIAL", "ACTIVE", "READONLY", "EXPIRED", "CLOSED"].includes(statusUpper) ? statusUpper : "ACTIVE",
        expires: t.expires || t.expire_date || t.expired_at || "—",
        module3d: t.module_3d || t.module3d || false,
      };
    });
  } catch (e) { console.error("fetchTenants error", e); return []; }
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

export async function fetchPermissions(): Promise<PermissionItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/permissions");
    return (r?.data || []).map((p: any) => ({
      code: p.code || "",
      name: p.name || p.code || "",
      perm_type: p.perm_type || "api",
      scene: p.scene || "all",
    }));
  } catch { return []; }
}

/** PUT /admin/v1/roles/{id}/permissions — 整体替换角色权限（勾选即最终态） */
export async function updateRolePermissions(roleId: string, permCodes: string[]) {
  return mutate<{ role_id: string; name: string; perm_count: number }>(
    "PUT", `/admin/v1/roles/${roleId}/permissions`, { perm_codes: permCodes },
  );
}

/** POST /admin/v1/roles — 新建自定义角色（is_system=false，可删可改） */
export async function createRole(body: {
  name: string; display_name?: string; description?: string; perm_codes?: string[];
}) {
  return mutate<{ id: string; name: string }>("POST", "/admin/v1/roles", {
    name: body.name,
    display_name: body.display_name || body.name,
    description: body.description || "",
    perm_codes: body.perm_codes || [],
  });
}

/** DELETE /admin/v1/roles/{id} — 系统预置角色后端会拒绝 */
export async function deleteRole(roleId: string) {
  return mutate("DELETE", `/admin/v1/roles/${roleId}`);
}

/** POST /admin/v1/roles/assign — 给用户加一个角色 */
export async function assignRole(userId: string, roleName: string) {
  return mutate("POST", "/admin/v1/roles/assign", { user_id: userId, role_name: roleName });
}

/** DELETE /admin/v1/roles/revoke — 摘掉用户的某个角色 */
export async function revokeRole(userId: string, roleName: string) {
  return mutate("DELETE", "/admin/v1/roles/revoke", { user_id: userId, role_name: roleName });
}

// ═══ 用户管理（平台级） ═══

function mapUser(u: any): PlatformUser {
  return {
    id: u.id || "",
    username: u.username || "",
    displayName: u.display_name || u.username || "",
    phone: u.phone || "",
    email: u.email || "",
    status: u.status || "active",
    orgId: u.org_id || "",
    tenantId: u.tenant_id || "",
    createdAt: u.created_at || "",
    roles: Array.isArray(u.roles)
      ? u.roles.map((r: any) => ({
          id: r.id || "", name: r.name || "", displayName: r.display_name || r.name || "",
        }))
      : [],
  };
}

/** GET /admin/v1/users — 当前租户下全部用户（含角色） */
export async function fetchUsers(): Promise<PlatformUser[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/users");
    if (r?.code !== 0 || !Array.isArray(r.data)) return [];
    return r.data.map(mapUser);
  } catch { return []; }
}

/** GET /admin/v1/users/{id} — 用户详情（含完整角色与机构） */
export async function fetchUserDetail(userId: string): Promise<PlatformUser | null> {
  try {
    const r = await get<{ code: number; data: any }>(`/admin/v1/users/${userId}`);
    if (r?.code !== 0 || !r.data) return null;
    return mapUser(r.data);
  } catch { return null; }
}

/** POST /admin/v1/users — 新建用户（后端会自动挂 health_user 默认角色） */
export async function createUser(body: {
  username: string; password: string;
  display_name?: string; phone?: string; email?: string;
}) {
  return mutate<{ id: string; username: string }>("POST", "/admin/v1/users", body);
}

/** PATCH /admin/v1/users/{id} — 改资料或改状态（active / disabled） */
export async function updateUser(userId: string, body: {
  display_name?: string; phone?: string; email?: string; org_id?: string; status?: string;
}) {
  return mutate("PATCH", `/admin/v1/users/${userId}`, body);
}

/** DELETE /admin/v1/users/{id} — 删除用户并清理角色关联 */
export async function deleteUser(userId: string) {
  return mutate("DELETE", `/admin/v1/users/${userId}`);
}

/** POST /admin/v1/users/{id}/reset-password — 不传密码则后端随机生成并回显 */
export async function resetUserPassword(userId: string, password?: string) {
  return mutate<{ user_id: string; new_password: string }>(
    "POST", `/admin/v1/users/${userId}/reset-password`,
    { password: password || null },
  );
}

// ═══ API 密钥 ═══

export async function fetchApiKeys(): Promise<ApiKey[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/api-keys/");
    const items = r?.data?.items || [];
    return items.map((k: any) => ({
      id: k.id || k.app_key || "",
      tenant: k.tenant_name || k.tenant_id || "",
      appKey: k.app_key || k.api_key || "",
      purpose: k.purpose || k.env || "PROD",
      qps: k.qps ?? k.rate_limit ?? 0,
      used: k.used_calls ?? k.used ?? 0,
      // 后端无配额字段 → null，页面显示「不限」，不假造 50000
      quota: k.quota_calls ?? k.quota ?? null,
      status: (k.status || "ACTIVE").toUpperCase(),
      expires: k.expire_date || k.expires_at || k.expires || "",
    }));
  } catch { return []; }
}

export async function createApiKey(tenantId: string, plan = 'standard'): Promise<MutateResult> {
  return mutate('POST', '/admin/v1/api-keys/', { tenant_id: tenantId, plan });
}

export async function rotateApiKey(keyId: string): Promise<MutateResult> {
  return mutate('POST', `/admin/v1/api-keys/${encodeURIComponent(keyId)}/rotate`);
}

export async function revokeApiKey(keyId: string): Promise<MutateResult> {
  return mutate('DELETE', `/admin/v1/api-keys/${encodeURIComponent(keyId)}`);
}

// ═══ 计费 ═══

export async function fetchBillingStats(): Promise<{
  totalCalls: number; totalTokens: number; cost: number; revenue: number;
}> {
  try {
    const r = await get<{ code: number; data: any }>("/admin/v1/billing/usage");
    const d = r?.data || {};
    return {
      totalCalls: d.total_calls || 0,
      totalTokens: d.total_tokens || 0,
      cost: Math.round((d.total_cost_cents || 0) / 100),
      revenue: 0,
    };
  } catch { return { totalCalls: 0, totalTokens: 0, cost: 0, revenue: 0 }; }
}

export async function fetchPlans(): Promise<PlanItem[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/plans");
    if (r?.code !== 0 || !Array.isArray(r.data)) return [];
    return r.data.map((p: any) => {
      const f = p.features_json || {};
      return {
        planName: p.plan_name || "",
        name: p.display_name || p.plan_name || "",
        features: {
          module_3d: !!f.module_3d,
          module_agent: !!f.module_agent,
          report_export: !!f.report_export,
          priority_support: !!f.priority_support,
          custom_skin: !!f.custom_skin,
        },
      };
    });
  } catch { return []; }
}

/** GET /admin/v1/subscriptions — 真实返回的是订阅记录，不是分场景用量 */
export async function fetchSubscriptions(): Promise<SubscriptionItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/subscriptions");
    const items = r?.data?.items || [];
    return items.map((s: any) => ({
      id: s.id || "",
      tenantId: s.tenant_id || "",
      planId: s.plan_id || "",
      status: s.status || "",
      startDate: s.start_date || "",
      endDate: s.end_date || "",
      autoRenew: !!s.auto_renew,
    }));
  } catch { return []; }
}

/** GET /admin/v1/tenants/{id}/orgs */
export async function fetchTenantOrgs(tenantId: string): Promise<OrgItem[]> {
  if (!tenantId) return [];
  try {
    const r = await get<{ code: number; data: { orgs?: any[] } }>(`/admin/v1/tenants/${tenantId}/orgs`);
    const orgs = r?.data?.orgs || [];
    return orgs.map((o: any) => ({
      id: o.id || "",
      name: o.name || o.display_name || "",
      parentId: o.parent_id ?? null,
      userCount: o.user_count ?? 0,
      status: o.status || "active",
    }));
  } catch { return []; }
}

/** GET /admin/v1/tenants/{id}/users */
export async function fetchTenantUsers(tenantId: string): Promise<TenantUserItem[]> {
  if (!tenantId) return [];
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>(`/admin/v1/tenants/${tenantId}/users`);
    const items = r?.data?.items || [];
    return items.map((u: any) => ({
      id: u.id || "",
      username: u.username || "",
      displayName: u.display_name || u.username || "—",
      phone: u.phone || "",
      email: u.email || "",
      orgName: u.org_name || "",
      status: u.status || "active",
      roles: Array.isArray(u.roles) ? u.roles.map((x: any) => x.display_name || x.name || "") : [],
      createdAt: u.created_at || "",
    }));
  } catch { return []; }
}

export async function fetchBills(): Promise<BillItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/billing/bills");
    const items = r?.data?.items || [];
    return items.slice(0, 200).map((s: any) => ({
      id: s.id || `B-${s.period}`,
      tenant: s.extra?.plan_name || s.tenant_id || "",
      tenantId: s.tenant_id || "",
      period: s.period || "",
      calls: String(s.total_calls || 0),
      tokens: String(s.total_tokens || 0),
      amount: Math.round((s.amount_cents || 0) / 100),
      status: s.status || "DRAFT",
    }));
  } catch { return []; }
}

// ═══ 内容管控 ═══

export async function fetchReviews(): Promise<TodoReviewItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/kg/review/pending");
    const items = r?.data?.items || [];
    return items.map((x: any) => ({
      id: x.id || "",
      type: x.entry_type || x.type || "知识条目",
      name: x.content || x.name || x.title || "",
      conf: x.confidence ?? x.conf ?? 0,
      source: x.source || "",
      reviewer: x.reviewer_role || x.reviewer || "",
    }));
  } catch { return []; }
}

export async function reviewAction(id: string, action: "approve" | "reject") {
  return post(`/admin/v1/kg/review/action`, { review_id: id, action, note: "" });
}

export async function fetchSensitiveWords(): Promise<SensitiveWordItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/content/words");
    const items = r?.data?.items || [];
    return items.map((w: any) => ({
      id: w.id || w.word || "",
      word: w.word || "",
      scene: w.scene || "ALL",
      cat: w.level || w.category || "—",
      replacement: w.replacement || "",
      action: w.replacement ? "替换" : "拦截",
      status: w.enabled !== undefined ? !!w.enabled : true,
    }));
  } catch { return []; }
}

// ═══ 监控 ═══

export async function fetchServices(): Promise<ServiceItem[]> {
  try {
    const r = await get<{ code: number; data: { services?: any[] } }>("/admin/v1/monitor/services");
    const services = r?.data?.services || [];
    return services.map((s: any) => ({
      name: s.name || "",
      status: s.status || "未知",
      latency: s.latency || "—",
      uptime: s.uptime || "—",
      ok: s.ok !== undefined ? s.ok : true,
    }));
  } catch { return []; }
}

/** GET /admin/v1/monitor/llm-status — 后端口径是「模型可用性」，不是 token 计量 */
export async function fetchLlmProviders(): Promise<LlmProviderItem[]> {
  try {
    const r = await get<{ code: number; data: { providers?: any[] } }>("/admin/v1/monitor/llm-status");
    const list = r?.data?.providers || [];
    return list.map((m: any) => ({
      name: m.name || "",
      available: !!m.available,
      failCount: m.fail_count ?? 0,
      lastError: m.last_error || "",
      lastCheck: m.last_check || "",
    }));
  } catch { return []; }
}

/** GET /admin/v1/billing/scene-usage — 真实分场景计量 */
export async function fetchSceneUsage(): Promise<SceneUsageItem[]> {
  try {
    const r = await get<{ code: number; data: { scene_usage?: any[] } }>("/admin/v1/billing/scene-usage");
    const list = r?.data?.scene_usage || [];
    return list.map((s: any) => ({
      scene: s.scene || s.scene_key || "",
      sceneKey: s.scene_key || s.scene || "",
      calls: s.calls ?? 0,
      tokens: s.tokens ?? 0,
      cost: s.cost ?? 0,
    }));
  } catch { return []; }
}

export async function fetchAuditLogs(): Promise<AuditLogItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/audit-logs");
    const items = r?.data?.items || [];
    return items.map((a: any) => ({
      time: a.created_at || a.time || "",
      op: a.user_id || a.operator || a.op || "系统",
      action: a.action || a.operation || "",
      target: a.target_id || a.target || "",
      ip: a.source_ip || a.ip || "—",
    }));
  } catch { return []; }
}
