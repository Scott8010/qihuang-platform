import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { Building2, Users, Zap, Banknote, ArrowRight, AlertTriangle, Clock, Info } from "lucide-react";
import { C, callTrend, sceneDist, alerts } from "@/lib/mock";
import TaskDeck from "@/components/TaskDeck";

const kpis = [
  { label: "租户总数", value: "8", sub: "医疗 3 · 大健康 3 · 培训 2", icon: Building2, delta: "本月 +2" },
  { label: "活跃用户（日）", value: "3,214", sub: "C端 2,860 / B端 354", icon: Users, delta: "环比 +12.4%" },
  { label: "今日调用量", value: "11,842", sub: "AI Token 41.2 万", icon: Zap, delta: "环比 +6.8%" },
  { label: "本月应收（元）", value: "120,400", sub: "已收 24,000 / 逾期 39,800", icon: Banknote, delta: "账期 2026-07" },
];

const levelIcon = { high: AlertTriangle, mid: Clock, low: Info };
const levelColor = { high: "#B03A2E", mid: "#8A6A1F", low: "#8FA9A0" };

export default function Dashboard({ go }: { go: (p: string) => void }) {
  return (
    <div className="space-y-5">
      {/* KPI */}
      <div className="grid grid-cols-4 gap-4">
        {kpis.map((k) => (
          <Card key={k.label} className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[13px]" style={{ color: C.light }}>{k.label}</div>
                  <div className="text-[26px] font-bold mt-1 tracking-tight" style={{ color: C.primary }}>{k.value}</div>
                </div>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: C.soft }}>
                  <k.icon className="w-5 h-5" style={{ color: C.primary }} />
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between text-[12px]">
                <span style={{ color: C.mid }}>{k.sub}</span>
                <span style={{ color: C.accent }}>{k.delta}</span>
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
              <CardTitle className="text-[15px]" style={{ color: C.primary }}>近 30 天 API 调用趋势（分场景）</CardTitle>
              <Button variant="outline" size="sm" onClick={() => go("billing")} className="text-[12px]">
                计量详情 <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="h-[280px] pt-4">
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
          </CardContent>
        </Card>

        {/* 场景分布 + 增值模块 */}
        <Card className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-0">
            <CardTitle className="text-[15px]" style={{ color: C.primary }}>租户场景分布</CardTitle>
          </CardHeader>
          <CardContent className="h-[190px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={sceneDist} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={3}>
                  {sceneDist.map((s) => <Cell key={s.name} fill={s.fill} />)}
                </Pie>
                <Legend verticalAlign="bottom" iconSize={9} wrapperStyle={{ fontSize: 12 }} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 10 }} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
          <div className="mx-5 mb-5 rounded-xl p-3.5" style={{ background: "#FBF4E4" }}>
            <div className="flex items-center justify-between">
              <div className="text-[13px] font-medium" style={{ color: C.gold }}>岐黄三境 · 3D 增值模块</div>
              <Badge variant="outline" className="text-[11px] border-amber-300" style={{ color: C.gold }}>加购项</Badge>
            </div>
            <div className="text-[12px] mt-1" style={{ color: C.mid }}>已开通租户 3 家 · 本月组件加载 8,412 次</div>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 告警 */}
        <Card className="col-span-2 border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <CardTitle className="text-[15px]" style={{ color: C.primary }}>运行告警与预警</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {alerts.map((a, i) => {
              const Icon = levelIcon[a.level as keyof typeof levelIcon];
              return (
                <div key={i} className="flex items-start gap-3 rounded-lg px-3 py-2.5" style={{ background: C.bg }}>
                  <Icon className="w-4 h-4 mt-0.5 shrink-0" style={{ color: levelColor[a.level as keyof typeof levelColor] }} />
                  <span className="text-[13px] flex-1" style={{ color: C.ink }}>{a.text}</span>
                  <span className="text-[11px] shrink-0" style={{ color: C.light }}>{a.time}</span>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* 多任务卡片堆 */}
        <TaskDeck go={go} />
      </div>
    </div>
  );
}
