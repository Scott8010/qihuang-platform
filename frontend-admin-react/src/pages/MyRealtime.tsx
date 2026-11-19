import { useEffect, useState, useCallback } from "react";
import {
  Activity, RefreshCw, Loader2, Zap, Coins, Clock, BarChart3, CheckCircle2, XCircle,
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { C } from "@/lib/types";
import { bjTime } from "@/pages/MyTickets";
import {
  fetchMyRealtimeUsage, type RealtimeUsageOverview,
} from "@/lib/api";

/** 机构端「实时消耗」——最近 N 分钟真业务 AI 调用（billable 口径，与 usage/billing 同源）。
 *  截图里的"ECS 实例 CPU/内存"是服务器监控假数，这里按老板拍板换成真实调用消耗明细。 */

const yuan = (cents: number) =>
  `¥${(cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function MyRealtime() {
  const [data, setData] = useState<RealtimeUsageOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [minutes, setMinutes] = useState(60);

  const load = useCallback(async (m: number, isRefresh = false) => {
    isRefresh ? setRefreshing(true) : setLoading(true);
    const d = await fetchMyRealtimeUsage(m);
    setData(d);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(minutes); }, [minutes, load]);

  return (
    <div className="space-y-6">
      {/* 顶部：标题 + 窗口切换 + 刷新 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5" style={{ color: C.primary }} />
          <h2 className="text-[17px] font-semibold" style={{ color: C.ink }}>实时消耗情况</h2>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[12px]" style={{ color: C.light }}>
            {data?.updated_at ? `更新于 ${bjTime(data.updated_at).slice(11, 16)}` : "—"}
          </span>
          <div className="flex rounded-lg overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
            {[60, 30, 10].map((m) => (
              <button key={m} onClick={() => setMinutes(m)}
                className="px-3 py-1.5 text-[12px]"
                style={minutes === m
                  ? { background: C.primary, color: "#fff" }
                  : { background: "#fff", color: C.mid }}>
                近{m}分钟
              </button>
            ))}
          </div>
          <button onClick={() => load(minutes, true)} disabled={refreshing}
            className="px-3 py-1.5 rounded-lg text-[13px] inline-flex items-center gap-1.5"
            style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.primary }}>
            <RefreshCw className={`w-3.5 h-5${refreshing ? " animate-spin" : ""}`} style={{ height: 14 }} />
            刷新
          </button>
        </div>
      </div>

      <div className="text-[13px] rounded-lg px-3 py-2" style={{ background: C.soft, color: C.mid }}>
        仅统计真实 AI 能力调用（登录后台、浏览页面不计入）。下列数据按当前机构隔离，与「使用情况」「账单与配额」口径一致。
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin mr-2" />加载实时消耗...
        </div>
      ) : !data ? (
        <div className="rounded-xl p-8 text-center text-[15px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
          实时消耗暂不可用，请稍后刷新或联系客户经理。
        </div>
      ) : (
        <>
          {/* 4 张概览卡 */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: "窗口内调用", value: data.summary.calls.toLocaleString(), unit: "次", icon: Activity, color: C.primary },
              { label: "消耗 Token", value: data.summary.tokens.toLocaleString(), unit: "", icon: Zap, color: "#3B6FC4" },
              { label: "消费金额", value: yuan(data.summary.cost_cents), unit: "", icon: Coins, color: C.gold },
              { label: "平均响应", value: data.summary.avg_latency_ms.toLocaleString(), unit: "ms", icon: Clock, color: "#7B5EA7" },
            ].map((k) => {
              const Icon = k.icon;
              return (
                <div key={k.label} className="rounded-xl p-4 bg-white" style={{ border: `1px solid ${C.border}` }}>
                  <div className="flex items-center gap-2 text-[12px]" style={{ color: C.light }}>
                    <Icon className="w-3.5 h-3.5" style={{ color: k.color }} />{k.label}
                  </div>
                  <div className="text-[22px] font-semibold mt-2" style={{ color: C.ink }}>
                    {k.value}<span className="text-[12px] ml-1 font-normal" style={{ color: C.light }}>{k.unit}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 每分钟调用流柱状图 */}
          <section className="rounded-xl p-5 bg-white" style={{ border: `1px solid ${C.border}` }}>
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <h3 className="text-[15px] font-semibold" style={{ color: C.ink }}>调用流（按分钟）</h3>
              <span className="text-[12px]" style={{ color: C.light }}>最近 {data.window_minutes} 分钟</span>
            </div>
            {data.timeline.length === 0 ? (
              <div className="py-10 text-center text-[13px]" style={{ color: C.light }}>窗口内暂无 AI 调用</div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.timeline} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
                  <XAxis dataKey="minute" tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="calls" name="调用次数" fill={C.primary} radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </section>

          {/* 按 Agent 消耗明细表（替代截图的 ECS 实例表） */}
          <section className="rounded-xl bg-white overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
            <div className="px-5 py-4" style={{ borderBottom: `1px solid ${C.border}` }}>
              <h3 className="text-[15px] font-semibold" style={{ color: C.ink }}>能力消耗明细</h3>
              <p className="text-[12px] mt-0.5" style={{ color: C.light }}>按 AI 能力拆分窗口内的真实调用、Token 与消费</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead>
                  <tr style={{ background: C.bg, color: C.light }}>
                    <th className="text-left px-5 py-3 font-medium">能力</th>
                    <th className="text-right px-4 py-3 font-medium">调用次数</th>
                    <th className="text-right px-4 py-3 font-medium">Token</th>
                    <th className="text-right px-4 py-3 font-medium">消费</th>
                    <th className="text-left px-4 py-3 font-medium">占比</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_agent.length === 0 ? (
                    <tr><td colSpan={5} className="text-center py-8" style={{ color: C.light }}>窗口内暂无能力调用</td></tr>
                  ) : data.by_agent.map((a) => {
                    const pct = data.summary.cost_cents > 0
                      ? Math.round(a.cost_cents / data.summary.cost_cents * 100) : 0;
                    return (
                      <tr key={a.agent} style={{ borderTop: `1px solid ${C.border}` }}>
                        <td className="px-5 py-3">
                          <div className="font-medium" style={{ color: C.ink }}>{a.name}</div>
                          <div className="text-[11px]" style={{ color: C.light }}>{a.agent}</div>
                        </td>
                        <td className="text-right px-4 py-3" style={{ color: C.mid }}>{a.calls.toLocaleString()}</td>
                        <td className="text-right px-4 py-3" style={{ color: C.mid }}>{a.tokens.toLocaleString()}</td>
                        <td className="text-right px-4 py-3" style={{ color: C.ink }}>{yuan(a.cost_cents)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-1.5 rounded-full overflow-hidden" style={{ background: C.bg }}>
                              <div className="h-full rounded-full" style={{ width: `${pct}%`, background: C.primary }} />
                            </div>
                            <span className="text-[12px]" style={{ color: C.mid }}>{pct}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* 最近调用明细 */}
          {data.recent.length > 0 && (
            <section className="rounded-xl bg-white overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
              <div className="px-5 py-4" style={{ borderBottom: `1px solid ${C.border}` }}>
                <h3 className="text-[15px] font-semibold" style={{ color: C.ink }}>最近调用</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr style={{ background: C.bg, color: C.light }}>
                      <th className="text-left px-5 py-2.5 font-medium">时间</th>
                      <th className="text-left px-4 py-2.5 font-medium">能力</th>
                      <th className="text-right px-4 py-2.5 font-medium">Token</th>
                      <th className="text-right px-4 py-2.5 font-medium">响应</th>
                      <th className="text-right px-4 py-2.5 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent.slice(0, 10).map((r, i) => (
                      <tr key={i} style={{ borderTop: `1px solid ${C.border}` }}>
                        <td className="px-5 py-2.5" style={{ color: C.mid }}>{r.time ? bjTime(r.time).slice(11, 16) : "—"}</td>
                        <td className="px-4 py-2.5" style={{ color: C.ink }}>{r.name}</td>
                        <td className="text-right px-4 py-2.5" style={{ color: C.mid }}>{r.tokens.toLocaleString()}</td>
                        <td className="text-right px-4 py-2.5" style={{ color: C.mid }}>{r.latency_ms ?? "—"}ms</td>
                        <td className="text-right px-4 py-2.5">
                          {r.status_code && r.status_code < 400
                            ? <CheckCircle2 className="w-4 h-4 inline" style={{ color: C.primary }} />
                            : <XCircle className="w-4 h-4 inline" style={{ color: "#B03A2E" }} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
