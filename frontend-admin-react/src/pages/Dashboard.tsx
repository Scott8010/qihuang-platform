import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { Building2, Users, Zap, Banknote, ArrowRight, AlertTriangle, Clock, Info, Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import { fetchDashboard, fetchBills, fetchTenantExtended } from "@/lib/api";
import type { CallTrendItem, SceneDistItem, AlertItem, TodoReviewItem, BillItem, DeckTask } from "@/lib/types";
import TaskDeck from "@/components/TaskDeck";

const levelIcon = { high: AlertTriangle, mid: Clock, low: Info };
const levelColor = { high: "#B03A2E", mid: "#8A6A1F", low: "#8FA9A0" };

function fmtNumber(n: number) {
  return n.toLocaleString("zh-CN");
}

export default function Dashboard({ go }: { go: (p: string) => void }) {
  const [loading, setLoading] = useState(true);
  const [totalTenants, setTotalTenants] = useState(0);
  const [activeTenants, setActiveTenants] = useState(0);
  const [totalUsers, setTotalUsers] = useState(0);
  const [apiCalls, setApiCalls] = useState(0);
  const [todayCalls, setTodayCalls] = useState(0);
  const [revenueYuan, setRevenueYuan] = useState(0);
  const [callTrend, setCallTrend] = useState<CallTrendItem[]>([]);
  const [sceneDist, setSceneDist] = useState<SceneDistItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [reviews, setReviews] = useState<TodoReviewItem[]>([]);
  const [bills, setBills] = useState<BillItem[]>([]);
  // 岐黄三境 3D 开通情况：从 fetchTenantExtended 取真实 module_3d 开关统计
  const [m3d, setM3d] = useState<{ total: number; enabled: number; loading: boolean; hadData: boolean }>({ total: 0, enabled: 0, loading: true, hadData: false });

  useEffect(() => {
    let mounted = true;
    fetchBills().then((b) => { if (mounted) setBills(b); });
    // 岐黄三境 3D 真实开通情况：与 dashboard 并行拉，避免再开一次慢查询
    fetchTenantExtended(50).then((list) => {
      if (!mounted) return;
      const total = list.length;
      const enabled = list.filter((t) => t.module3d).length;
      setM3d({ total, enabled, loading: false, hadData: true });
    }).catch(() => { if (mounted) setM3d((s) => ({ ...s, loading: false, hadData: true })); });
    fetchDashboard().then((d) => {
      if (!mounted) return;
      setReviews(d.reviews || []);
      setTotalTenants(d.totalTenants);
      setActiveTenants(d.activeTenants);
      setTotalUsers(d.totalUsers);
      setApiCalls(d.apiCalls);
      setTodayCalls(d.todayCalls);
      setRevenueYuan(d.revenueCents / 100);
      setCallTrend(d.callTrend.length ? d.callTrend : []);
      setSceneDist(d.sceneDist.length ? d.sceneDist : []);
      setAlerts(d.alerts);
      setLoading(false);
    });
    return () => { mounted = false; };
  }, []);

  // 平台应收——真实数据源是 Bill 表 paid/issued 账单的 total_cost_cents 合计。
  // 真零数据时（平台尚未生成任何账单）显式说明，避免被误以为"未接数据/mock"。
  const revenueSub = revenueYuan > 0
    ? `来自套餐订阅 / 用量（${bills.filter((b) => (b.status || "").toUpperCase() === "PAID").length} 张已结清）`
    : "当前为 0——平台尚未生成任何账单（首笔收入待生成账单后入账）";

  const kpis = [
    { label: "租户总数", value: fmtNumber(totalTenants), sub: `活跃 ${fmtNumber(activeTenants)} · 本月新增 —`, icon: Building2, delta: "" },
    { label: "用户总数", value: fmtNumber(totalUsers), sub: "平台累计注册用户", icon: Users, delta: "" },
    { label: "今日调用量", value: fmtNumber(todayCalls), sub: `累计 ${fmtNumber(apiCalls)} 次`, icon: Zap, delta: "" },
    { label: "平台应收（元）", value: `¥${fmtNumber(Math.round(revenueYuan))}`, sub: revenueSub, icon: Banknote, delta: "" },
  ];

  // ── 待办任务：全部由真实信号派生（待审知识 / 逾期账单 / 系统告警），无信号则为空 ──
  const overdueBills = bills.filter((b) => (b.status || "").toUpperCase() === "OVERDUE");
  const deckTasks: DeckTask[] = [
    ...reviews.slice(0, 4).map((r) => ({
      id: `RV-${r.id}`,
      type: "知识审核",
      title: `${r.name} · ${r.type || "待审条目"}`,
      desc: `置信度 ${r.conf ?? "—"}；来源 ${r.source || "未标注"}；建议审核人 ${r.reviewer || "未指派"}`,
      page: "content",
      tone: (Number(r.conf) < 0.6 ? "red" : "amber") as DeckTask["tone"],
      tag: `${reviews.length} 条待审`,
    })),
    ...overdueBills.slice(0, 3).map((b) => ({
      id: `BL-${b.id}`,
      type: "账单逾期",
      title: `${b.tenant || b.tenantId} · ¥${b.amount.toLocaleString()}`,
      desc: `${b.period} 账期已逾期，请跟进催收或办理续费`,
      page: "billing",
      tone: "red" as DeckTask["tone"],
      tag: `${overdueBills.length} 张逾期`,
    })),
    ...alerts.slice(0, 4).map((a, i) => ({
      id: `AL-${i}`,
      type: "系统告警",
      title: a.text,
      desc: `告警级别 ${a.level || "—"}，上报时间 ${a.time || "—"}`,
      page: "monitor",
      tone: (a.level === "high" ? "red" : a.level === "mid" ? "amber" : "green") as DeckTask["tone"],
      tag: `${alerts.length} 条告警`,
    })),
  ];

  return (
    <div className="space-y-5">
      {loading && (
        <div className="flex items-center gap-2 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 正在加载真实业务数据…
        </div>
      )}

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4">
        {kpis.map((k) => (
          <Card key={k.label} className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[15px]" style={{ color: C.light }}>{k.label}</div>
                  <div className="text-[28px] font-bold mt-1 tracking-tight" style={{ color: C.primary }}>{k.value}</div>
                </div>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: C.soft }}>
                  <k.icon className="w-5 h-5" style={{ color: C.primary }} />
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[14px]">
                <span style={{ color: C.mid }}>{k.sub}</span>
                {k.delta && <span style={{ color: C.accent }}>{k.delta}</span>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 调用趋势 */}
        <Card className="col-span-2 border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between">
              <CardTitle className="text-[17px]" style={{ color: C.primary }}>近 30 天 API 调用趋势（分场景）</CardTitle>
              <Button variant="outline" size="sm" onClick={() => go("billing")} className="text-[14px]">
                计量详情 <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="h-[280px] pt-4">
            {callTrend.length === 0 ? (
              <div className="h-full flex items-center justify-center text-[15px]" style={{ color: C.light }}>暂无调用数据</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={callTrend} margin={{ top: 5, right: 10, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: C.light }} tickLine={false} interval={4} />
                  <YAxis tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 10, border: `1px solid ${C.border}` }} />
                  <Area type="monotone" dataKey="大健康" stackId="1" stroke="#2E5A4C" fill="#2E5A4C" fillOpacity={0.75} />
                  <Area type="monotone" dataKey="医疗" stackId="1" stroke="#B03A2E" fill="#B03A2E" fillOpacity={0.7} />
                  <Area type="monotone" dataKey="培训" stackId="1" stroke="#C8A45D" fill="#C8A45D" fillOpacity={0.75} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* 场景分布 + 增值模块 */}
        <Card className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-0">
            <CardTitle className="text-[17px]" style={{ color: C.primary }}>租户场景分布</CardTitle>
          </CardHeader>
          <CardContent className="h-[190px]">
            {sceneDist.length === 0 ? (
              <div className="h-full flex items-center justify-center text-[15px]" style={{ color: C.light }}>暂无租户分布数据</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={sceneDist} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={3}>
                    {sceneDist.map((s) => <Cell key={s.name} fill={s.fill} />)}
                  </Pie>
                  <Legend verticalAlign="bottom" iconSize={9} wrapperStyle={{ fontSize: 12 }} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 10 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
          <div className="mx-5 mb-5 rounded-xl p-3.5" style={{ background: "#FBF4E4" }}>
            <div className="flex items-center justify-between">
              <div className="text-[15px] font-medium" style={{ color: C.gold }}>岐黄三境 · 3D 增值模块</div>
              {/* 套餐绑定（按 8/22 拍板，3D 走套餐门槛无单独加购开关） */}
              <Badge variant="outline" className="text-[13px] border-amber-300" style={{ color: C.gold }}>套餐绑定</Badge>
            </div>
            {m3d.loading ? (
              <div className="text-[14px] mt-1 flex items-center gap-1.5" style={{ color: C.mid }}>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                统计 3D 开通情况中…
              </div>
            ) : m3d.hadData && m3d.total === 0 ? (
              <div className="text-[14px] mt-1" style={{ color: C.mid }}>
                暂无租户数据，待接入 <code className="text-[12px] px-1 rounded" style={{ background: "rgba(0,0,0,.04)" }}>tenants-extended</code> 字段后显示。
              </div>
            ) : m3d.total > 0 && m3d.enabled === 0 ? (
              <div className="text-[14px] mt-1" style={{ color: C.mid }}>
                当前 <b>{m3d.total}</b> 家租户均未开通 3D 模块（需专业版/企业版套餐自动解锁）
              </div>
            ) : (
              <div className="text-[14px] mt-1" style={{ color: C.mid }}>
                已开通 <b style={{ color: C.gold }}>{m3d.enabled}</b> 家 / 共 <b>{m3d.total}</b> 家
                （占比 <b>{m3d.total > 0 ? Math.round((m3d.enabled / m3d.total) * 100) : 0}%</b>）
              </div>
            )}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 告警 */}
        <Card className="col-span-2 border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <CardTitle className="text-[17px]" style={{ color: C.primary }}>运行告警与预警</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {alerts.length === 0 ? (
              <div className="text-[15px]" style={{ color: C.light }}>暂无告警</div>
            ) : (
              alerts.map((a, i) => {
                const Icon = levelIcon[a.level as keyof typeof levelIcon];
                return (
                  <div key={i} className="flex items-start gap-3 rounded-lg px-3 py-2.5" style={{ background: C.bg }}>
                    <Icon className="w-4 h-4 mt-0.5 shrink-0" style={{ color: levelColor[a.level as keyof typeof levelColor] }} />
                    <span className="text-[15px] flex-1" style={{ color: C.ink }}>{a.text}</span>
                    <span className="text-[13px] shrink-0" style={{ color: C.light }}>{a.time}</span>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>

        {/* 待办任务（真实信号派生） */}
        <TaskDeck tasks={deckTasks} go={go} loading={loading} />
      </div>
    </div>
  );
}
