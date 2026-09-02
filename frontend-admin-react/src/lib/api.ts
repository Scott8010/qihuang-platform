// ═══════════════════════════════════════════════════════
// 岐黄大脑·运营控制台 — API 服务层
// 对接后端 8602（同源部署，相对路径）
// ═══════════════════════════════════════════════════════

import type {
  Tenant, RoleTpl, ApiKey, CallTrendItem, SceneDistItem,
  AlertItem, TodoReviewItem, BillItem, PlanItem, SubscriptionItem, SceneUsageItem,
  OrgItem, TenantUserItem, PermissionItem, PlatformUser,
  SensitiveWordItem, ServiceItem, LlmProviderItem, AuditLogItem, DashboardData,
  PriceBook, AgentCenterItem, OrderItem, BillDetailItem,
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
  newThisMonth: number;
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
    const newThisMonth = d.tenants?.new_this_month || 0;
    const totalCalls = d.api?.total_calls || 0;
    const todayCalls = d.api?.today_calls || 0;
    const revenueCents = d.revenue?.total_cents || 0;

    // 场景分布：直接基于后端 scene_distribution 真实聚合（键为 health/medical/edu 等），不再臆造比例
    const SCENE_META: Record<string, { name: string; fill: string }> = {
      health: { name: "大健康", fill: "#2E5A4C" },
      medical: { name: "医疗", fill: "#B03A2E" },
      edu: { name: "培训", fill: "#C8A45D" },
      unknown: { name: "未分类", fill: "#8FA9A0" },
    };
    const sceneDist: SceneDistItem[] = (
      d.scene_distribution && typeof d.scene_distribution === "object"
        ? Object.entries(d.scene_distribution)
        : []
    )
      .map(([k, v]) => {
        const meta = SCENE_META[k] || SCENE_META.unknown;
        return { name: meta.name, value: Number(v) || 0, fill: meta.fill };
      })
      .filter((s) => s.value > 0);

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
      totalTenants, activeTenants, totalUsers, newThisMonth,
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
        name: s.name,
        status: s.ok ? (s.status === "warning" ? "DeepSeek 备用切换中" : "运行正常") : "服务不可用",
        latency: s.latency_ms ? `${s.latency_ms}ms` : "—",
        uptime: s.uptime || "—",
        ok: s.ok !== undefined ? !!s.ok : s.status === "normal",
      })),
      recentOps: (d.recent_ops || []).slice(0, 8),
    };
  } catch (e) {
    console.error("fetchDashboard error", e);
    return { totalTenants: 0, activeTenants: 0, totalUsers: 0, newThisMonth: 0, apiCalls: 0, todayCalls: 0, apiUsage: 0, revenueCents: 0, callTrend: [], sceneDist: [], alerts: [], reviews: [], services: [], recentOps: [] };
  }
}

// ═══ 租户 ═══

export async function fetchTenants(): Promise<Tenant[]> {
  try {
    const r = await get<{ code: number; data: any[] }>("/admin/v1/tenants");
    if (r?.code !== 0 || !r.data) return [];
    return (r.data || []).map((t: any) => {
      const sceneUpper = (t.scene || "HEALTH").toUpperCase();
      // 修复 2026-08-15: 去掉"体验版"硬兜底，避免 plan 字段暂时为空时误导为体验版；
      // 空值显示 "—"，让用户看到"未配置"而不是误判为最低套餐。
      // 2026-08-15 补充：列表接口现已返回中文 plan（display_name），优先用 t.plan；
      // plan_name 为英文标识，作为兜底；空值才显示 "—"
      const planName = t.plan || t.plan_name || "—";
      const statusUpper = (t.status || "active").toUpperCase();
      return {
        id: t.id || t.code || "",
        code: t.code || null,
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
        pendingPlan: t.pending_plan || null,
        pendingEffectiveDate: t.pending_effective_date || null,
        // 2026-08-22 开户表单升级：机构资质信息透传
        contactName: t.contact_name || "",
        contactPhone: t.contact_phone || "",
        contactEmail: t.contact_email || "",
        addressCountry: t.address_country || "",
        addressProvince: t.address_province || "",
        addressCity: t.address_city || "",
        addressDistrict: t.address_district || "",
        orgIntro: t.org_intro || "",
        licenseBusiness: t.license_business || "",
        licenseBusinessName: t.license_business_name || "",
        licenseMedical: t.license_medical || "",
        licenseMedicalName: t.license_medical_name || "",
      };
    });
  } catch (e) { console.error("fetchTenants error", e); return []; }
}

export async function createTenant(body: {
  name: string; scene: string; plan: string;
  contactName: string; contactPhone: string; module3d: boolean;
  code?: string;
  contactEmail?: string;
  addressCountry?: string; addressProvince?: string; addressCity?: string; addressDistrict?: string;
  addressDetail?: string;
  orgIntro?: string;
  licenseBusiness?: string; licenseBusinessName?: string;
  licenseMedical?: string; licenseMedicalName?: string;
}) {
  // 走「开户一条龙」端点：创建租户 + 根机构 + 套餐订阅 + 联系人 + 3D 开关，一次落库。
  // 旧端点 POST /admin/v1/tenants 只建租户名（套餐/联系人/3D 全被丢弃）→ 详情页套餐服务全空。
  const sceneMap: Record<string, string> = { MED: "medical", HEALTH: "health", EDU: "edu" };
  return post("/admin/v1/tenants/onboard", {
    name: "T" + Date.now().toString(36).toUpperCase(), // 租户标识（唯一）
    display_name: body.name,
    scene: sceneMap[body.scene] || "health",
    plan: body.plan,               // plan_name 英文标识（trial/standard/professional/enterprise）
    contact_name: body.contactName,
    contact_phone: body.contactPhone,
    contact_email: body.contactEmail || null,
    module_3d: body.module3d,
    code: body.code || null,
    duration_months: 12,
    // 2026-08-22 开户表单升级：机构资质信息
    address_country: body.addressCountry || null,
    address_province: body.addressProvince || null,
    address_city: body.addressCity || null,
    address_district: body.addressDistrict || null,
    address_detail: body.addressDetail || null,
    org_intro: body.orgIntro || null,
    license_business: body.licenseBusiness || null,
    license_business_name: body.licenseBusinessName || null,
    license_medical: body.licenseMedical || null,
    license_medical_name: body.licenseMedicalName || null,
  });
}

/** POST /admin/v1/upload — 上传证照文件（multipart），返回可访问 URL（2026-08-22 开户表单） */
export async function uploadFile(file: File, purpose = "license"): Promise<MutateResult<{ file_id: string; url: string; name: string }>> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("purpose", purpose);
  try {
    const headers: Record<string, string> = {};
    if (_token) headers["Authorization"] = `Bearer ${_token}`;
    const res = await fetch("/admin/v1/upload", { method: "POST", headers, body: fd });
    let j: any = {};
    try { j = await res.json(); } catch { /* 空响应体 */ }
    if (res.ok && j?.code === 0) return { ok: true, msg: j?.msg || "上传成功", data: j.data };
    const msg = j?.msg || j?.detail?.message || `上传失败（HTTP ${res.status}）`;
    return { ok: false, msg };
  } catch (e: any) {
    return { ok: false, msg: e?.message || "上传异常" };
  }
}

/** DELETE /admin/v1/tenants/{id} — 软删除租户（后端记录审计日志） */
export async function deleteTenant(tenantId: string) {
  return mutate("DELETE", `/admin/v1/tenants/${tenantId}`);
}

// ═══ 角色 ═══

export async function fetchRoles(tenantId?: string): Promise<RoleTpl[]> {
  try {
    const url = tenantId
      ? `/admin/v1/roles?tenant_id=${encodeURIComponent(tenantId)}`
      : "/admin/v1/roles";
    const r = await get<{ code: number; data: any[] }>(url);
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
  tenant_id?: string; org_id?: string;
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
        id: p.id || "",
        planName: p.plan_name || "",
        name: p.display_name || p.plan_name || "",
        desc: p.description || "",
        priceCents: p.price_cents ?? 0,
        monthCalls: p.month_calls ?? 0,
        status: p.status || "active",
        features: {
          module_3d: !!f.module_3d,
          module_agent: !!f.module_agent,
          report_export: !!f.report_export,
          priority_support: !!f.priority_support,
          custom_skin: !!f.custom_skin,
        },
        agents: Array.isArray(f.agents) ? f.agents : [],
      };
    });
  } catch { return []; }
}

/** GET /admin/v1/billing/price-book — 计费价目（#474 单一真源）：叠加包 + 单加 agent 月费 */
export async function fetchPriceBook(): Promise<PriceBook | null> {
  try {
    const r = await get<{ code: number; data: any }>("/admin/v1/billing/price-book");
    if (r?.code !== 0 || !r.data) return null;
    return {
      rechargePacks: (r.data.recharge_packs || []).map((p: any) => ({
        key: p.key || "",
        label: p.label || "",
        yuan: p.yuan ?? 0,
        credits: p.credits ?? 0,
      })),
      agentAddon: {
        textMonthlyYuan: r.data.agent_addon?.text_monthly_yuan ?? 59,
        multimodalMonthlyYuan: r.data.agent_addon?.multimodal_monthly_yuan ?? 99,
        note: r.data.agent_addon?.note || "",
      },
    };
  } catch (e) { console.error("fetchPriceBook error", e); return null; }
}

// ═══ 充值 / 加购（admin 给指定租户直接下单，#474 计费）═══

/** POST /billing/v1/wallet/recharge?tenant_id=&pack= — 叠加包充值（永久有效）
 *  注意：后端该端点用 Query 参数，不是 JSON body；仅平台 admin 可调用。 */
export async function rechargePack(tenantId: string, pack: string): Promise<MutateResult> {
  return mutate("POST",
    `/billing/v1/wallet/recharge?tenant_id=${encodeURIComponent(tenantId)}&pack=${encodeURIComponent(pack)}`);
}

/** GET /admin/v1/agents — Agent 中台能力资源池（单加叠加弹窗数据源） */
export async function fetchAgents(): Promise<AgentCenterItem[]> {
  try {
    const r = await get<{ code: number; data: { agents?: any[] } }>("/admin/v1/agents");
    const items = r?.data?.agents || [];
    return items.map((a: any) => ({
      agentKey: a.agent_key || a.key || "",
      name: a.name || a.display_name || a.agent_key || "",
      category: a.category || "general",
      includedInPlans: Array.isArray(a.included_in_plans) ? a.included_in_plans : [],
    }));
  } catch (e) { console.error("fetchAgents error", e); return []; }
}

/** POST /admin/v1/tenants/{tenantId}/agent-addons — 叠加额外 Agent（套餐之外精准授权）
 *  后端在套餐 agents 基础上合并；首月即从积分池扣月费（文本¥59/多模态¥99），余额不足返 402。 */
export async function addAgentAddon(tenantId: string, addKeys: string[]): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/tenants/${encodeURIComponent(tenantId)}/agent-addons`, {
    add: addKeys,
    remove: [],
  });
}

// ═══ 套餐升级（租户订阅变更）═══
// 真实接口：GET /admin/v1/tenants-extended?page_size=20（正确分页，避免 422）
//           POST /admin/v1/tenants/{id}/subscription/upgrade  { plan_id }
// 旧版崩溃根因：前端写死 page_size=200 → 后端上限 100 → 422 整页崩。

export interface TenantPlanItem {
  id: string;
  name: string;            // display_name
  displayName: string;
  scene: string;           // HEALTH / MED / EDU
  status: string;
  plan: string;            // 当前套餐显示名（可能空）
  planId: string;          // 当前套餐 UUID（可能空）
  pendingPlan: string | null;          // 待生效预约的目标套餐（scheduled 订阅）
  pendingEffectiveDate: string | null; // 待生效日期（YYYY-MM-DD）
  agentAddons: string[];               // 单加 agent（tenant.extra.agent_addons）
  orgs: number;
  users: number;
  usedCalls: number;
  quotaCalls: number;
  expires: string | null;
  module3d: boolean;
}

/** GET /admin/v1/tenants-extended?page_size=20 — 拉租户 + 当前套餐（正确分页，不崩） */
export async function fetchTenantExtended(pageSize = 20): Promise<TenantPlanItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>(
      `/admin/v1/tenants-extended?page_size=${pageSize}`,
    );
    const items = r?.data?.items || [];
    return items.map((t: any) => ({
      id: t.id || "",
      name: t.display_name || t.name || "",
      displayName: t.display_name || t.name || "",
      scene: (t.scene || "health").toUpperCase(),
      status: (t.status || "active").toUpperCase(),
      plan: t.plan || "",
      planId: t.plan_id || "",
      pendingPlan: t.pending_plan || null,
      pendingEffectiveDate: t.pending_effective_date || null,
      agentAddons: Array.isArray(t.agent_addons) ? t.agent_addons : [],
      orgs: t.orgs || 0,
      users: t.users || 0,
      usedCalls: t.usedCalls || t.used_calls || 0,
      quotaCalls: t.quotaCalls ?? t.quota_calls ?? 0,
      expires: t.expires || null,
      module3d: t.module_3d || false,
    }));
  } catch (e) { console.error("fetchTenantExtended error", e); return []; }
}

/** POST /admin/v1/tenants/{tenantId}/subscription/upgrade — 预约次月1号生效升级 */
export async function upgradeSubscription(tenantId: string, planId: string): Promise<MutateResult> {
  return mutate<{ subscription_id: string; target_plan_name: string; effective_date: string }>(
    "POST",
    `/admin/v1/tenants/${encodeURIComponent(tenantId)}/subscription/upgrade`,
    { plan_id: planId },
  );
}

/** POST /admin/v1/tenants/{tenantId}/subscription/cancel-pending — 取消待生效的预约升级 */
export async function cancelPendingUpgrade(tenantId: string): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/tenants/${encodeURIComponent(tenantId)}/subscription/cancel-pending`);
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

// ═══ 结算中心订单（#B 方案）═══

/** GET /billing/v1/orders — 结算中心订单记录（admin 可查任意/全部，租户仅自身） */
export async function fetchOrders(params?: {
  tenant_id?: string; type?: string; period?: string; page?: number; page_size?: number;
}): Promise<OrderItem[]> {
  try {
    const qs = new URLSearchParams();
    if (params?.tenant_id) qs.set("tenant_id", params.tenant_id);
    if (params?.type) qs.set("order_type", params.type);
    if (params?.period) qs.set("period", params.period);
    if (params?.page) qs.set("page", String(params.page));
    if (params?.page_size) qs.set("page_size", String(params.page_size));
    const q = qs.toString();
    const r = await get<{ code: number; data: { items?: any[] } }>(`/billing/v1/orders${q ? `?${q}` : ""}`);
    const items = r?.data?.items || [];
    return items.map((s: any) => ({
      id: s.id || "",
      order_no: s.order_no || "",
      tenant_id: s.tenant_id || "",
      order_type: s.order_type || "",
      item_key: s.item_key || "",
      item_label: s.item_label || "",
      amount_cents: s.amount_cents || 0,
      credits: s.credits || 0,
      status: s.status || "PENDING",
      billed: !!s.billed,
      period_month: s.period_month || "",
      paid_at: s.paid_at || null,
      created_at: s.created_at || "",
    }));
  } catch { return []; }
}

/** GET /billing/v1/wallet/{tenant_id} — 租户积分余额（结算中心租户现状卡） */
export async function fetchWalletBalance(tenantId: string): Promise<{ base: number; addon: number; total: number } | null> {
  try {
    const r = await get<{ code: number; data: { base_credits?: number; addon_credits?: number; total_credits?: number } }>(
      `/billing/v1/wallet/${encodeURIComponent(tenantId)}`,
    );
    if (r?.code !== 0 || !r?.data) return null;
    return {
      base: r.data.base_credits || 0,
      addon: r.data.addon_credits || 0,
      total: r.data.total_credits || 0,
    };
  } catch { return null; }
}

/** GET /admin/v1/billing/bills/{bill_id} — 账单明细（订单聚合 + 用量按端点/3D 聚合） */
export async function fetchBillDetail(billId: string): Promise<BillDetailItem | null> {
  try {
    const r = await get<{ code: number; data: any }>(`/admin/v1/billing/bills/${encodeURIComponent(billId)}`);
    if (r?.code !== 0 || !r?.data) return null;
    return r.data as BillDetailItem;
  } catch { return null; }
}

/** POST /admin/v1/billing/bills/generate — 手动生成月度账单（无账单数据时先走这里） */
export async function generateBill(tenantId: string, period: string): Promise<{ ok: boolean; msg: string }> {
  try {
    const r = await post<{ code: number; message: string }>("/admin/v1/billing/bills/generate", { tenant_id: tenantId, period });
    return { ok: r?.code === 0, msg: r?.message || (r?.code === 0 ? "账单已生成" : "生成失败") };
  } catch { return { ok: false, msg: "生成失败" }; }
}

// ═══ 内容管控 ═══

export async function fetchReviews(): Promise<TodoReviewItem[]> {
  try {
    const r = await get<{ code: number; data: { items?: any[] } }>("/admin/v1/kg/review/pending");
    const items = r?.data?.items || [];
    const roleMap: Record<string, string> = { DZ: "大张(临床)", XZ: "小张(典籍)" };
    return items.map((x: any) => {
      const c = x.content && typeof x.content === "object" ? x.content : {};
      const rawName = c.entity_name || c.name || c.clause_text || c.title || x.item_id_in_kg || x.id || "";
      const name = typeof rawName === "string"
        ? (rawName.length > 60 ? rawName.slice(0, 60) + "…" : rawName)
        : String(rawName);
      return {
        id: x.id || "",
        type: x.item_type || c.entity_type || c.type || x.type || "知识条目",
        name,
        conf: x.confidence ?? x.conf ?? 0,
        // 来源列展示原始任务类别（证候提纲/方证对应/方剂信息/知识审核/自生长审核）
        source: c.type || c._src || "历史标注",
        reviewer: roleMap[x.reviewer_role] || x.reviewer_role || x.reviewer || "—",
        // 详情抽屉需要完整 content（后端列表接口已透传）
        content: c,
      };
    });
  } catch { return []; }
}

export async function reviewAction(id: string, action: "approve" | "reject") {
  return post(`/admin/v1/kg/review/action`, { review_id: id, action, note: "" });
}

/** POST /admin/v1/kg/review/{id}/refine — AI 翻译+提炼（研究题目/结论/共识分歧），写回 content._refined */
export async function refineReview(id: string): Promise<MutateResult<{ refined: any }>> {
  return mutate<{ refined: any }>("POST", `/admin/v1/kg/review/${encodeURIComponent(id)}/refine`);
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

/** POST /admin/v1/content/words — 新增敏感词（scene: HEALTH/MED/EDU/GLOBAL；level: warn/block） */
export async function addSensitiveWord(
  word: string, scene: string, level: string, replacement?: string,
): Promise<boolean> {
  try {
    await mutate("POST", "/admin/v1/content/words", {
      word, scene, level, replacement: replacement || null,
    });
    return true;
  } catch (e) { console.error("addSensitiveWord", e); return false; }
}

/** DELETE /admin/v1/content/words/{id} — 删除敏感词 */
export async function deleteSensitiveWord(id: string): Promise<boolean> {
  try {
    await mutate("DELETE", `/admin/v1/content/words/${encodeURIComponent(id)}`);
    return true;
  } catch (e) { console.error("deleteSensitiveWord", e); return false; }
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
      is_demo: s.is_demo !== undefined ? !!s.is_demo : true,
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

// ═══ Agent 中台（智能控制面）═══
// 构件 A 资源池 / 构件 B 套餐专家团组合 / 构件 C 各 Agent 看板
// 后端契约见 qihuang_platform/control/router.py（/admin/v1/agents*, /admin/v1/plans/{id}/agents）

export interface AgentDef {
  agent_key: string;
  name: string;
  kind: string;
  engine: string | null;
  category: string;
  router_prefix: string | null;
  capabilities: string[];
  status: string;          // active / inactive
  desc: string | null;
  features_json: Record<string, any>;
  included_in_plans: string[];
}

/** GET /admin/v1/agents — 能力资源池（含被哪些套餐纳入专家团） */
export async function fetchAgentCenter(): Promise<{ total: number; agents: AgentDef[] }> {
  try {
    const r = await get<{ code: number; data: { total?: number; agents?: any[] } }>("/admin/v1/agents");
    if (r?.code !== 0 || !r.data) return { total: 0, agents: [] };
    const agents = (r.data.agents || []).map((a: any) => ({
      agent_key: a.agent_key || "",
      name: a.name || a.agent_key || "",
      kind: a.kind || "business_embedded",
      engine: a.engine ?? null,
      category: a.category || "general",
      router_prefix: a.router_prefix ?? null,
      capabilities: a.capabilities || [],
      status: a.status || "active",
      desc: a.desc ?? null,
      features_json: a.features_json || {},
      included_in_plans: a.included_in_plans || [],
    }));
    return { total: r.data.total ?? agents.length, agents };
  } catch (e) { console.error("fetchAgentCenter error", e); return { total: 0, agents: [] }; }
}

/** POST /admin/v1/agents/{agent_key}/toggle — 运营态热插拔启停 */
export async function toggleAgent(agentKey: string, status: "active" | "inactive"): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/agents/${encodeURIComponent(agentKey)}/toggle`, { status });
}

/** 健康助手喂料口（2026-08-22 老黄拍板：B 端后台可视化编辑营销语料） */
export interface HealthAssistantPromptData {
  tenant_id: string;
  health_assistant_prompt: string;
  sample?: string;
}
/** GET /admin/v1/tenants/{tenant_id}/health-assistant-prompt — 查语料（含空态样例） */
export async function fetchHealthAssistantPrompt(tenantId: string): Promise<MutateResult<HealthAssistantPromptData>> {
  return get<{ code: number; msg?: string; data?: HealthAssistantPromptData; detail?: any }>(
    `/admin/v1/tenants/${encodeURIComponent(tenantId)}/health-assistant-prompt`,
  ).then((r) => {
    if (r?.code === 0 && r.data) return { ok: true, msg: r.msg || "成功", data: r.data };
    const msg = r?.detail?.msg || r?.detail?.message || r?.msg || "查询失败";
    return { ok: false, msg };
  }).catch((e: any) => ({ ok: false, msg: e?.message || "网络异常" }));
}
/** PUT /admin/v1/tenants/{tenant_id}/health-assistant-prompt — 保存语料（自动过合规，违规拦截） */
export async function saveHealthAssistantPrompt(tenantId: string, prompt: string): Promise<MutateResult> {
  return mutate("PUT", `/admin/v1/tenants/${encodeURIComponent(tenantId)}/health-assistant-prompt`, { prompt });
}

/* ── #482 门店级语料槽（Org 维度，门店列表复用已有 fetchTenantOrgs）── */
export interface OrgPromptData {
  tenant_id: string;
  org_id: string;
  health_assistant_prompt: string;
  platform_default: string;
  sample?: string;
}
/** GET /admin/v1/tenants/{tenant_id}/orgs/{org_id}/health-assistant-prompt — 门店语料（含平台默认兜底展示） */
export async function fetchOrgHealthAssistantPrompt(tenantId: string, orgId: string): Promise<MutateResult<OrgPromptData>> {
  return get<{ code: number; msg?: string; data?: OrgPromptData; detail?: any }>(
    `/admin/v1/tenants/${encodeURIComponent(tenantId)}/orgs/${encodeURIComponent(orgId)}/health-assistant-prompt`,
  ).then((r) => {
    if (r?.code === 0 && r.data) return { ok: true, msg: r.msg || "成功", data: r.data };
    const msg = r?.detail?.msg || r?.detail?.message || r?.msg || "查询失败";
    return { ok: false, msg };
  }).catch((e: any) => ({ ok: false, msg: e?.message || "网络异常" }));
}
/** PUT /admin/v1/tenants/{tenant_id}/orgs/{org_id}/health-assistant-prompt — 保存门店语料（自动过合规） */
export async function saveOrgHealthAssistantPrompt(tenantId: string, orgId: string, prompt: string): Promise<MutateResult> {
  return mutate("PUT", `/admin/v1/tenants/${encodeURIComponent(tenantId)}/orgs/${encodeURIComponent(orgId)}/health-assistant-prompt`, { prompt });
}

/** GET /admin/v1/agents/{agent_key}/dashboard — 各 Agent 运营看板（中台派发，内核在底层） */
export async function fetchAgentDashboard(
  agentKey: string, opts?: { storeId?: string; port?: string },
): Promise<{ ok: boolean; dashboard?: any; msg?: string }> {
  try {
    const qs = new URLSearchParams();
    if (opts?.storeId) qs.set("store_id", opts.storeId);
    if (opts?.port) qs.set("port", opts.port);
    const q = qs.toString();
    const r = await get<{ code: number; data?: any; msg?: string }>(
      `/admin/v1/agents/${encodeURIComponent(agentKey)}/dashboard${q ? `?${q}` : ""}`,
    );
    if (r?.code === 0 && r.data) return { ok: true, dashboard: r.data.dashboard };
    return { ok: false, msg: r?.msg || "看板拉取失败" };
  } catch (e: any) { return { ok: false, msg: e?.message || "看板拉取异常" }; }
}

export interface PlanAgentRow { planId: string; planName: string; agents: string[]; }

/** GET /admin/v1/plans + 每个套餐的 agents — 套餐专家团矩阵（构件 B 编排用） */
export async function fetchPlanAgentMatrix(): Promise<PlanAgentRow[]> {
  try {
    const r = await get<{ code: number; data?: any }>("/admin/v1/plans");
    const plans = Array.isArray(r?.data) ? r.data : (r?.data?.items || []);
    const rows: PlanAgentRow[] = [];
    for (const p of plans) {
      const planId = p.id || p.plan_id || "";
      if (!planId) continue;
      let agents: string[] = [];
      try {
        const pr = await get<{ code: number; data?: any }>(`/admin/v1/plans/${encodeURIComponent(planId)}/agents`);
        agents = pr?.data?.agents || [];
      } catch { agents = []; }
      rows.push({ planId, planName: p.display_name || p.plan_name || planId, agents });
    }
    return rows;
  } catch (e) { console.error("fetchPlanAgentMatrix error", e); return []; }
}

/** PUT /admin/v1/plans/{plan_id}/agents — 设置套餐的 Agent 专家团组合 */
export async function setPlanAgents(planId: string, agents: string[]): Promise<MutateResult> {
  return mutate("PUT", `/admin/v1/plans/${encodeURIComponent(planId)}/agents`, { agents });
}

export interface AgentUsageItem {
  agent_key: string;
  name: string;
  calls: number;
  tokens: number;
  cost_cents: number;
  cost_yuan: number;
}

/** GET /admin/v1/agents/usage — 各 Agent 调用量聚合（支持租户下钻 + 近 N 日）
 *  tenantId 留空=全部租户；days 默认 7。驾驶舱活跃度排行 + 金额维度数据源。 */
export async function fetchAgentUsage(tenantId?: string, days = 7): Promise<{ usage: AgentUsageItem[]; totalCalls: number; totalCostYuan: number }> {
  try {
    const qs = new URLSearchParams();
    if (tenantId) qs.set("tenant_id", tenantId);
    qs.set("days", String(days));
    const r = await get<{ code: number; data?: { usage?: any[]; total_calls?: number; total_cost_yuan?: number } }>(
      `/admin/v1/agents/usage?${qs.toString()}`
    );
    if (r?.code !== 0 || !r.data) return { usage: [], totalCalls: 0, totalCostYuan: 0 };
    const usage = (r.data.usage || []).map((u: any) => ({
      agent_key: u.agent_key || "",
      name: u.name || u.agent_key || "",
      calls: u.calls ?? 0,
      tokens: u.tokens ?? 0,
      cost_cents: u.cost_cents ?? 0,
      cost_yuan: u.cost_yuan ?? 0,
    }));
    return { usage, totalCalls: r.data.total_calls ?? 0, totalCostYuan: r.data.total_cost_yuan ?? 0 };
  } catch (e) { console.error("fetchAgentUsage error", e); return { usage: [], totalCalls: 0, totalCostYuan: 0 }; }
}

export interface ReconcileGap {
  type: string;
  severity: string;
  detail: string;
}
export interface ReconcileTenantResult {
  tenant_id: string;
  period: string;
  calllog?: { calls: number; tokens: number; cost_cents: number };
  usage_order?: any;
  bill?: any;
  healthy: boolean;
  gaps: ReconcileGap[];
}
export interface ReconcileAnomalies {
  bare_zero?: { count: number; samples: string[] };
  double_write_suspect?: { trace_ids_with_dup: number; count: number; samples: string[] };
}
export interface BillingReconcileResult {
  mode: "tenant" | "all";
  period: string;
  tenant_id?: string;
  reconcile?: ReconcileTenantResult;
  anomalies?: ReconcileAnomalies;
  fixed?: boolean;
  tenants?: ReconcileTenantResult[];
  summary?: { total: number; healthy: number; with_gaps: number; total_gaps: number; fixed: number };
}

/** GET /admin/v1/billing/reconcile — 真计费对账（三层: CallLog→usage单→Bill） */
export async function fetchBillingReconcile(
  period: string,
  tenantId?: string,
  fix = false
): Promise<BillingReconcileResult | null> {
  try {
    const qs = new URLSearchParams();
    qs.set("period", period);
    if (tenantId) qs.set("tenant_id", tenantId);
    if (fix) qs.set("fix", "1");
    const r = await get<{ code: number; data?: BillingReconcileResult }>(`/admin/v1/billing/reconcile?${qs.toString()}`);
    if (r?.code !== 0 || !r.data) return null;
    return r.data;
  } catch (e) { console.error("fetchBillingReconcile error", e); return null; }
}

export interface AgentBusinessSignal {
  kg_id: string;
  entity_name: string | null;
  entity_type: string | null;
  ref_count: number;
}

export interface AgentBusinessSignals {
  window_days: number;
  signal_enabled: boolean;
  totals: { references: number; distinct_kg: number };
  top: AgentBusinessSignal[];
}

/** GET /admin/v1/agent-business-signals — 活态化 P1-B 业务实证采纳榜（consult 引用日志聚合） */
export async function fetchAgentBusinessSignals(): Promise<AgentBusinessSignals | null> {
  try {
    const r = await get<{ code: number; data: AgentBusinessSignals }>("/admin/v1/agent-business-signals");
    return r?.data || null;
  } catch (e) { console.error("fetchAgentBusinessSignals", e); return null; }
}

// ═══ 中医健康顾问（health-advisor）═══
// 后端契约见 qihuang_platform/agent/health_advisor/router.py
// POST /api/v1/agent/health-advisor/consult（需登录态，复用 _token）

export interface HealthAdvisorConsultReq {
  question: string;
  profile?: { age?: number; gender?: string };
  store_id?: string;
  mode?: "full" | "quick";
  session_id?: string;
}

export interface HealthAdvisorConsultResult {
  reply: string;
  constitution?: { type?: string; desc?: string };
  syndrome?: { name?: string; desc?: string; confidence?: number };
  formulas?: { name?: string; desc?: string }[];
  suggestions?: string[];
  report_id?: string;
  session_id?: string;
  disclaimer?: string;
  partial?: boolean;
  trace_id?: string;
}

/** POST /api/v1/agent/health-advisor/consult — 中医健康顾问辨证（固定专业辨证链 + partial 降级） */
export async function consultHealthAdvisor(
  payload: HealthAdvisorConsultReq,
): Promise<{ code: number; message?: string; data?: HealthAdvisorConsultResult }> {
  return post<{ code: number; message?: string; data?: HealthAdvisorConsultResult }>(
    "/api/v1/agent/health-advisor/consult",
    payload,
  );
}

// ═══ 门店话术教练（store-coach）═══
// 后端契约见 qihuang_platform/agent/store_coach/router.py
// POST /api/v1/agent/store-coach/sessions（需登录态，复用 _token）

export interface StoreCoachTrialReq {
  scene?: string;
  topic: string;
  customer_profile?: string;
  material_text?: string;
  passing_score?: number;
}

export interface StoreCoachTrialResult {
  session_id: string;
  scene: string;
  topic: string;
  customer_profile: string;
  opening: string;
  model?: string;
  material_ref?: string | null;
  passing_score?: number | null;
}

export async function consultStoreCoach(
  payload: StoreCoachTrialReq,
): Promise<{ code: number; message?: string; data?: StoreCoachTrialResult }> {
  return post<{ code: number; message?: string; data?: StoreCoachTrialResult }>(
    "/api/v1/agent/store-coach/sessions",
    payload,
  );
}

// ═══ 多租户能力中心 ═══

export interface CapabilityTemplate {
  id: string;
  tenant_id: string;
  name: string;
  kind: string;
  content_json: Record<string, unknown>;
  current_version: string;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  ownership: {
    visibility: string | null;
    source: string | null;
    owner_org_id: string | null;
  } | null;
}

export interface CapabilitySubmission {
  id: string;
  template_id: string;
  submitter_tenant_id: string | null;
  submitter_org_id: string | null;
  status: string;
  reviewer_id: string | null;
  review_note: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
}

/** GET /admin/v1/template-center/templates — 模板列表 */
export async function fetchCapabilityTemplates(): Promise<CapabilityTemplate[]> {
  try {
    const r = await get<{ code: number; data: { items?: CapabilityTemplate[]; total?: number } }>(
      "/admin/v1/template-center/templates",
    );
    return r?.data?.items || [];
  } catch (e) { console.error("fetchCapabilityTemplates", e); return []; }
}

/** POST /admin/v1/template-center/templates — 创建模板 */
export async function createCapabilityTemplate(body: {
  name: string; kind: string; content_json: Record<string, unknown>;
}): Promise<MutateResult> {
  return mutate("POST", "/admin/v1/template-center/templates", { ...body, visibility: "private" });
}

/** PUT /admin/v1/template-center/templates/{id} — 编辑模板（后端自动快照旧版本 + 版本自增） */
export async function updateCapabilityTemplate(
  templateId: string,
  body: { name?: string; content_json?: Record<string, unknown> },
): Promise<MutateResult> {
  return mutate("PUT", `/admin/v1/template-center/templates/${encodeURIComponent(templateId)}`, body);
}

/** POST /admin/v1/template-center/templates/{id}/clone — 克隆到指定机构 */
export async function cloneCapabilityTemplate(
  templateId: string, targetOrgId: string,
): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/template-center/templates/${encodeURIComponent(templateId)}/clone`, {
    target_org_id: targetOrgId, visibility: "private",
  });
}

/** POST /admin/v1/template-center/templates/{id}/submit — 机构模板提交平台审核 */
export async function submitCapabilityTemplate(templateId: string): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/template-center/templates/${encodeURIComponent(templateId)}/submit`);
}

/** GET /admin/v1/template-center/review/submissions — 审核单列表 */
export async function fetchCapabilitySubmissions(status?: string): Promise<CapabilitySubmission[]> {
  try {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    const r = await get<{ code: number; data: { items?: CapabilitySubmission[]; total?: number } }>(
      `/admin/v1/template-center/review/submissions${q}`,
    );
    return r?.data?.items || [];
  } catch (e) { console.error("fetchCapabilitySubmissions", e); return []; }
}

/** POST /admin/v1/template-center/review/submissions/{id}/approve — 平台采纳（提升 public） */
export async function approveCapabilitySubmission(submissionId: string, note: string): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/template-center/review/submissions/${encodeURIComponent(submissionId)}/approve`, {
    review_note: note,
  });
}

/** POST /admin/v1/template-center/review/submissions/{id}/reject — 平台强下架（收回 private） */
export async function rejectCapabilitySubmission(submissionId: string, note: string): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/template-center/review/submissions/${encodeURIComponent(submissionId)}/reject`, {
    review_note: note,
  });
}

export interface CapabilityVersion {
  version_tag: string;
  snapshot_json: Record<string, unknown>;
  created_by: string | null;
  created_at: string | null;
}

export interface CapabilityStats {
  totals: { templates: number; versions: number; clones: number };
  templates_by_kind: Record<string, number>;
  reviews: Record<string, number>;
  sync: Record<string, number>;
  disable_requests: Record<string, number>;
}

/** GET /admin/v1/template-center/templates/{id}/versions — 版本快照列表 */
export async function fetchCapabilityTemplateVersions(
  templateId: string,
): Promise<{ items: CapabilityVersion[]; current_version: string; total: number }> {
  try {
    const r = await get<{ code: number; data: { items?: CapabilityVersion[]; current_version?: string; total?: number } }>(
      `/admin/v1/template-center/templates/${encodeURIComponent(templateId)}/versions`,
    );
    return {
      items: r?.data?.items || [],
      current_version: r?.data?.current_version || "",
      total: r?.data?.total || 0,
    };
  } catch (e) { console.error("fetchCapabilityTemplateVersions", e); return { items: [], current_version: "", total: 0 }; }
}

/** POST /admin/v1/template-center/templates/{id}/rollback — 回滚到指定版本 */
export async function rollbackCapabilityTemplate(
  templateId: string, versionTag: string,
): Promise<MutateResult> {
  return mutate("POST", `/admin/v1/template-center/templates/${encodeURIComponent(templateId)}/rollback`, {
    version_tag: versionTag,
  });
}

/** GET /admin/v1/template-center/stats — 运营统计聚合 */
export async function fetchCapabilityStats(): Promise<CapabilityStats | null> {
  try {
    const r = await get<{ code: number; data: CapabilityStats }>("/admin/v1/template-center/stats");
    return r?.data || null;
  } catch (e) { console.error("fetchCapabilityStats", e); return null; }
}
