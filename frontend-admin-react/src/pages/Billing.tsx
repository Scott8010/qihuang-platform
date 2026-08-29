import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BarChart3, Download, Check, Minus, Loader2 } from "lucide-react";
import { C, billStatus, planFeatureLabels, sceneMap } from "@/lib/types";
import type { PlanItem, BillItem, SubscriptionItem, SceneUsageItem, PriceBook } from "@/lib/types";
import { fetchBillingStats, fetchPlans, fetchBills, fetchSubscriptions, fetchSceneUsage, fetchPriceBook } from "@/lib/api";
import { CodeCopy } from "@/components/ui/code-copy";

/* ═══════════════════════════════════════════
   计费与套餐 — 真实接口驱动
   KPI    → GET /admin/v1/billing/usage
   套餐   → GET /admin/v1/plans（仅特性开关，后端无价格/QPS）
   账单   → GET /admin/v1/billing/bills
   订阅   → GET /admin/v1/subscriptions
   ═══════════════════════════════════════════ */

const MAIN_PLAN = "professional";   // 主力套餐高亮

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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchBillingStats().then(setStats),
      fetchPlans().then(setPlans),
      fetchBills().then(setBills),
      fetchSubscriptions().then(setSubs),
      fetchSceneUsage().then(setScenes),
      fetchPriceBook().then(setPriceBook),
    ]).finally(() => setLoading(false));
  }, []);

  // 应收 = 账单金额合计（真实派生，不写死）
  const receivable = bills.reduce((a, b) => a + (b.amount || 0), 0);
  const sceneTotalCalls = scenes.reduce((a, s) => a + (s.calls || 0), 0);

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

  const kpiCards = [
    { label: "本月总调用", value: `${wan(stats.totalCalls)} 次`, sub: "来自网关计量埋点" },
    { label: "本月 Token 消耗", value: wan(stats.totalTokens), sub: "共识四模型合计" },
    { label: "本月 LLM 成本", value: `¥${stats.cost.toLocaleString()}`, sub: "按 total_cost_cents 折算" },
    { label: "账单应收合计", value: `¥${receivable.toLocaleString()}`, sub: `${bills.length} 张账单` },
  ];

  return (
    <div className="space-y-4">
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

      {/* 订阅列表 + 套餐体系 */}
      <div className="grid grid-cols-2 gap-4">
        {/* 租户订阅 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>租户订阅</span>
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
                {subs.map((s) => (
                  <tr key={s.id} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2.5" style={{ color: C.ink }}>
                      <CodeCopy value={s.tenantId} short />
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
                {subs.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-10 text-center text-[14px]" style={{ color: C.light }}>
                      {loading ? "加载中…" : "暂无订阅记录"}
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
                return (
                  <div
                    key={p.planName}
                    className="rounded-lg border p-3.5 relative"
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
                      月调用 {p.monthCalls.toLocaleString()} 次
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
                </tr>
              </thead>
              <tbody>
                {(priceBook?.rechargePacks || []).map((pk) => (
                  <tr key={pk.key} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2" style={{ color: C.ink }}>{pk.label}</td>
                    <td className="py-2 text-right" style={{ color: C.ink }}>¥{pk.yuan}</td>
                    <td className="py-2 text-right" style={{ color: C.mid }}>{pk.credits.toLocaleString()}</td>
                  </tr>
                ))}
                {(!priceBook || priceBook.rechargePacks.length === 0) && (
                  <tr>
                    <td colSpan={3} className="py-6 text-center text-[13px]" style={{ color: C.light }}>
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

        {/* 单加 Agent 月费 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>单加 Agent 月费</span>
              <span className="text-[13px] font-normal" style={{ color: C.light }}>（开门订阅费）</span>
            </div>
            <div className="space-y-1 text-[14px]">
              <div className="flex items-center justify-between py-2 border-t" style={{ borderColor: C.border }}>
                <span style={{ color: C.mid }}>文本类 Agent</span>
                <span className="font-medium" style={{ color: C.ink }}>¥{priceBook?.agentAddon.textMonthlyYuan ?? 59}/月</span>
              </div>
              <div className="flex items-center justify-between py-2 border-t" style={{ borderColor: C.border }}>
                <span style={{ color: C.mid }}>多模态类 Agent</span>
                <span className="font-medium" style={{ color: C.ink }}>¥{priceBook?.agentAddon.multimodalMonthlyYuan ?? 99}/月</span>
              </div>
            </div>
            <div className="mt-3 text-[12.5px] leading-relaxed" style={{ color: C.light }}>
              {priceBook?.agentAddon.note || "客户单独开通某 agent 的月度订阅；调用仍按 token 吞积分池，先赠后充。"}
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
              {bills.slice(0, 20).map((b) => {
                const st = billStatus[(b.status || "").toUpperCase()];
                return (
                  <tr key={b.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-mono text-[14px]" style={{ color: C.mid }}>{String(b.id).slice(0, 12)}</td>
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
    </div>
  );
}
