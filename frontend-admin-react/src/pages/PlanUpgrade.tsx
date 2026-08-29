import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, ArrowUpCircle, CheckCircle2, AlertCircle, Clock, XCircle } from "lucide-react";
import { C, sceneMap } from "@/lib/types";
import { fetchTenantExtended, fetchPlans, upgradeSubscription, cancelPendingUpgrade } from "@/lib/api";
import type { TenantPlanItem, PlanItem } from "@/lib/types";

export default function PlanUpgrade() {
  const [tenants, setTenants] = useState<TenantPlanItem[]>([]);
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<Set<string>>(new Set());
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // 套餐展示等级顺序：体验版 → 标准版 → 专业版 → 企业版（前端兜底，不依赖后端排序）
  const PLAN_LEVEL: Record<string, number> = {
    "体验版": 1, "标准版": 2, "专业版": 3, "企业版": 4,
  };

  const load = async () => {
    setLoading(true);
    const [ts, ps] = await Promise.all([fetchTenantExtended(20), fetchPlans()]);
    setTenants(ts);
    // 前端硬排序：保证 体验版→标准版→专业版→企业版（无论后端 order by price_cents 是否乱）
    setPlans([...ps].sort((a, b) => (PLAN_LEVEL[a.name] ?? 99) - (PLAN_LEVEL[b.name] ?? 99)));
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const doUpgrade = async (t: TenantPlanItem) => {
    const pid = target[t.id];
    if (!pid) return;
    setSubmitting((s) => new Set(s).add(t.id));
    setToast(null);
    const r = await upgradeSubscription(t.id, pid);
    setSubmitting((s) => { const n = new Set(s); n.delete(t.id); return n; });
    if (r.ok) {
      const targetName = plans.find((p) => p.id === pid)?.name || "新套餐";
      setToast({ type: "ok", text: `已提交升级预约：${t.name} → ${targetName}，将于次月1号生效，当月仍按原套餐计费` });
      setTarget((m) => { const n = { ...m }; delete n[t.id]; return n; });
      await load();
    } else {
      setToast({ type: "err", text: r.msg || "升级提交失败" });
    }
  };

  const doCancelPending = async (t: TenantPlanItem) => {
    setCancelling((s) => new Set(s).add(t.id));
    setToast(null);
    const r = await cancelPendingUpgrade(t.id);
    setCancelling((s) => { const n = new Set(s); n.delete(t.id); return n; });
    if (r.ok) {
      setToast({ type: "ok", text: `已取消 ${t.name} 的升级预约，保持当前套餐` });
      await load();
    } else {
      setToast({ type: "err", text: r.msg || "取消失败" });
    }
  };

  return (
    <div className="space-y-4">
      {/* 标题 + 说明 */}
      <div className="flex items-center gap-2 flex-wrap">
        <ArrowUpCircle className="w-5 h-5" style={{ color: C.primary }} />
        <span className="text-[17px] font-semibold" style={{ color: C.primary }}>套餐升级</span>
        <span className="text-[14px]" style={{ color: C.light }}>
          预约次月1号生效，当月仍按原套餐计费与鉴权
        </span>
      </div>

      {/* 结果提示 */}
      {toast && (
        <div
          className="flex items-center gap-2 rounded-lg p-3 text-[15px]"
          style={{
            background: toast.type === "ok" ? "#EAF2EE" : "#FDECEA",
            color: toast.type === "ok" ? C.mid : "#B03A2E",
          }}
        >
          {toast.type === "ok" ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          {toast.text}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 加载租户与套餐…
        </div>
      )}

      <Card className="border" style={{ borderColor: C.border }}>
        <CardContent className="p-0">
          <table className="w-full text-[15px]">
            <thead>
              <tr className="border-b text-left" style={{ borderColor: C.border, color: C.light }}>
                <th className="px-5 py-3 font-medium">租户</th>
                <th className="px-3 py-3 font-medium">场景</th>
                <th className="px-3 py-3 font-medium">当前套餐</th>
                <th className="px-3 py-3 font-medium">升级到</th>
                <th className="px-3 py-3 font-medium w-[150px]">操作</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => {
                const samePlan = t.planId && target[t.id] === t.planId;
                const hasTarget = !!target[t.id];
                const busy = submitting.has(t.id);
                const cancellingBusy = cancelling.has(t.id);
                const hasPending = !!t.pendingPlan && !!t.pendingEffectiveDate;
                return (
                  <tr key={t.id} className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="px-5 py-3.5">
                      <div className="font-medium" style={{ color: C.ink }}>{t.name}</div>
                      <div className="text-[13px]" style={{ color: C.light }}>{t.id}</div>
                    </td>
                    <td className="px-3 py-3.5">
                      <span
                        className="px-2 py-0.5 rounded text-[13px]"
                        style={{ color: (sceneMap as any)[t.scene]?.color || C.mid, background: (sceneMap as any)[t.scene]?.bg || C.bg }}
                      >
                        {(sceneMap as any)[t.scene]?.label || t.scene}
                      </span>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>
                      {t.plan || <span style={{ color: C.light }}>未配置</span>}
                      {hasPending && (
                        <span
                          className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[13px] font-medium"
                          style={{ background: "#FBF4E4", color: "#8A6A1F", border: "1px solid #EDD9A8" }}
                          title={`将于 ${t.pendingEffectiveDate} 生效`}
                        >
                          <Clock className="w-3 h-3" />
                          预约升级中 · {t.pendingEffectiveDate} → {t.pendingPlan}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      {hasPending ? (
                        <span className="text-[14px]" style={{ color: C.light }}>
                          次月将生效，本月不可再改
                        </span>
                      ) : (
                        <select
                          value={target[t.id] || ""}
                          onChange={(e) => setTarget((m) => ({ ...m, [t.id]: e.target.value }))}
                          className="text-[15px] rounded-lg border px-3 py-2 bg-white outline-none"
                          style={{ borderColor: C.border, minWidth: 150 }}
                        >
                          <option value="">选择目标套餐</option>
                          {plans.map((p) => (
                            <option key={p.id} value={p.id} disabled={p.id === t.planId}>
                              {p.name}{p.id === t.planId ? "（当前）" : ""}
                            </option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      {hasPending ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={cancellingBusy}
                          style={{ borderColor: "#E5B8B3", color: "#B03A2E", background: "transparent" }}
                          onClick={() => doCancelPending(t)}
                        >
                          {cancellingBusy ? (
                            <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                          ) : (
                            <XCircle className="w-3.5 h-3.5 mr-1" />
                          )}
                          取消预约
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          disabled={!hasTarget || samePlan || busy}
                          style={{ background: hasTarget && !samePlan && !busy ? C.primary : "#C9D4CF" }}
                          onClick={() => doUpgrade(t)}
                        >
                          {busy ? (
                            <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                          ) : (
                            <ArrowUpCircle className="w-3.5 h-3.5 mr-1" />
                          )}
                          升级
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {tenants.length === 0 && !loading && (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-[14px]" style={{ color: C.light }}>暂无租户</td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <div className="text-[14px]" style={{ color: C.light }}>
        共 {tenants.length} 家租户 · 升级为次月1号生效，当前月仍按原套餐计费与鉴权
      </div>
    </div>
  );
}
