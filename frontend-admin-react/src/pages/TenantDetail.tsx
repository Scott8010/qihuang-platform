import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ArrowLeft, KeyRound, Sparkles, Loader2, Check, Minus } from "lucide-react";
import { C, sceneMap, statusMap, billStatus, planFeatureLabels } from "@/lib/types";
import type {
  Tenant, OrgItem, TenantUserItem, BillItem, SubscriptionItem, PlanItem, PlanFeatures,
} from "@/lib/types";
import {
  fetchTenantOrgs, fetchTenantUsers, fetchBills, fetchSubscriptions, fetchPlans,
} from "@/lib/api";

/** 租户详情 — 全部数据来自后端真实接口
 *  机构 → GET /admin/v1/tenants/{id}/orgs
 *  用户 → GET /admin/v1/tenants/{id}/users
 *  订阅 → GET /admin/v1/subscriptions（按 tenant_id 过滤）
 *  账单 → GET /admin/v1/billing/bills（按 tenant_id 过滤）
 *  套餐特性 → GET /admin/v1/plans
 *  后端未提供的维度（分日趋势 / 端点级用量 / 单租户特性覆写）一律显示空态，不造假数据
 */
export default function TenantDetail({ tenant, onBack }: { tenant: Tenant; onBack: () => void }) {
  const t = tenant;
  const hasQuota = t.quotaCalls > 0;
  const pct = hasQuota ? Math.min(100, Math.round((t.usedCalls / t.quotaCalls) * 100)) : 0;

  const [loading, setLoading] = useState(true);
  const [orgs, setOrgs] = useState<OrgItem[]>([]);
  const [users, setUsers] = useState<TenantUserItem[]>([]);
  const [bills, setBills] = useState<BillItem[]>([]);
  const [subs, setSubs] = useState<SubscriptionItem[]>([]);
  const [plans, setPlans] = useState<PlanItem[]>([]);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchTenantOrgs(t.id).then(setOrgs),
      fetchTenantUsers(t.id).then(setUsers),
      fetchBills().then((all) => setBills(all.filter((b) => b.tenantId === t.id))),
      fetchSubscriptions().then((all) => setSubs(all.filter((s) => s.tenantId === t.id))),
      fetchPlans().then(setPlans),
    ]).finally(() => setLoading(false));
  }, [t.id]);

  const myPlan =
    plans.find((p) => p.planName === t.plan) ||
    plans.find((p) => p.name === t.plan) ||
    null;

  const sc = sceneMap[t.scene] || { label: t.scene, color: C.mid, bg: C.soft };
  const st = statusMap[t.status] || { label: t.status, cls: "bg-gray-100 text-gray-600 border-gray-200" };

  const empty = (text: string) => (
    <div className="py-10 text-center text-[13px]" style={{ color: C.light }}>
      {loading ? <span className="inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 加载中…</span> : text}
    </div>
  );

  const userStatusCls = (s: string) =>
    /active|enabled|正常/i.test(s)
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : /disabled|locked|停用|禁用/i.test(s)
        ? "bg-red-50 text-red-600 border-red-200"
        : "bg-gray-100 text-gray-600 border-gray-200";

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={onBack} style={{ borderColor: C.border, color: C.primary }}>
          <ArrowLeft className="w-4 h-4 mr-1" /> 返回列表
        </Button>
        <h2 className="text-[17px] font-semibold">{t.name}</h2>
        <span className="px-2 py-0.5 rounded text-[11px]" style={{ color: sc.color, background: sc.bg }}>
          {sc.label}场景
        </span>
        <span className={`px-2 py-0.5 rounded border text-[11px] ${st.cls}`}>{st.label}</span>
        {t.module3d && (
          <Badge variant="outline" className="border-amber-300 text-[11px]" style={{ color: C.gold }}>
            <Sparkles className="w-3 h-3 mr-1" /> 岐黄三境 3D
          </Badge>
        )}
        <div className="flex-1" />
        {loading && <Loader2 className="w-4 h-4 animate-spin" style={{ color: C.light }} />}
      </div>

      {/* 概要条 */}
      <div className="grid grid-cols-5 gap-3 text-[13px]">
        {[
          { l: "租户 ID", v: t.id || "—" },
          { l: "套餐", v: `${t.plan} · 到期 ${t.expires || "—"}` },
          { l: "机构 / 用户", v: `${orgs.length || t.orgs} / ${(users.length || t.users).toLocaleString()}` },
          {
            l: "累计调用",
            v: hasQuota
              ? `${t.usedCalls.toLocaleString()} / ${t.quotaCalls.toLocaleString()}（${pct}%）`
              : `${t.usedCalls.toLocaleString()} · 配额不限`,
          },
          { l: "数据隔离", v: "tenant_id 行级" },
        ].map((x) => (
          <Card key={x.l} className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-3">
              <div className="text-[11px]" style={{ color: C.light }}>{x.l}</div>
              <div className="mt-1 font-medium text-[12.5px]">{x.v}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">订阅与用量</TabsTrigger>
          <TabsTrigger value="orgs">机构管理</TabsTrigger>
          <TabsTrigger value="users">用户账号</TabsTrigger>
          <TabsTrigger value="features">套餐特性</TabsTrigger>
          <TabsTrigger value="bills">账单记录</TabsTrigger>
        </TabsList>

        {/* ============ 订阅与用量 ============ */}
        <TabsContent value="overview" className="mt-4 space-y-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">订阅记录</div>
              {subs.length === 0 ? empty("该租户暂无订阅记录") : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px]" style={{ color: C.light }}>
                      {["订阅 ID", "套餐", "状态", "生效日", "到期日", "自动续订"].map((h) => (
                        <th key={h} className="pb-2 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {subs.map((s) => (
                      <tr key={s.id} className="border-t" style={{ borderColor: C.border }}>
                        <td className="py-2.5 font-mono text-[12px]">{s.id}</td>
                        <td className="py-2.5">{s.planId || "—"}</td>
                        <td className="py-2.5">
                          <Badge variant="outline" className={userStatusCls(s.status)}>{s.status || "—"}</Badge>
                        </td>
                        <td className="py-2.5" style={{ color: C.mid }}>{s.startDate || "—"}</td>
                        <td className="py-2.5" style={{ color: C.mid }}>{s.endDate || "—"}</td>
                        <td className="py-2.5">{s.autoRenew ? "是" : "否"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>

          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-1">分日趋势 / 端点级用量</div>
              <div className="py-8 text-center text-[13px]" style={{ color: C.light }}>
                后端当前未提供单租户「分日趋势」与「端点级用量」明细接口
                <div className="mt-1 text-[11.5px]">
                  已上报的聚合口径见「计量计费」与「监控大盘」；明细接口开通后此处自动填充
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 机构管理 ============ */}
        <TabsContent value="orgs" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">下级机构（{orgs.length} 家）</div>
              {orgs.length === 0 ? empty("该租户暂无下级机构") : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px]" style={{ color: C.light }}>
                      {["机构 ID", "名称", "上级", "用户数", "状态"].map((h) => (
                        <th key={h} className="pb-2 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {orgs.map((o) => (
                      <tr key={o.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                        <td className="py-2.5 font-mono text-[12px]">{o.id}</td>
                        <td className="py-2.5 font-medium">{o.name}</td>
                        <td className="py-2.5 font-mono text-[12px]" style={{ color: C.mid }}>{o.parentId || "—"}</td>
                        <td className="py-2.5">{o.userCount}</td>
                        <td className="py-2.5">
                          <Badge variant="outline" className={userStatusCls(o.status)}>{o.status || "—"}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 用户账号 ============ */}
        <TabsContent value="users" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">用户账号（{users.length} 个）</div>
              {users.length === 0 ? empty("该租户暂无用户账号") : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px]" style={{ color: C.light }}>
                      {["用户", "手机号", "邮箱", "角色", "机构", "创建时间", "状态"].map((h) => (
                        <th key={h} className="pb-2 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                        <td className="py-2.5">
                          <div className="font-medium">{u.displayName}</div>
                          <div className="text-[11px] font-mono" style={{ color: C.light }}>{u.username || u.id}</div>
                        </td>
                        <td className="py-2.5" style={{ color: C.mid }}>{u.phone || "—"}</td>
                        <td className="py-2.5" style={{ color: C.mid }}>{u.email || "—"}</td>
                        <td className="py-2.5">{u.roles.length ? u.roles.join("、") : "—"}</td>
                        <td className="py-2.5" style={{ color: C.mid }}>{u.orgName || "—"}</td>
                        <td className="py-2.5 text-[12px]" style={{ color: C.light }}>{(u.createdAt || "—").slice(0, 19).replace("T", " ")}</td>
                        <td className="py-2.5">
                          <Badge variant="outline" className={userStatusCls(u.status)}>{u.status || "—"}</Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 套餐特性 ============ */}
        <TabsContent value="features" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-1">套餐特性（{myPlan ? myPlan.name : t.plan}）</div>
              <div className="text-[12px] mb-3" style={{ color: C.light }}>
                特性开关由套餐 features_json 统一下发（GET /admin/v1/plans）；后端当前未提供「单租户特性覆写」接口，此处为只读。
              </div>
              {!myPlan ? empty(`未在套餐库中匹配到「${t.plan}」，无法展示特性明细`) : (
                <div className="space-y-2">
                  {planFeatureLabels.map((f) => {
                    const on = !!myPlan.features[f.key as keyof PlanFeatures];
                    return (
                      <div
                        key={f.key}
                        className="flex items-center justify-between rounded-lg border p-3.5"
                        style={{ borderColor: C.border, background: on ? "#F8FBFA" : "#fff" }}
                      >
                        <div>
                          <div className="text-[13px] font-medium flex items-center gap-2">
                            {f.label}
                            <span className="font-mono text-[11px]" style={{ color: C.light }}>{f.key}</span>
                          </div>
                        </div>
                        {on
                          ? <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: C.primary }}><Check className="w-4 h-4" /> 已包含</span>
                          : <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: C.light }}><Minus className="w-4 h-4" /> 不包含</span>}
                      </div>
                    );
                  })}
                  <div className="flex items-center justify-between rounded-lg border p-3.5" style={{ borderColor: C.border, background: t.module3d ? "#FDF9F0" : "#fff" }}>
                    <div className="text-[13px] font-medium flex items-center gap-2">
                      岐黄三境 3D（租户级开通标记）
                      <span className="font-mono text-[11px]" style={{ color: C.light }}>module_3d</span>
                    </div>
                    {t.module3d
                      ? <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: C.gold }}><Check className="w-4 h-4" /> 已开通</span>
                      : <span className="inline-flex items-center gap-1 text-[12px]" style={{ color: C.light }}><Minus className="w-4 h-4" /> 未开通</span>}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 账单记录 ============ */}
        <TabsContent value="bills" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">历史账单</div>
              {bills.length === 0 ? empty("该租户暂无出账记录（新建租户在首个账期末出账）") : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px]" style={{ color: C.light }}>
                      {["账单号", "账期", "调用量", "Token", "金额", "状态"].map((h) => (
                        <th key={h} className="pb-2 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {bills.map((b) => {
                      const s = billStatus[b.status] || { label: b.status, cls: "bg-gray-100 text-gray-600 border-gray-200" };
                      return (
                        <tr key={b.id} className="border-t" style={{ borderColor: C.border }}>
                          <td className="py-2.5 font-mono text-[12px]">{b.id}</td>
                          <td className="py-2.5">{b.period}</td>
                          <td className="py-2.5">{Number(b.calls).toLocaleString()}</td>
                          <td className="py-2.5">{Number(b.tokens).toLocaleString()}</td>
                          <td className="py-2.5 font-medium">¥{b.amount.toLocaleString()}</td>
                          <td className="py-2.5"><Badge variant="outline" className={s.cls}>{s.label}</Badge></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              <div className="mt-3 flex items-center gap-1.5 text-[11.5px]" style={{ color: C.light }}>
                <KeyRound className="w-3.5 h-3.5" /> 续费与套餐变更在「计量计费」页操作。
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
