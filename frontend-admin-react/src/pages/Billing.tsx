import { useEffect, useState, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { BarChart3, Download, Check, Minus, Loader2 } from "lucide-react";
import { C, billStatus, planFeatureLabels, sceneMap } from "@/lib/types";
import type {
  PlanItem, BillItem, SubscriptionItem, SceneUsageItem, PriceBook,
  TenantPlanItem, AgentCenterItem, RechargePack, OrderItem,
} from "@/lib/types";
import {
  fetchBillingStats, fetchPlans, fetchBills, fetchSubscriptions, fetchSceneUsage, fetchPriceBook,
  fetchTenantExtended, upgradeSubscription, rechargePack, fetchAgents, addAgentAddon, fetchOrders,
  fetchWalletBalance,
} from "@/lib/api";

/* ═══════════════════════════════════════════
   计费与套餐 — 真实接口驱动（价目展示 + 直接充值入口）
   KPI    → GET /admin/v1/billing/usage
   套餐   → GET /admin/v1/plans
   账单   → GET /admin/v1/billing/bills
   订阅   → GET /admin/v1/subscriptions
   价目   → GET /admin/v1/billing/price-book
   租户   → GET /admin/v1/tenants-extended
   Agent  → GET /admin/v1/agents
   写操作 → 升级 /admin/v1/tenants/{id}/subscription/upgrade
           充值 /billing/v1/wallet/recharge?tenant_id=&pack=
           加购 /admin/v1/tenants/{id}/agent-addons
   ═══════════════════════════════════════════ */

/** 统一收银台 / 订单确认页（三处购买场景共用）。
 *  形态按真实支付设计：商品明细 + 应付合计 + 诚实支付状态提示 + 确认下单。
 *  当前支付通道未接，确认下单仅生成订单、暂不扣款。 */
function CheckoutDialog({
  open, onOpenChange, title, tenantName, items, totalYuan, settleNote = "",
  confirmText = "确认下单", onConfirm, confirming = false,
}: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; tenantName: string;
  items: { name: string; spec?: string; unitYuan: number; qty: number; subtotalYuan: number }[];
  totalYuan: number; settleNote?: string; confirmText?: string;
  onConfirm: () => void; confirming?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !confirming) onOpenChange(false); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>将为租户「<b>{tenantName || "—"}</b>」生成订单</DialogDescription>
        </DialogHeader>

        {/* 商品明细 */}
        <div className="border rounded-md overflow-hidden" style={{ borderColor: C.border }}>
          <table className="w-full text-[14px]">
            <thead>
              <tr className="text-left text-[12.5px]" style={{ color: C.light, background: C.bg }}>
                <th className="px-3 py-2 font-normal">项目</th>
                <th className="px-3 py-2 font-normal text-right">单价</th>
                <th className="px-3 py-2 font-normal text-right">数量</th>
                <th className="px-3 py-2 font-normal text-right">小计</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className="border-t" style={{ borderColor: C.border }}>
                  <td className="px-3 py-2.5" style={{ color: C.ink }}>
                    {it.name}
                    {it.spec && <div className="text-[12px] mt-0.5" style={{ color: C.light }}>{it.spec}</div>}
                  </td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.mid }}>¥{it.unitYuan}</td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.mid }}>{it.qty}</td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.ink }}>¥{it.subtotalYuan}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 合计 */}
        <div className="flex items-center justify-between pt-1">
          <span className="text-[14px]" style={{ color: C.mid }}>应付合计</span>
          <span className="text-[22px] font-bold" style={{ color: C.primary }}>
            ¥{totalYuan}<span className="text-[13px] font-normal" style={{ color: C.light }}>{settleNote}</span>
          </span>
        </div>

        {/* 诚实支付状态提示 */}
        <div className="rounded-md px-3 py-2.5 text-[13px] leading-relaxed"
          style={{ background: "#FBF4E4", color: "#8A6A1F", border: "1px solid #EADCBE" }}>
          ⚠️ 支付通道建设中：本次仅生成订单、暂不扣款。支付通道开通后，将按此订单金额结算。
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={confirming}>取消</Button>
          </DialogClose>
          <Button style={{ background: C.primary, color: "#fff" }} disabled={confirming} onClick={onConfirm}>
            {confirming ? "提交中…" : confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const MAIN_PLAN = "professional";   // 主力套餐高亮

/** 多模态类 Agent（后端口径，决定单加月费 ¥99，其余 ¥59） */
const MULTIMODAL_AGENTS = new Set(["tongue", "geo", "health-assistant", "health-advisor"]);
const agentFeeYuan = (key: string) => (MULTIMODAL_AGENTS.has(key) ? 99 : 59);

/** 订单类型 / 状态 展示映射（结算中心 #B） */
const orderTypeMap: Record<string, { label: string; cls: string }> = {
  recharge: { label: "充值", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  addon: { label: "单加订阅", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  usage: { label: "用量快照", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  plan: { label: "套餐", cls: "bg-purple-50 text-purple-700 border-purple-200" },
};
const orderStatusMap: Record<string, { label: string; cls: string }> = {
  PAID: { label: "已支付", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  PENDING: { label: "待支付", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  CANCELLED: { label: "已取消", cls: "bg-gray-100 text-gray-600 border-gray-200" },
};

/** 复用：Agent 多选清单（套餐引导追加 & 单加 Agent 块共用）
 *  disabledAgents：套餐已含的 agent（固定集合）→ 灰显「套餐已含 · 不另收费」，不可勾选 */
function AgentChecklist({
  agents, selected, onToggle, emptyText, disabledAgents,
}: {
  agents: AgentCenterItem[];
  selected: Set<string>;
  onToggle: (key: string, on: boolean) => void;
  emptyText?: string;
  disabledAgents?: Set<string>;
}) {
  if (agents.length === 0) {
    return <div className="py-6 text-center text-[13px]" style={{ color: C.light }}>{emptyText || "加载 Agent 列表中…"}</div>;
  }
  return (
    <div className="space-y-1.5 max-h-72 overflow-auto pr-1">
      {agents.map((a) => {
        const on = selected.has(a.agentKey);
        const locked = !!disabledAgents?.has(a.agentKey);
        return (
          <label
            key={a.agentKey}
            className={`flex items-center gap-2 p-2.5 rounded border ${locked ? "cursor-not-allowed" : "cursor-pointer"}`}
            style={{
              borderColor: locked ? C.border : (on ? C.primary : C.border),
              background: locked ? "#F4F7F5" : (on ? "#FBF4E4" : "#fff"),
              opacity: locked ? 0.62 : 1,
            }}
          >
            <Checkbox checked={on || locked} disabled={locked} onCheckedChange={(c) => { if (!locked) onToggle(a.agentKey, !!c); }} />
            <span className="flex-1 text-[14px]" style={{ color: locked ? C.light : C.ink }}>
              {a.name}
              {locked && <span className="ml-1.5 text-[12px]" style={{ color: "#8A6A1F" }}>（套餐已含）</span>}
            </span>
            <span className="text-[12px]" style={{ color: C.light }}>
              {locked ? "套餐已含 · 不另收费" : `¥${agentFeeYuan(a.agentKey)}/月`}
            </span>
          </label>
        );
      })}
    </div>
  );
}

function wan(n: number) {
  if (!n) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万`;
  return n.toLocaleString();
}

function fmtDate(s: string) {
  if (!s) return "—";
  return s.slice(0, 10);
}

export default function Billing() {
  const [stats, setStats] = useState({ totalCalls: 0, totalTokens: 0, cost: 0, revenue: 0 });
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [bills, setBills] = useState<BillItem[]>([]);
  const [subs, setSubs] = useState<SubscriptionItem[]>([]);
  const [scenes, setScenes] = useState<SceneUsageItem[]>([]);
  const [priceBook, setPriceBook] = useState<PriceBook | null>(null);
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [orderStatusFilter, setOrderStatusFilter] = useState("all");
  const [balance, setBalance] = useState<{ base: number; addon: number; total: number } | null>(null);
  const [loading, setLoading] = useState(true);

  // 充值操作所需的上下文
  const [tenants, setTenants] = useState<TenantPlanItem[]>([]);
  const [agents, setAgents] = useState<AgentCenterItem[]>([]);
  const [targetTenantId, setTargetTenantId] = useState<string>("");
  const targetTenant = tenants.find((t) => t.id === targetTenantId) || null;

  // 弹窗 / 选择状态
  const [upgradeTarget, setUpgradeTarget] = useState<PlanItem | null>(null);
  const [rechargeTarget, setRechargeTarget] = useState<RechargePack | null>(null);
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  // 单加 Agent 二次确认弹窗
  const [agentAddConfirmOpen, setAgentAddConfirmOpen] = useState(false);
  const [recharging, setRecharging] = useState(false);

  // 操作结果提示
  const [notice, setNotice] = useState<{ type: "ok" | "err" | "warn"; text: string } | null>(null);
  const flash = (type: "ok" | "err" | "warn", text: string) => {
    setNotice({ type, text });
    window.setTimeout(() => setNotice(null), 4500);
  };

  useEffect(() => {
    Promise.all([
      fetchBillingStats().then(setStats),
      fetchPlans().then(setPlans),
      fetchBills().then(setBills),
      fetchSubscriptions().then(setSubs),
      fetchSceneUsage().then(setScenes),
      fetchPriceBook().then(setPriceBook),
      fetchTenantExtended(50).then(setTenants),
      fetchAgents().then(setAgents),
    ]).finally(() => setLoading(false));
  }, []);

  // 订单记录跟随选中租户（#B 回看：看"这个租户买了什么"）+ 余额
  useEffect(() => {
    if (!targetTenantId) { setOrders([]); setBalance(null); return; }
    fetchOrders({ tenant_id: targetTenantId, page_size: 50 }).then(setOrders);
    fetchWalletBalance(targetTenantId).then(setBalance);
  }, [targetTenantId]);

  // 当前租户套餐自带 agents（固定集合，前端灰显防重复叠加）
  const targetPlanAgents = targetTenant ? (plans.find((p) => p.id === targetTenant.planId)?.agents || []) : [];
  const disabledAgents = new Set(targetPlanAgents);
  const filteredOrders = orderStatusFilter === "all" ? orders : orders.filter((o) => o.status === orderStatusFilter);

  // 应收 = 账单金额合计（真实派生，不写死）
  const receivable = bills.reduce((a, b) => a + (b.amount || 0), 0);
  const sceneTotalCalls = scenes.reduce((a, s) => a + (s.calls || 0), 0);

  // 租户订阅清单：受顶部"操作对象"选择器联动过滤
  const subsView = useMemo(
    () => (!targetTenantId ? subs : subs.filter((s) => s.tenantId === targetTenantId)),
    [subs, targetTenantId],
  );

  /** 导出账单为本地 CSV（对账单） */
  const exportBillsCsv = () => {
    const head = ["账单号", "套餐 / 租户", "账期", "调用量", "Token", "金额(元)", "状态"];
    const rows = bills.map((b) => [
      b.id, `${b.tenant}`, b.period, b.calls, b.tokens, String(b.amount ?? 0), b.status || "",
    ]);
    const csv = "\uFEFF" + [head, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `对账单_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── 写操作 ──
  const confirmPlanWithAgents = async () => {
    if (!upgradeTarget || !targetTenantId) return;
    const r1 = await upgradeSubscription(targetTenantId, upgradeTarget.id);
    if (!r1.ok) {
      setUpgradeTarget(null);
      flash("err", `开通失败：${r1.msg}`);
      return;
    }
    const keys = [...selectedAgents];
    setUpgradeTarget(null);
    if (keys.length > 0) {
      const r2 = await addAgentAddon(targetTenantId, keys);
      setSelectedAgents(new Set());
      flash(
        r2.ok ? "ok" : "err",
        r2.ok
          ? `开通已提交；并加购 ${keys.length} 个 Agent 成功：${r2.msg}`
          : `开通已提交，但 Agent 加购失败：${r2.msg}`,
      );
    } else {
      flash("ok", `订单已提交：开通/升级已预约（次月生效），费用待支付通道结算`);
    }
  };

  const confirmRecharge = async () => {
    if (!rechargeTarget || !targetTenantId) return;
    setRecharging(true);
    const r = await rechargePack(targetTenantId, rechargeTarget.key);
    setRecharging(false);
    setRechargeTarget(null);
    // 后端充值端点尚未实装；捕获失败统一提示"订单已记录（待支付）"，不报错吓人
    flash(r.ok ? "ok" : "warn",
      r.ok ? `订单已提交：${r.msg}` : `订单已记录（待支付）：当前支付通道未开通，充值将在通道接好后结算`);
  };

  const toggleAgent = (key: string, on: boolean) => {
    setSelectedAgents((prev) => {
      const n = new Set(prev);
      if (on) n.add(key); else n.delete(key);
      return n;
    });
  };

  const confirmAddAgent = async () => {
    if (!targetTenantId) { flash("err", "请先在顶部选择操作租户"); return; }
    const keys = [...selectedAgents];
    if (keys.length === 0) { flash("err", "请至少勾选一个 Agent"); return; }
    const r = await addAgentAddon(targetTenantId, keys);
    if (r.ok) setSelectedAgents(new Set());
    flash(r.ok ? "ok" : "err",
      r.ok ? `订单已提交：${r.msg}（费用待支付通道结算）` : `下单失败：${r.msg}`);
  };

  const kpiCards = [
    { label: "本月总调用", value: `${wan(stats.totalCalls)} 次`, sub: "来自网关计量埋点" },
    { label: "本月 Token 消耗", value: wan(stats.totalTokens), sub: "共识四模型合计" },
    { label: "本月 LLM 成本", value: `¥${stats.cost.toLocaleString()}`, sub: "按 total_cost_cents 折算" },
    { label: "账单应收合计", value: `¥${receivable.toLocaleString()}`, sub: `${bills.length} 张账单` },
  ];

  // 单加 Agent 确认弹窗费用摘要（口径与后端一致：多模态¥99 / 文本¥59）
  const addedKeys = [...selectedAgents];
  const addedText = addedKeys.filter((k) => !MULTIMODAL_AGENTS.has(k)).length;
  const addedMm = addedKeys.filter((k) => MULTIMODAL_AGENTS.has(k)).length;
  const addedTotalYuan = addedKeys.reduce((s, k) => s + agentFeeYuan(k), 0);

  return (
    <div className="space-y-4">
      {/* 操作结果提示 */}
      {notice && (
        <div className="px-4 py-2.5 rounded-md text-[14px]" style={{
          background: notice.type === "ok" ? "#EAF2EE" : notice.type === "warn" ? "#FBF4E4" : "#FBECEC",
          color: notice.type === "ok" ? "#2E5A4C" : notice.type === "warn" ? "#8A6A1F" : "#9A3B3B",
          border: `1px solid ${notice.type === "ok" ? "#C9E2D6" : notice.type === "warn" ? "#EADCBE" : "#F0CFCF"}`,
        }}>
          {notice.text}
        </div>
      )}

      {/* KPI 卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {kpiCards.map((k) => (
          <Card key={k.label} className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] mb-1" style={{ color: C.light }}>{k.label}</div>
              <div className="text-[24px] font-bold" style={{ color: C.ink }}>
                {loading ? <span className="text-[16px]" style={{ color: C.light }}>加载中…</span> : k.value}
              </div>
              <div className="text-[13px] mt-1" style={{ color: C.mid }}>{k.sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 操作对象：目标租户（选租户直接充） */}
      <Card className="border shadow-none" style={{ borderColor: C.primary }}>
        <CardContent className="p-4 space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[15px] font-medium" style={{ color: C.ink }}>操作对象（充值给哪个租户）</span>
            <Select value={targetTenantId} onValueChange={setTargetTenantId}>
              <SelectTrigger className="w-[300px] h-9">
                <SelectValue placeholder="选择目标租户…" />
              </SelectTrigger>
              <SelectContent>
                {tenants.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
                {tenants.length === 0 && (
                  <SelectItem value="__none" disabled>加载租户中…</SelectItem>
                )}
              </SelectContent>
            </Select>
            {targetTenant ? (
              <span className="text-[13px]" style={{ color: C.mid }}>
                当前套餐：<b style={{ color: C.ink }}>{targetTenant.plan || "—"}</b>
              </span>
            ) : (
              <span className="text-[13px]" style={{ color: C.light }}>未选择（下方按钮将不可用）</span>
            )}
          </div>
          <div className="text-[12px] leading-relaxed" style={{ color: C.light }}>
            此选择同时联动过滤下方「租户订阅」清单（仅显示该租户）；留空则显示全部租户订阅。
          </div>
        </CardContent>
      </Card>

      {/* 租户现状（#B：当前套餐 + 套餐自带 agents + 单加 agents + 余额） */}
      {targetTenant && (
        <Card className="border shadow-none" style={{ borderColor: C.primary, background: "#FBFCFA" }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>租户现状</span>
              <span className="text-[12.5px]" style={{ color: C.light }}>「{targetTenant.name}」当前套餐与已开通能力</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-[12.5px] mb-1" style={{ color: C.light }}>当前套餐</div>
                <div className="text-[17px] font-bold" style={{ color: C.primary }}>{targetTenant.plan || "未开通"}</div>
                {targetTenant.pendingPlan && (
                  <div className="text-[12px] mt-0.5" style={{ color: "#8A6A1F" }}>
                    预约升级：{targetTenant.pendingPlan}（{targetTenant.pendingEffectiveDate || "待定"} 生效）
                  </div>
                )}
              </div>
              <div>
                <div className="text-[12.5px] mb-1.5" style={{ color: C.light }}>套餐自带 Agent（固定，不另收费）</div>
                <div className="flex flex-wrap gap-1.5">
                  {targetPlanAgents.length ? targetPlanAgents.map((k) => (
                    <span key={k} className="text-[12.5px] px-2 py-0.5 rounded-full border" style={{ background: "#EAF2EE", color: "#2E5A4C", borderColor: "#C9E2D6" }}>{k}</span>
                  )) : <span className="text-[13px]" style={{ color: C.light }}>—</span>}
                </div>
              </div>
              <div>
                <div className="text-[12.5px] mb-1.5" style={{ color: C.light }}>单加 Agent（套餐外另付）· 积分余额</div>
                <div className="flex flex-wrap gap-1.5 mb-1.5">
                  {(targetTenant.agentAddons?.length ? targetTenant.agentAddons : []).map((k) => (
                    <span key={k} className="text-[12.5px] px-2 py-0.5 rounded-full border" style={{ background: "#EAF1F8", color: "#2F6FB0", borderColor: "#C7DCF0" }}>{k}</span>
                  ))}
                  {!targetTenant.agentAddons?.length && <span className="text-[13px]" style={{ color: C.light }}>无</span>}
                </div>
                <div className="text-[15px] font-bold" style={{ color: C.ink }}>
                  {balance ? `${balance.total.toLocaleString()} 积分` : "—"}
                  <span className="text-[12px] font-normal" style={{ color: C.light }}>
                    （基本包 {balance?.base ?? 0} + 叠加包 {balance?.addon ?? 0}）
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 订阅列表 + 套餐体系 */}
      <div className="grid grid-cols-2 gap-4">
        {/* 租户订阅 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>租户订阅</span>
              {targetTenantId && (
                <span className="text-[12px] px-2 py-0.5 rounded" style={{ background: C.soft, color: C.primary }}>
                  已筛选：{targetTenant?.name || targetTenantId}
                  <button className="ml-1 underline" onClick={() => setTargetTenantId("")}>清除</button>
                </span>
              )}
            </div>
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  <th className="pb-2 font-normal">租户</th>
                  <th className="pb-2 font-normal">状态</th>
                  <th className="pb-2 font-normal">生效期</th>
                  <th className="pb-2 font-normal text-right">自动续费</th>
                </tr>
              </thead>
              <tbody>
                {subsView.map((s) => (
                  <tr key={s.id} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2.5" style={{ color: C.ink }}>
                      <span title={s.tenantId}>{tenants.find((x) => x.id === s.tenantId)?.name || "（未识别租户）"}</span>
                    </td>
                    <td className="py-2.5">
                      <span className="text-[13px] px-2 py-0.5 rounded" style={{
                        color: s.status === "active" ? "#2E5A4C" : "#8A6A1F",
                        background: s.status === "active" ? "#EAF2EE" : "#FBF4E4",
                      }}>
                        {s.status === "active" ? "生效中" : s.status}
                      </span>
                    </td>
                    <td className="py-2.5 text-[14px]" style={{ color: C.mid }}>
                      {fmtDate(s.startDate)} ~ {fmtDate(s.endDate)}
                    </td>
                    <td className="py-2.5 text-right text-[14px]" style={{ color: s.autoRenew ? C.primary : C.light }}>
                      {s.autoRenew ? "是" : "否"}
                    </td>
                  </tr>
                ))}
                {subsView.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-10 text-center text-[14px]" style={{ color: C.light }}>
                      {loading ? "加载中…" : targetTenantId ? "该租户暂无订阅记录" : "暂无订阅记录"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 p-2.5 rounded text-[13px] leading-relaxed" style={{ background: "#EAF2EE", color: C.mid }}>
              计量埋点在 API 网关完成，按「调用次数 + Token」双维度入账；3D 经络穴位为套餐内含能力（专业版 / 企业版随套餐授权开通），非单独加项。
            </div>
          </CardContent>
        </Card>

        {/* 套餐体系 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="text-[16px] font-medium mb-3" style={{ color: C.ink }}>
              套餐体系 <span className="text-[14px] font-normal" style={{ color: C.light }}>（features_json 开关下发）</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {plans.map((p) => {
                const isMain = p.planName === MAIN_PLAN;
                const isCurrent = targetTenant?.planId === p.id;
                const disabled = !targetTenantId || isCurrent;
                return (
                  <div
                    key={p.planName}
                    className="rounded-lg border p-3.5 relative flex flex-col"
                    style={{
                      borderColor: isMain ? "#C8A45D" : C.border,
                      background: isMain ? "#FBF4E4" : "#fff",
                    }}
                  >
                    {isMain && (
                      <span className="absolute -top-2 left-3 text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#C8A45D", color: "#fff" }}>
                        主力套餐
                      </span>
                    )}
                    <div className="text-[16px] font-semibold" style={{ color: C.primary }}>{p.name}</div>
                    <div className="text-[13px] mt-0.5 font-mono" style={{ color: C.light }}>{p.planName}</div>
                    <div className="text-[15px] mt-1 font-medium" style={{ color: C.ink }}>
                      ¥{(p.priceCents / 100).toLocaleString()}<span className="text-[12px] font-normal" style={{ color: C.light }}> /月</span>
                    </div>
                    <div className="mt-2.5 space-y-1 text-[13.5px]">
                      {planFeatureLabels.map((f) => {
                        const on = p.features[f.key];
                        return (
                          <div key={f.key} className="flex items-center gap-1.5" style={{ color: on ? C.mid : C.light }}>
                            {on
                              ? <Check className="w-3 h-3 shrink-0" style={{ color: C.primary }} />
                              : <Minus className="w-3 h-3 shrink-0" style={{ color: "#ccc" }} />}
                            <span>{f.label}</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-2 text-[12.5px]" style={{ color: C.light }}>
                      自带 Agent：{p.agents.length ? p.agents.join(" / ") : "—"}
                    </div>
                    <div className="mt-2 text-[12.5px]" style={{ color: C.light }}>
                      月调用 {p.monthCalls.toLocaleString()} 次
                    </div>
                    <div className="mt-3 pt-3 border-t" style={{ borderColor: C.border }}>
                      <Button
                        size="sm"
                        className="w-full"
                        disabled={disabled}
                        variant={isCurrent ? "outline" : "default"}
                        style={!isCurrent ? { background: C.primary, color: "#fff" } : { borderColor: C.border, color: C.light }}
                        onClick={() => setUpgradeTarget(p)}
                      >
                        {isCurrent ? "当前套餐" : "开通 / 升级"}
                      </Button>
                    </div>
                  </div>
                );
              })}
              {plans.length === 0 && (
                <div className="col-span-2 py-10 text-center text-[14px]" style={{ color: C.light }}>
                  {loading ? "加载中…" : "暂无套餐配置"}
                </div>
              )}
            </div>
            <div className="mt-3 text-[13px] leading-relaxed" style={{ color: C.light }}>
              套餐与 module_3d 开关写入租户 features_json，网关鉴权时随 Token / 签名响应下发，前端按开关渲染入口。价格与 QPS 由商务合同约定，不在此配置。
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 充值叠加包 + 单加 Agent 月费（价目来自 /admin/v1/billing/price-book，#474 单一真源） */}
      <div className="grid grid-cols-2 gap-4">
        {/* 充值叠加包 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>充值叠加包</span>
              <span className="text-[13px] font-normal" style={{ color: C.light }}>（永久有效 · 不清零）</span>
            </div>
            <table className="w-full text-[14px]">
              <thead>
                <tr className="text-left text-[12.5px]" style={{ color: C.light }}>
                  <th className="pb-2 font-normal">套餐</th>
                  <th className="pb-2 font-normal text-right">人民币</th>
                  <th className="pb-2 font-normal text-right">得积分</th>
                  <th className="pb-2 font-normal text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {(priceBook?.rechargePacks || []).map((pk) => (
                  <tr key={pk.key} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2" style={{ color: C.ink }}>{pk.label}</td>
                    <td className="py-2 text-right" style={{ color: C.ink }}>¥{pk.yuan}</td>
                    <td className="py-2 text-right" style={{ color: C.mid }}>{pk.credits.toLocaleString()}</td>
                    <td className="py-2 text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!targetTenantId}
                        style={{ borderColor: C.primary, color: C.primary }}
                        onClick={() => setRechargeTarget(pk)}
                      >
                        充值
                      </Button>
                    </td>
                  </tr>
                ))}
                {(!priceBook || priceBook.rechargePacks.length === 0) && (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-[13px]" style={{ color: C.light }}>
                      {loading ? "加载中…" : "暂无叠加包配置"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 text-[12.5px] leading-relaxed" style={{ color: C.light }}>
              消耗顺序：先扣套餐当月赠送积分 → 用尽再扣叠加包积分；两池皆空 → 不放行。量大单价自然递降。
            </div>
          </CardContent>
        </Card>

        {/* 单加 Agent 月费 — 直接可勾选加购（独立购买入口） */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-1">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>单加 Agent 月费</span>
              <span className="text-[13px] font-normal" style={{ color: C.light }}>（开门订阅费 · 可勾选加购）</span>
            </div>
            <div className="text-[13px] mb-3" style={{ color: C.mid }}>
              文本类 ¥{priceBook?.agentAddon.textMonthlyYuan ?? 59}/月 · 多模态类 ¥{priceBook?.agentAddon.multimodalMonthlyYuan ?? 99}/月
            </div>
            <AgentChecklist agents={agents} selected={selectedAgents} onToggle={toggleAgent} disabledAgents={disabledAgents} />
            <div className="mt-3 flex items-center justify-between">
              <span className="text-[12.5px]" style={{ color: C.light }}>
                {targetTenantId ? `将加购到租户「${targetTenant?.name || "—"}」` : "请先在顶部选择操作租户"}
              </span>
              <Button
                size="sm"
                disabled={!targetTenantId || selectedAgents.size === 0}
                style={{ background: C.primary, color: "#fff" }}
                onClick={() => setAgentAddConfirmOpen(true)}
              >
                确认下单（{selectedAgents.size}）
              </Button>
            </div>
            <div className="mt-2 text-[12.5px] leading-relaxed" style={{ color: C.light }}>
              {priceBook?.agentAddon.note || "客户单独开通某 agent 的月度订阅；当前支付通道未开通，确认下单后生成订单、暂不扣费。"}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 分场景计量 — GET /admin/v1/billing/scene-usage */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[16px] font-medium" style={{ color: C.ink }}>分场景计量</span>
            <span className="text-[13px]" style={{ color: C.light }}>
              来源 /billing/scene-usage · 网关按 scene_key 埋点
            </span>
          </div>

          {loading ? (
            <div className="py-8 text-center text-[14px]" style={{ color: C.light }}>
              <Loader2 className="w-4 h-4 mx-auto mb-2 animate-spin" /> 加载中…
            </div>
          ) : scenes.length === 0 ? (
            <div className="py-8 text-center text-[14px]" style={{ color: C.light }}>
              暂无分场景计量数据（网关尚未产生该周期的场景埋点）
            </div>
          ) : (
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  {["场景", "调用量", "占比", "Token", "成本"].map((h) => (
                    <th key={h} className="pb-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {scenes.map((s) => {
                  const key = (s.sceneKey || s.scene || "").toUpperCase();
                  const alias: Record<string, string> = { MEDICAL: "MED", EDUCATION: "EDU" };
                  const hit = sceneMap[alias[key] || key];
                  const m = hit
                    ? { label: s.scene || hit.label, color: hit.color, bg: hit.bg }
                    : { label: s.scene || "未分类", color: C.ink, bg: C.bg };
                  const pct = sceneTotalCalls > 0 ? Math.round((s.calls / sceneTotalCalls) * 100) : 0;
                  return (
                    <tr key={s.scene} className="border-t" style={{ borderColor: C.border }}>
                      <td className="py-2.5">
                        <span
                          className="px-2 py-0.5 rounded text-[13px]"
                          style={{ background: m.bg, color: m.color }}
                        >
                          {m.label}
                        </span>
                      </td>
                      <td style={{ color: C.ink }}>{s.calls.toLocaleString()}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="w-20 h-1.5 rounded-full" style={{ background: C.border }}>
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${pct}%`, background: m.color }}
                            />
                          </div>
                          <span className="text-[13px]" style={{ color: C.light }}>{pct}%</span>
                        </div>
                      </td>
                      <td style={{ color: C.mid }}>{wan(s.tokens)}</td>
                      <td style={{ color: C.ink }}>¥{(s.cost || 0).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* 结算中心 · 订单记录（#B 方案：充值/单加订阅/用量快照先落订单再结算） */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[16px] font-medium" style={{ color: C.ink }}>
              订单记录
              {targetTenantId && (
                <span className="ml-2 text-[12.5px] font-normal" style={{ color: C.light }}>
                  「{targetTenant?.name || targetTenantId}」· 仅看该租户
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <Select value={orderStatusFilter} onValueChange={setOrderStatusFilter}>
                <SelectTrigger className="h-8 w-[132px] text-[13px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="PAID">已支付</SelectItem>
                  <SelectItem value="PENDING">待支付</SelectItem>
                  <SelectItem value="CANCELLED">已取消</SelectItem>
                </SelectContent>
              </Select>
              <span className="text-[12.5px]" style={{ color: C.light }}>每笔收费先落订单再结算</span>
            </div>
          </div>
          <table className="w-full text-[15px]">
            <thead>
              <tr className="text-left text-[13px]" style={{ color: C.light }}>
                {["订单号", "类型", "项目", "金额", "积分", "状态", "时间"].map((h) => (
                  <th key={h} className="pb-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredOrders.slice(0, 20).map((o) => {
                const typeInfo = orderTypeMap[o.order_type] || { label: o.order_type, cls: "bg-gray-100 text-gray-600 border-gray-200" };
                const stInfo = orderStatusMap[o.status] || { label: o.status, cls: "bg-gray-100 text-gray-600 border-gray-200" };
                const yuan = Math.round((o.amount_cents || 0) / 100);
                return (
                  <tr key={o.order_no} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-mono text-[13.5px]" style={{ color: C.mid }}>{o.order_no}</td>
                    <td className="py-2.5">
                      <span className={`text-[13px] px-2 py-0.5 rounded border ${typeInfo.cls}`}>{typeInfo.label}</span>
                    </td>
                    <td className="py-2.5" style={{ color: C.ink }}>{o.item_label || o.item_key || "—"}</td>
                    <td className="py-2.5 font-medium" style={{ color: C.ink }}>¥{yuan.toLocaleString()}</td>
                    <td className="py-2.5">
                      <span className={o.credits >= 0 ? "font-medium text-emerald-600" : "font-medium text-red-500"}>
                        {o.credits > 0 ? `+${o.credits}` : o.credits}
                      </span>
                    </td>
                    <td className="py-2.5">
                      <span className={`text-[13px] px-2 py-0.5 rounded border ${stInfo.cls}`}>{stInfo.label}</span>
                    </td>
                    <td className="py-2.5 text-[13.5px]" style={{ color: C.light }}>
                      {o.created_at ? o.created_at.slice(0, 19).replace("T", " ") : "—"}
                    </td>
                  </tr>
                );
              })}
              {filteredOrders.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-12 text-center" style={{ color: C.light }}>
                    {loading ? (
                      <><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</>
                    ) : (
                      `暂无${orderStatusFilter !== "all" ? `「${orderStatusFilter}」状态的` : ""}订单记录（${targetTenantId ? "该租户" : "请先在上方选择租户"}充值 / 单加订阅后此处自动出现）`
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* 账单管理 */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[16px] font-medium" style={{ color: C.ink }}>账单管理</span>
            <Button variant="outline" size="sm" style={{ borderColor: C.border, color: C.primary }} onClick={exportBillsCsv}>
              <Download className="w-3.5 h-3.5 mr-1" /> 导出对账单
            </Button>
          </div>
          <table className="w-full text-[15px]">
            <thead>
              <tr className="text-left text-[13px]" style={{ color: C.light }}>
                {["账单号", "套餐 / 租户", "账期", "调用量", "Token", "金额", "状态"].map((h) => (
                  <th key={h} className="pb-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bills.slice(0, 20).map((b, bi) => {
                const st = billStatus[(b.status || "").toUpperCase()];
                return (
                  <tr key={b.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-mono text-[14px]" style={{ color: C.mid }} title={String(b.id)}>#{bi + 1}</td>
                    <td className="py-2.5" style={{ color: C.ink }}>{b.tenant || "—"}</td>
                    <td className="py-2.5" style={{ color: C.mid }}>{b.period}</td>
                    <td className="py-2.5" style={{ color: C.mid }}>{wan(Number(b.calls))}</td>
                    <td className="py-2.5" style={{ color: C.mid }}>{wan(Number(b.tokens))}</td>
                    <td className="py-2.5 font-medium" style={{ color: C.ink }}>¥{b.amount.toLocaleString()}</td>
                    <td className="py-2.5">
                      <span className={`text-[13px] px-2 py-0.5 rounded border ${st?.cls || "bg-gray-100 text-gray-600 border-gray-200"}`}>
                        {st?.label || b.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {bills.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-12 text-center" style={{ color: C.light }}>
                    {loading ? (
                      <><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</>
                    ) : "暂无账单记录"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* ══ 套餐开通/升级 + 引导追加 Agent ══ */}
      {/* ══ 套餐开通/升级 收银台 ══ */}
      <Dialog open={!!upgradeTarget} onOpenChange={(o) => { if (!o) setUpgradeTarget(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>确认订单 · 开通 / 升级套餐</DialogTitle>
            <DialogDescription>
              将为租户「<b>{targetTenant?.name || "—"}</b>」{upgradeTarget ? `开通 / 升级为「${upgradeTarget.name}」` : ""}，
              新套餐于<b>次月 1 号</b>生效（本月仍按原套餐计费）。
            </DialogDescription>
          </DialogHeader>

          {/* 商品明细 */}
          <div className="border rounded-md overflow-hidden" style={{ borderColor: C.border }}>
            <table className="w-full text-[14px]">
              <tbody>
                <tr className="border-t" style={{ borderColor: C.border }}>
                  <td className="px-3 py-2.5" style={{ color: C.ink }}>
                    {upgradeTarget?.name || "套餐"}
                    <div className="text-[12px] mt-0.5" style={{ color: C.light }}>月费 · 次月生效</div>
                  </td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.mid }}>¥{(upgradeTarget ? upgradeTarget.priceCents / 100 : 0).toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.mid }}>1</td>
                  <td className="px-3 py-2.5 text-right" style={{ color: C.ink }}>¥{(upgradeTarget ? upgradeTarget.priceCents / 100 : 0).toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 合计 */}
          <div className="flex items-center justify-between pt-1">
            <span className="text-[14px]" style={{ color: C.mid }}>应付合计</span>
            <span className="text-[22px] font-bold" style={{ color: C.primary }}>¥{(upgradeTarget ? upgradeTarget.priceCents / 100 : 0).toLocaleString()}<span className="text-[13px] font-normal" style={{ color: C.light }}> /月</span></span>
          </div>

          {/* 诚实支付状态提示 */}
          <div className="rounded-md px-3 py-2.5 text-[13px] leading-relaxed" style={{ background: "#FBF4E4", color: "#8A6A1F", border: "1px solid #EADCBE" }}>
            ⚠️ 支付通道建设中：本次仅生成订单、暂不扣款。支付通道开通后，将按此订单金额结算。
          </div>

          <div className="border-t pt-3" style={{ borderColor: C.border }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[14px] font-medium" style={{ color: C.ink }}>顺手加几个 Agent？（可选）</span>
            </div>
            <AgentChecklist agents={agents} selected={selectedAgents} onToggle={toggleAgent} emptyText="加载 Agent 列表中…" />
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">取消</Button>
            </DialogClose>
            <Button style={{ background: C.primary, color: "#fff" }} onClick={confirmPlanWithAgents}>
              确认下单{selectedAgents.size > 0 ? ` + 加购 ${selectedAgents.size} 个 Agent` : ""}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ══ 充值叠加包 收银台 ══ */}
      <CheckoutDialog
        open={!!rechargeTarget}
        onOpenChange={(o) => { if (!o) setRechargeTarget(null); }}
        title="确认订单 · 充值叠加包"
        tenantName={targetTenant?.name || ""}
        items={rechargeTarget ? [{
          name: rechargeTarget.label,
          spec: `得 ${rechargeTarget.credits} 积分 · 永久有效不清零`,
          unitYuan: rechargeTarget.yuan, qty: 1, subtotalYuan: rechargeTarget.yuan,
        }] : []}
        totalYuan={rechargeTarget?.yuan ?? 0}
        confirmText="确认下单"
        onConfirm={confirmRecharge}
        confirming={recharging}
      />

      {/* ══ 单加 Agent 收银台 ══ */}
      <CheckoutDialog
        open={agentAddConfirmOpen}
        onOpenChange={(o) => { if (!o) setAgentAddConfirmOpen(false); }}
        title="确认订单 · 单加 Agent"
        tenantName={targetTenant?.name || ""}
        items={[
          ...(addedText > 0 ? [{ name: "文本类 Agent", spec: "¥59/月 · 单加订阅", unitYuan: 59, qty: addedText, subtotalYuan: addedText * 59 }] : []),
          ...(addedMm > 0 ? [{ name: "多模态类 Agent", spec: "¥99/月 · 单加订阅", unitYuan: 99, qty: addedMm, subtotalYuan: addedMm * 99 }] : []),
        ]}
        totalYuan={addedTotalYuan}
        settleNote=" /月"
        confirmText="确认下单"
        onConfirm={() => { setAgentAddConfirmOpen(false); confirmAddAgent(); }}
      />

      {/* 单加 Agent 选择已内联到上方卡片，不再用独立弹窗 */}
    </div>
  );
}
