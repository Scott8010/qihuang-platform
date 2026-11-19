import { useState, useEffect } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Loader2, CreditCard, TrendingUp, Download, ReceiptText,
  BellRing, FileText, Info, CalendarClock, Coins,
} from "lucide-react";
import { C } from "@/lib/types";
import { fetchMyBillingOverview, type BillingOverview } from "@/lib/api";

/**
 * MyBilling — 机构管理员「账单与配额」（参考 tenant-portal 设计稿布局，数据全真）。
 * 布局：3 张总览卡（本月消费/账户余额/当前套餐）→ 近6月消费柱状图+导出 →
 *       费用构成（按 agent）+ 续费提醒/发票记录两栏。
 * 数据唯一来源：/admin/v1/my/billing-overview（后端按 token 租户强制收窄）。
 * 口径（2026-11-19 A）：只算真业务 AI 调用；发票后端无真实表，明确标占位不造假。
 * 1 积分 = ¥0.05 = 5 分，cost_cents 为真扣费分。
 */
const yuan = (cents: number) => `¥${(cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const AGENT_LABEL: Record<string, string> = {
  "health-advisor": "中医健康顾问",
  "health-assistant": "花花健康助手",
  "tongue": "AI 舌诊",
  "constitution": "体质辨识",
  "compliance": "内容合规",
  "fortune": "命理咨询",
  "geo": "地理风水",
  "insight": "健康洞察",
  "store-coach": "门店经营教练",
  "coach": "健康教练",
  "content-writer": "内容创作",
};
const agentLabel = (k: string) => AGENT_LABEL[k] || k;

/** 到期日 → 剩余天数文案 */
function renewHint(expires: string | null): { text: string; urgent: boolean } {
  if (!expires) return { text: "未获取到到期时间", urgent: false };
  const end = new Date(expires.includes("T") ? expires : expires + "T00:00:00").getTime();
  const days = Math.ceil((end - Date.now()) / 86400000);
  if (Number.isNaN(days)) return { text: `到期 ${expires.slice(0, 10)}`, urgent: false };
  if (days < 0) return { text: `已到期 ${Math.abs(days)} 天，请联系续费`, urgent: true };
  if (days <= 30) return { text: `剩余 ${days} 天，建议尽快续费`, urgent: true };
  return { text: `到期 ${expires.slice(0, 10)} · 剩余 ${days} 天`, urgent: false };
}

export default function MyBilling() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<BillingOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    fetchMyBillingOverview().then((d) => {
      if (!alive) return;
      setData(d);
      if (!d) setError("账单数据暂时无法读取，请稍后重试或联系客服。");
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  /** 导出近6月消费 CSV（真实数据，不造假） */
  const exportCsv = () => {
    if (!data) return;
    const rows = [
      ["月份", "消费金额(元)", "调用次数"],
      ...data.monthly_trend.map((m) => [m.period, (m.cost_cents / 100).toFixed(2), String(m.calls)]),
    ];
    const csv = "\uFEFF" + rows.map((r) => r.join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `账单消费_${data.month.period}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64" style={{ color: C.light }}>
      <Loader2 className="w-5 h-5 animate-spin mr-2" /> 账单数据加载中...
    </div>;
  }

  const credits = data?.credits || { base: 0, addon: 0, total: 0 };
  const plan = data?.plan || {
    name: "", plan_id: "", expires: null, quota_calls: 0, used_calls: 0,
    pending_plan: null, pending_effective_date: null,
  };
  const month = data?.month || { period: "", cost_cents: 0, calls: 0 };
  const trend = data?.monthly_trend || [];
  const breakdown = data?.cost_breakdown || [];
  const renew = renewHint(plan.expires);
  const quotaPct = plan.quota_calls > 0 ? Math.min(100, Math.round((plan.used_calls / plan.quota_calls) * 100)) : 0;
  const totalBreakdown = breakdown.reduce((s, x) => s + x.cost_cents, 0);
  const chartData = trend.map((m) => ({ month: m.period.slice(5) + "月", amount: +(m.cost_cents / 100).toFixed(2), calls: m.calls }));

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-lg px-4 py-3 text-[14px]" style={{ background: "#FDECEA", color: "#B03A2E", border: "1px solid #F5C6C0" }}>
          {error}
        </div>
      )}

      {/* 口径说明 */}
      <div className="rounded-lg px-4 py-2.5 text-[13px] flex items-start gap-2"
        style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        <Info className="w-4 h-4 mt-0.5 shrink-0" style={{ color: C.primary }} />
        <span>账单只统计<b style={{ color: C.primary }}>真实 AI 能力调用</b>产生的消费；登录后台、浏览页面等操作不计费。账户余额为可用积分，1 积分 ≈ ¥0.05。</span>
      </div>

      {/* 总览三卡 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-[14px]" style={{ color: C.mid }}>
              <TrendingUp className="w-4 h-4" style={{ color: C.primary }} /> 本月累计消费
            </div>
            <div className="mt-3 text-[30px] font-bold tabular" style={{ color: C.primary }}>{yuan(month.cost_cents)}</div>
            <div className="mt-1 text-[13px]" style={{ color: C.light }}>账单周期 {month.period || "—"}</div>
          </CardContent>
        </Card>
        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-[14px]" style={{ color: C.mid }}>
              <Coins className="w-4 h-4" style={{ color: C.accent }} /> 账户余额
            </div>
            <div className="mt-3 text-[30px] font-bold tabular" style={{ color: C.primary }}>
              {credits.total.toLocaleString("zh-CN")}<span className="text-[15px] font-normal ml-1">积分</span>
            </div>
            <div className="mt-1 text-[13px]" style={{ color: C.light }}>
              基础包 {credits.base.toLocaleString()} · 加购包 {credits.addon.toLocaleString()}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-[14px]" style={{ color: C.mid }}>
              <CreditCard className="w-4 h-4" style={{ color: C.primary }} /> 当前套餐
            </div>
            <div className="mt-3 text-[26px] font-bold" style={{ color: C.primary }}>{plan.name || "—"}</div>
            <div className="mt-1 text-[13px]" style={{ color: renew.urgent ? "#B03A2E" : C.light }}>
              {renew.text}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 配额进度条 */}
      {plan.quota_calls > 0 && (
        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardContent className="p-5">
            <div className="flex justify-between text-[14px] mb-2">
              <span style={{ color: C.mid }}>本月调用配额</span>
              <span className="tabular" style={{ color: C.primary }}>
                已用 {plan.used_calls.toLocaleString()} / {plan.quota_calls.toLocaleString()} 次（{quotaPct}%）
              </span>
            </div>
            <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: C.border }}>
              <div className="h-full rounded-full" style={{ width: `${quotaPct}%`, background: C.primary }} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* 近6月消费趋势 */}
      <Card className="rounded-xl" style={{ borderColor: C.border }}>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-[17px]" style={{ color: C.primary }}>近 6 个月消费趋势</CardTitle>
          <Button variant="outline" size="sm" onClick={exportCsv} disabled={!data}
            className="text-[13px]" style={{ borderColor: C.border, color: C.mid }}>
            <Download className="w-4 h-4 mr-1.5" /> 导出账单
          </Button>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <div className="h-52 flex items-center justify-center text-[14px]" style={{ color: C.light }}>暂无消费记录</div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                  <XAxis dataKey="month" tick={{ fill: C.light, fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: C.light, fontSize: 12 }} axisLine={false} tickLine={false} width={52}
                    tickFormatter={(v) => `¥${v}`} />
                  <Tooltip
                    cursor={{ fill: C.soft }}
                    formatter={(v: number, _n: string, p: any) => [`${yuan(v)} · ${p.payload.calls} 次`, "消费"]}
                    contentStyle={{ borderColor: C.border, borderRadius: 10, fontSize: 13 }}
                  />
                  <Bar dataKey="amount" fill={C.primary} radius={[6, 6, 0, 0]} isAnimationActive={false} maxBarSize={46} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 费用构成 */}
      <Card className="rounded-xl" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[17px]" style={{ color: C.primary }}>本月费用构成</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {breakdown.length === 0 ? (
            <div className="py-6 text-center text-[14px]" style={{ color: C.light }}>本月暂无 AI 能力消费</div>
          ) : breakdown.map((b) => {
            const pct = totalBreakdown > 0 ? Math.round((b.cost_cents / totalBreakdown) * 100) : 0;
            return (
              <div key={b.agent}>
                <div className="flex justify-between items-baseline mb-1.5">
                  <div>
                    <span className="text-[14px] font-medium" style={{ color: C.ink }}>{agentLabel(b.agent)}</span>
                    <span className="text-[12px] ml-2" style={{ color: C.light }}>{b.calls} 次调用</span>
                  </div>
                  <div className="tabular">
                    <span className="text-[15px] font-semibold" style={{ color: C.primary }}>{yuan(b.cost_cents)}</span>
                    <span className="text-[12px] ml-2" style={{ color: C.light }}>{pct}%</span>
                  </div>
                </div>
                <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: C.soft }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, background: C.primary }} />
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* 续费提醒 + 发票记录 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <CardTitle className="text-[17px] flex items-center gap-2" style={{ color: C.primary }}>
              <BellRing className="w-[18px] h-[18px]" /> 续费提醒
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-lg p-3.5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
              <div className="flex justify-between items-center">
                <span className="text-[14px] font-medium" style={{ color: C.ink }}>{plan.name || "当前套餐"}</span>
                <span className="text-[12px] px-2 py-0.5 rounded-full"
                  style={{ background: renew.urgent ? "#FDF0E4" : "#fff", color: renew.urgent ? "#B03A2E" : C.mid }}>
                  {renew.text}
                </span>
              </div>
              <div className="mt-1.5 text-[12px]" style={{ color: C.light }}>
                到期时间 {plan.expires ? plan.expires.slice(0, 10) : "—"} · 本月已用 {plan.used_calls} 次
              </div>
            </div>
            {plan.pending_plan && (
              <div className="rounded-lg p-3.5" style={{ border: `1px dashed ${C.border}` }}>
                <div className="text-[14px]" style={{ color: C.mid }}>
                  待生效升级：<b style={{ color: C.primary }}>{plan.pending_plan}</b>
                  <span className="ml-2 text-[12px]" style={{ color: C.light }}>{plan.pending_effective_date} 生效</span>
                </div>
              </div>
            )}
            <div className="text-[12px] leading-relaxed" style={{ color: C.light }}>
              续费或调整套餐请联系客服，我们会在到期前协助你完成升级。
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-xl" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <CardTitle className="text-[17px] flex items-center gap-2" style={{ color: C.primary }}>
              <ReceiptText className="w-[18px] h-[18px]" /> 发票记录
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-lg p-5 text-center" style={{ background: C.soft, border: `1px dashed ${C.border}` }}>
              <FileText className="w-8 h-8 mx-auto mb-2" style={{ color: C.light }} />
              <div className="text-[14px] font-medium" style={{ color: C.mid }}>发票自助查询暂未开放</div>
              <div className="mt-1.5 text-[13px] leading-relaxed" style={{ color: C.light }}>
                {data?.invoice_note || "发票由平台财务统一开具，如需开票请联系客服。"}
              </div>
            </div>
            <div className="mt-3 flex items-start gap-2 text-[12px]" style={{ color: C.light }}>
              <CalendarClock className="w-4 h-4 mt-0.5 shrink-0" />
              <span>开票申请提交后，一般 3-5 个工作日内开具并邮件发送。</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
