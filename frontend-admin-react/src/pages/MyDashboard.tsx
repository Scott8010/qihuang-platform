import { useState, useEffect } from "react";
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, ArrowRight, KeyRound, Ticket, Activity, Zap, Wallet, Sparkles, Users } from "lucide-react";
import { C } from "@/lib/types";
import {
  getIdentity, fetchWalletBalance, fetchAgentUsage, fetchApiKeys,
  fetchTenantExtended, fetchTenantInsights, fetchMyTickets,
} from "@/lib/api";

/**
 * MyDashboard — 机构管理员登录后的「数据看板」（参考 tenant-portal 设计稿布局）。
 * 布局：欢迎条 → 4 张 KPI 卡 → 调用趋势面积图 + 能力分布饼图 → 服务状态 + 快捷入口。
 * 数据全部来自本租户真实接口（后端按 token 租户强制收窄），平台自身成本不计入。
 */
export default function MyDashboard({ go }: { go: (p: string) => void }) {
  const identity = getIdentity();
  const tenantId = identity?.tenant_id || "";
  const userName = identity?.display_name || identity?.username || "管理员";
  const orgName = identity?.tenant_name || "我的机构";
  const roleName = (identity?.roles || []).includes("super_admin") ? "平台超级管理员"
    : (identity?.roles || []).includes("tenant_admin") ? "租户管理员"
    : (identity?.roles || []).includes("org_admin") ? "机构管理员"
    : (identity?.roles || []).includes("admin") ? "管理员" : "管理员";
  const greeting = (() => {
    const h = new Date().getHours();
    return h < 6 ? "夜深了" : h < 11 ? "早上好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
  })();

  const [loading, setLoading] = useState(true);
  const [wallet, setWallet] = useState<{ base: number; addon: number; total: number } | null>(null);
  const [totalCalls, setTotalCalls] = useState(0);
  const [keyCount, setKeyCount] = useState(0);
  const [openTickets, setOpenTickets] = useState(0);
  const [myPlan, setMyPlan] = useState<{ plan: string; quotaCalls: number; usedCalls: number; userCount: number } | null>(null);
  const [insights, setInsights] = useState<{
    trend: { date: string; calls: number }[];
    ability: { name: string; value: number; color: string; calls: number }[];
    totalCalls: number; successRate: number;
  }>({ trend: [], ability: [], totalCalls: 0, successRate: 0 });
  const [range, setRange] = useState(30);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [w, u, k, all, ins, tk] = await Promise.all([
        fetchWalletBalance(tenantId),
        fetchAgentUsage(tenantId, 30),
        fetchApiKeys(tenantId),
        fetchTenantExtended(100),
        fetchTenantInsights(range),
        fetchMyTickets(undefined, 1, 100),
      ]);
      const mine = all.find((t) => t.id === tenantId);
      if (!alive) return;
      setWallet(w);
      setTotalCalls(u.totalCalls);
      setKeyCount(k.filter((x) => x.status === "ACTIVE").length);
      setOpenTickets(tk.items.filter((t) => !["resolved", "closed"].includes(t.status)).length);
      setInsights(ins);
      if (mine) setMyPlan({
        plan: mine.plan || "—", quotaCalls: mine.quotaCalls || 0,
        usedCalls: mine.usedCalls || 0, userCount: mine.users || 0,
      });
      setLoading(false);
    })();
    return () => { alive = false; };
  }, [tenantId, range]);

  const quotaPct = myPlan && myPlan.quotaCalls > 0
    ? Math.min(100, Math.round((myPlan.usedCalls / myPlan.quotaCalls) * 100)) : 0;

  const kpis = [
    { label: "本月调用量", value: totalCalls.toLocaleString("zh-CN"), sub: myPlan && myPlan.quotaCalls > 0 ? `配额 ${myPlan.quotaCalls.toLocaleString("zh-CN")} · 已用 ${quotaPct}%` : "按积分计费", icon: Zap },
    { label: "积分余额", value: wallet ? wallet.total.toLocaleString("zh-CN") : "—", sub: wallet ? `基础 ${wallet.base} · 叠加 ${wallet.addon}` : "钱包数据", icon: Wallet },
    { label: "当前套餐", value: myPlan?.plan || (loading ? "读取中" : "—"), sub: "决定可用的 AI 能力", icon: Sparkles },
    { label: "团队人数", value: String(myPlan?.userCount ?? "—"), sub: `有效密钥 ${keyCount} 把`, icon: Users },
  ];

  return (
    <div className="space-y-5">
      {loading && (
        <div className="flex items-center gap-2 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 正在加载我的数据…
        </div>
      )}

      {/* 欢迎条 */}
      <div className="flex flex-wrap items-end justify-between gap-3 rounded-xl p-5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div>
          <div className="text-[20px] font-bold" style={{ color: C.primary }}>{greeting}，{userName}</div>
          <div className="text-[13px] mt-1" style={{ color: C.mid }}>{orgName} · {roleName}</div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => go("myusage")} className="text-[13px]" style={{ borderColor: C.border, color: C.mid }}>
            查看用量明细
          </Button>
          <Button size="sm" onClick={() => go("mytickets")} className="text-[13px]" style={{ background: C.primary }}>
            <Ticket className="w-4 h-4 mr-1" /> 提交工单
          </Button>
        </div>
      </div>

      {/* 4 张 KPI 卡 */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {kpis.map((k) => (
          <Card key={k.label} className="border shadow-sm" style={{ borderColor: C.border }}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <span className="text-[13px]" style={{ color: C.light }}>{k.label}</span>
                <span className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: C.soft }}>
                  <k.icon className="w-4 h-4" style={{ color: C.primary }} />
                </span>
              </div>
              <div className="mt-3 text-[25px] font-semibold tabular tracking-tight" style={{ color: C.primary }}>{k.value}</div>
              <div className="mt-1 text-[12px]" style={{ color: C.mid }}>{k.sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 趋势 + 能力分布 */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="border shadow-sm xl:col-span-2" style={{ borderColor: C.border }}>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>调用量趋势</CardTitle>
            <div className="flex rounded-lg p-0.5" style={{ background: C.bg }}>
              {[7, 30, 90].map((d) => (
                <button key={d} onClick={() => setRange(d)} className="px-3 py-1 text-[12px] rounded-md transition-colors"
                  style={range === d ? { background: "#fff", color: C.primary, fontWeight: 600 } : { color: C.mid }}>
                  {d} 天
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            <div className="h-64">
              {insights.trend.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={insights.trend} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="tenantCalls" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={C.primary} stopOpacity={0.28} />
                        <stop offset="100%" stopColor={C.primary} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={C.border} />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 10, border: `1px solid ${C.border}` }} />
                    <Area type="monotone" dataKey="calls" name="调用次数" stroke={C.primary} strokeWidth={2} fill="url(#tenantCalls)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-[14px]" style={{ color: C.light }}>
                  近 {range} 天暂无调用数据
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-sm" style={{ borderColor: C.border }}>
          <CardHeader className="pb-0"><CardTitle className="text-[16px]" style={{ color: C.primary }}>能力调用分布</CardTitle></CardHeader>
          <CardContent>
            <div className="h-48">
              {insights.ability.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={insights.ability} dataKey="value" nameKey="name" innerRadius="56%" outerRadius="86%" paddingAngle={2} strokeWidth={0} isAnimationActive={false}>
                      {insights.ability.map((a) => <Cell key={a.name} fill={a.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 10, border: `1px solid ${C.border}` }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-[14px]" style={{ color: C.light }}>暂无数据</div>
              )}
            </div>
            <ul className="mt-1 space-y-2">
              {insights.ability.slice(0, 4).map((a) => (
                <li key={a.name} className="flex items-center gap-2 text-[13px]">
                  <span className="w-2.5 h-2.5 rounded" style={{ background: a.color }} />
                  <span className="flex-1 truncate" style={{ color: C.mid }}>{a.name}</span>
                  <span className="tabular" style={{ color: C.ink }}>{a.value}%</span>
                </li>
              ))}
              {!insights.ability.length && <li className="text-[13px]" style={{ color: C.light }}>调用后再来看分布</li>}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* 服务状态 + 快捷入口 */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="border shadow-sm xl:col-span-2" style={{ borderColor: C.border }}>
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>调用健康度</CardTitle>
            <span className="text-[12px]" style={{ color: C.light }}>近 {range} 天</span>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between rounded-lg px-4 py-3" style={{ background: C.bg }}>
              <div className="flex items-center gap-3">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" />
                <span className="text-[14px]" style={{ color: C.ink }}>AI 能力接口</span>
              </div>
              <span className="text-[14px] font-semibold tabular" style={{ color: insights.successRate >= 95 ? C.primary : "#B03A2E" }}>
                {insights.totalCalls ? `成功率 ${insights.successRate}%` : "暂无调用"}
              </span>
            </div>
            <div className="text-[13px] leading-relaxed" style={{ color: C.mid }}>
              共发起 <b style={{ color: C.primary }}>{insights.totalCalls.toLocaleString("zh-CN")}</b> 次调用，
              成功 <b style={{ color: C.primary }}>{insights.totalCalls ? Math.round(insights.totalCalls * insights.successRate / 100).toLocaleString("zh-CN") : 0}</b> 次。
              想看每次调用的时间、接口和消耗，点上方「查看用量明细」。
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-sm" style={{ borderColor: C.border }}>
          <CardHeader className="pb-3"><CardTitle className="text-[16px]" style={{ color: C.primary }}>快捷入口</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <button onClick={() => go("mykeys")} className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left hover:opacity-80" style={{ background: C.bg }}>
              <KeyRound className="w-4 h-4" style={{ color: C.primary }} />
              <span className="flex-1 text-[14px]" style={{ color: C.ink }}>我的密钥</span>
              <span className="text-[13px] tabular" style={{ color: C.mid }}>{keyCount}</span>
              <ArrowRight className="w-3.5 h-3.5" style={{ color: C.light }} />
            </button>
            <button onClick={() => go("mytickets")} className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left hover:opacity-80" style={{ background: C.bg }}>
              <Ticket className="w-4 h-4" style={{ color: C.primary }} />
              <span className="flex-1 text-[14px]" style={{ color: C.ink }}>工单中心</span>
              <span className="text-[13px] tabular" style={{ color: openTickets ? "#B03A2E" : C.mid }}>{openTickets}</span>
              <ArrowRight className="w-3.5 h-3.5" style={{ color: C.light }} />
            </button>
            <button onClick={() => go("mylogs")} className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left hover:opacity-80" style={{ background: C.bg }}>
              <Activity className="w-4 h-4" style={{ color: C.primary }} />
              <span className="flex-1 text-[14px]" style={{ color: C.ink }}>使用日志</span>
              <ArrowRight className="w-3.5 h-3.5" style={{ color: C.light }} />
            </button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
