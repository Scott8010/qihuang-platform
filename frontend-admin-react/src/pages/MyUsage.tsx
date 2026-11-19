import { useState, useEffect } from "react";
import { RefreshCw, Search, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { C } from "@/lib/types";
import {
  getIdentity, fetchAgentUsage, fetchWalletBalance, fetchTenantExtended,
  fetchMyCallLogs,
} from "@/lib/api";
import { bjTime } from "./MyTickets";

/**
 * MyUsage — 机构管理员的「使用情况」（参考 tenant-portal 设计稿 Usage 布局）。
 * 配额概览卡（真实配额/余额）→ 调用明细表（my/call-logs，按 token 租户收窄）。
 */
export default function MyUsage() {
  const identity = getIdentity();
  const tenantId = identity?.tenant_id || "";
  const [loading, setLoading] = useState(true);
  const [quota, setQuota] = useState<{ plan: string; used: number; total: number } | null>(null);
  const [wallet, setWallet] = useState<{ total: number } | null>(null);
  const [cost, setCost] = useState(0);
  const [abilityCount, setAbilityCount] = useState(0);
  const [logs, setLogs] = useState<{ id: string; timestamp: string | null; endpoint: string; method: string; status_code: number; latency_ms: number; tokens_used: number; cost_cents: number; app_key: string }[]>([]);
  const [kw, setKw] = useState("");
  const [days, setDays] = useState(30);
  const [refreshedAt, setRefreshedAt] = useState("");
  const [spinning, setSpinning] = useState(false);

  const load = async (d: number) => {
    setLoading(true);
    const [all, w, u, lg] = await Promise.all([
      fetchTenantExtended(100), fetchWalletBalance(tenantId),
      fetchAgentUsage(tenantId, d), fetchMyCallLogs({ days: d, page: 1, page_size: 100 }),
    ]);
    const mine = all.find((t) => t.id === tenantId);
    setQuota(mine ? {
      plan: mine.plan || "—", used: mine.usedCalls || 0, total: mine.quotaCalls || 0,
    } : null);
    setWallet(w);
    setCost(u.totalCostYuan);
    setAbilityCount(u.usage.length);
    setLogs(lg.items);
    setRefreshedAt(bjTime(new Date().toISOString()));
    setLoading(false);
  };

  useEffect(() => { load(days); /* eslint-disable-next-line */ }, [tenantId, days]);

  const refresh = async () => {
    setSpinning(true);
    await load(days);
    setSpinning(false);
  };

  const filtered = logs.filter((l) =>
    !kw || (l.endpoint || "").toLowerCase().includes(kw.toLowerCase()) || (l.app_key || "").toLowerCase().includes(kw.toLowerCase())
  );

  const quotaPct = quota && quota.total > 0 ? Math.min(100, Math.round((quota.used / quota.total) * 100)) : 0;
  const tone = (pct: number) => pct >= 85 ? "#B03A2E" : pct >= 65 ? "#C8A45D" : C.primary;

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        这里只统计<b style={{ color: C.primary }}>你自己的调用</b>。平台自身跑 AI 的成本由平台承担，不计入你的用量与账单。
      </div>

      {/* 配额概览卡 */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[16px] font-semibold" style={{ color: C.primary }}>配额使用概览</h2>
          <span className="text-[12px]" style={{ color: C.light }}>当前套餐：{quota?.plan || "—"}</span>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card className="border shadow-sm" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium" style={{ color: C.ink }}>调用次数</span>
                <span className="text-[13px] font-semibold tabular" style={{ color: tone(quotaPct) }}>{quotaPct}%</span>
              </div>
              <p className="mt-0.5 text-[12px]" style={{ color: C.light }}>本计费周期</p>
              <div className="mt-3"><Progress value={quotaPct} /></div>
              <p className="mt-2 text-[12px] tabular" style={{ color: C.mid }}>
                {quota && quota.total > 0 ? `已用 ${quota.used.toLocaleString("zh-CN")} / ${quota.total.toLocaleString("zh-CN")} 次` : "按实际用量结算，无上限"}
              </p>
            </CardContent>
          </Card>
          <Card className="border shadow-sm" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium" style={{ color: C.ink }}>积分余额</span>
              </div>
              <p className="mt-0.5 text-[12px]" style={{ color: C.light }}>可用于调用抵扣</p>
              <div className="mt-3 text-[24px] font-semibold tabular" style={{ color: C.primary }}>{wallet ? wallet.total.toLocaleString("zh-CN") : "—"}</div>
              <p className="mt-1 text-[12px]" style={{ color: C.mid }}>用完可联系平台补充</p>
            </CardContent>
          </Card>
          <Card className="border shadow-sm" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium" style={{ color: C.ink }}>近 {days} 天消费</span>
              </div>
              <p className="mt-0.5 text-[12px]" style={{ color: C.light }}>真实调用聚合</p>
              <div className="mt-3 text-[24px] font-semibold tabular" style={{ color: C.primary }}>¥{cost.toFixed(2)}</div>
              <p className="mt-1 text-[12px]" style={{ color: C.mid }}>1 积分 ≈ ¥0.05</p>
            </CardContent>
          </Card>
          <Card className="border shadow-sm" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium" style={{ color: C.ink }}>使用能力数</span>
              </div>
              <p className="mt-0.5 text-[12px]" style={{ color: C.light }}>近 {days} 天有调用</p>
              <div className="mt-3 text-[24px] font-semibold tabular" style={{ color: C.primary }}>{abilityCount}</div>
              <p className="mt-1 text-[12px]" style={{ color: C.mid }}>种 AI 能力</p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* 调用明细表 */}
      <Card className="border shadow-sm" style={{ borderColor: C.border }}>
        <CardHeader className="space-y-3 pb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>调用明细</CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-[12px]" style={{ color: C.light }}>更新于 {refreshedAt}</span>
              <Button variant="outline" size="sm" onClick={refresh} disabled={spinning} className="text-[13px]" style={{ borderColor: C.border }}>
                <RefreshCw className={`w-3.5 h-3.5 mr-1 ${spinning ? "animate-spin" : ""}`} /> 刷新
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-lg p-0.5" style={{ background: C.bg }}>
              {[7, 30, 90].map((d) => (
                <button key={d} onClick={() => setDays(d)} className="px-3 py-1 text-[12px] rounded-md" style={days === d ? { background: "#fff", color: C.primary, fontWeight: 600 } : { color: C.mid }}>{d} 天</button>
              ))}
            </div>
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
              <input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="按接口 / 密钥搜索"
                className="h-8 w-56 pl-8 pr-3 text-[13px] rounded-lg border outline-none" style={{ borderColor: C.border, background: C.bg }} />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-14 text-[14px]" style={{ color: C.light }}><Loader2 className="w-4 h-4 animate-spin mr-2" />加载中…</div>
          ) : (
            <div className="overflow-x-auto"><table className="w-full text-[13px]">
              <thead><tr className="text-left" style={{ color: C.light, background: C.bg }}>
                {["时间", "接口", "状态", "耗时", "Tokens", "费用", "密钥"].map((h) => <th key={h} className="py-3 px-4 font-normal whitespace-nowrap first:pl-6 last:pr-6">{h}</th>)}
              </tr></thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={7} className="py-12 text-center" style={{ color: C.light }}>没有匹配的调用记录</td></tr>
                )}
                {filtered.map((l) => (
                  <tr key={l.id} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-3 px-4 pl-6 whitespace-nowrap tabular" style={{ color: C.mid }}>{bjTime(l.timestamp)}</td>
                    <td className="py-3 px-4 max-w-[240px] truncate" style={{ color: C.ink }} title={l.endpoint}>{l.endpoint}</td>
                    <td className="py-3 px-4"><span className="px-2 py-0.5 rounded text-[12px]" style={{ background: l.status_code < 400 ? C.soft : "#FDECEA", color: l.status_code < 400 ? C.primary : "#B03A2E" }}>{l.status_code}</span></td>
                    <td className="py-3 px-4 tabular" style={{ color: C.mid }}>{l.latency_ms}ms</td>
                    <td className="py-3 px-4 tabular" style={{ color: C.mid }}>{(l.tokens_used || 0).toLocaleString("zh-CN")}</td>
                    <td className="py-3 px-4 tabular" style={{ color: C.mid }}>¥{((l.cost_cents || 0) / 100).toFixed(3)}</td>
                    <td className="py-3 px-4 pr-6 tabular" style={{ color: C.light }}>{l.app_key || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
