import { useEffect, useState, type ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Bot, Boxes, RefreshCw, Check, Loader2, Network, Gauge, Plug,
  CircleDot, AlertTriangle, Stethoscope, X, BarChart3, Activity, Users,
  Coins, HeartPulse, Zap, Server, PenLine, Copy,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { C } from "@/lib/types";
import {
  fetchAgentCenter, toggleAgent, fetchAgentDashboard, fetchPlanAgentMatrix, setPlanAgents,
  getIdentity, consultHealthAdvisor, consultStoreCoach,
  fetchDashboard, fetchSceneUsage, fetchAgentUsage, fetchAgentBusinessSignals,
  fetchHealthAssistantPrompt, saveHealthAssistantPrompt,
  fetchTenantOrgs, fetchOrgHealthAssistantPrompt, saveOrgHealthAssistantPrompt,
  type AgentDef, type PlanAgentRow, type HealthAdvisorConsultResult, type AgentBusinessSignals,
} from "@/lib/api";

/* ═══════════════════════════════════════════
   Agent 中台（智能控制面）
   构件 A 资源池（注册 / 运营态热插拔启停）
   构件 B 套餐专家团组合编排
   构件 C 各 Agent 运营看板（中台派发，内核在底层）
   全部对接后端 /admin/v1/agents* 与 /admin/v1/plans/{id}/agents
   ═══════════════════════════════════════════ */

const stateLabel: Record<string, string> = {
  blocked: "已拦截", review: "待复核", pending: "待处理", passed: "已通过",
};
const stateColor: Record<string, string> = {
  blocked: "#B03A2E", review: "#8A6A1F", pending: "#C8A45D", passed: "#2E5A4C",
};

/** 活态化 P1-B · 业务实证采纳榜（自取数据，独立于主组件） */
const BIZ_TYPE_LABEL: Record<string, string> = {
  formula: "方剂", herb: "草药", syndrome: "证候", disease: "疾病",
};

function BusinessSignalsPanel() {
  const [data, setData] = useState<AgentBusinessSignals | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetchAgentBusinessSignals().then((d) => { setData(d); setLoading(false); });
  }, []);
  return (
    <section>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Zap className="w-4 h-4" style={{ color: C.accent }} />
        <span className="text-[16px] font-medium" style={{ color: C.ink }}>活态化 P1-B · 业务实证采纳榜</span>
        <span className="text-[13px] px-1.5 py-0.5 rounded-full" style={{ background: "#FBF4E4", color: "#8A6A1F" }}>回路三</span>
        {data && !data.signal_enabled && (
          <span className="text-[13px] px-1.5 py-0.5 rounded-full" style={{ background: "#F1EFE8", color: "#5F5E5A" }}>回灌未激活</span>
        )}
      </div>
      <Card className="border" style={{ borderColor: C.border }}>
        <CardContent className="p-4 space-y-3">
          <div className="text-[13.5px]" style={{ color: C.light }}>
            聚合 health-advisor 每次成功 consult 的实体引用日志（consult_attribution），反映「哪些知识点被真实业务采纳」。
            开关 <span className="font-mono">LIVING_BUSINESS_SIGNAL_ENABLED=true</span> 后，该信号即回灌知识置信度加权，系统「越用越聪明」。
          </div>
          {loading ? (
            <div className="py-6 text-center text-[14px]" style={{ color: C.light }}><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</div>
          ) : !data || data.totals.references === 0 ? (
            <div className="py-6 text-center text-[14px]" style={{ color: C.light }}>暂无业务实证数据（真实/仿真 consult 产生引用日志后才会出现）</div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2 text-[13.5px]" style={{ color: C.mid }}>
                <span className="px-2 py-1 rounded" style={{ background: C.soft, color: C.primary }}>近 {data.window_days} 天引用 {data.totals.references} 次</span>
                <span className="px-2 py-1 rounded" style={{ background: C.soft, color: C.primary }}>涉及知识点 {data.totals.distinct_kg} 个</span>
              </div>
              <div className="space-y-1.5">
                {data.top.map((s, i) => (
                  <div key={s.kg_id} className="flex items-center gap-2 rounded-md border px-2.5 py-2" style={{ borderColor: C.border, background: "#FCFCFA" }}>
                    <span className="shrink-0 w-5 h-5 rounded-full text-[12.5px] font-bold flex items-center justify-center" style={{ background: C.primary, color: "#fff" }}>{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[14.5px] font-medium truncate" style={{ color: C.ink }}>{s.entity_name || s.kg_id}</div>
                      <div className="text-[13px] font-mono truncate" style={{ color: C.light }}>{s.kg_id}</div>
                    </div>
                    {s.entity_type && (
                      <span className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#F5EDD9", color: "#8A6A1F" }}>{BIZ_TYPE_LABEL[s.entity_type] || s.entity_type}</span>
                    )}
                    <span className="text-[14px] font-semibold" style={{ color: C.primary }}>{s.ref_count} 次</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export default function AgentCenter() {
  const [agents, setAgents] = useState<AgentDef[]>([]);
  const [loading, setLoading] = useState(true);

  // 构件 C：看板
  const [dashKey, setDashKey] = useState<string | null>(null);
  const [dash, setDash] = useState<any>(null);
  const [dashLoading, setDashLoading] = useState(false);

  // 构件 B：套餐专家团矩阵
  const [matrix, setMatrix] = useState<PlanAgentRow[]>([]);
  const [matrixLoading, setMatrixLoading] = useState(true);
  const [editPlan, setEditPlan] = useState<string | null>(null);
  const [editAgents, setEditAgents] = useState<string[]>([]);
  const [savingPlan, setSavingPlan] = useState<string | null>(null);

  // 在线试用：当前展开试用的 agent_key（null=收起）
  const [trialFor, setTrialFor] = useState<string | null>(null);

  // 喂料口：健康助手营销语料弹窗（当前打开的 agent_key，null=关闭）
  const [promptFor, setPromptFor] = useState<string | null>(null);
  const [promptRefreshKey, setPromptRefreshKey] = useState(0);

  const loadAgents = () => fetchAgentCenter().then((d) => setAgents(d.agents));
  const loadMatrix = () => fetchPlanAgentMatrix().then(setMatrix);

  useEffect(() => {
    Promise.all([loadAgents(), loadMatrix()]).finally(() => {
      setLoading(false); setMatrixLoading(false);
    });
  }, []);

  const handleToggle = async (a: AgentDef) => {
    const next = a.status === "active" ? "inactive" : "active";
    const r = await toggleAgent(a.agent_key, next);
    if (r.ok) { await loadAgents(); }
    else { alert(r.msg || "启停失败"); }
  };

  // 喂料口：打开营销语料弹窗（当前登录管理员所在租户为语料归属）
  const openPrompt = (agentKey: string) => {
    setPromptFor(agentKey);
    setPromptRefreshKey((k) => k + 1);
  };

  const openDash = async (key: string) => {
    setDashKey(key); setDash(null); setDashLoading(true);
    const r = await fetchAgentDashboard(key);
    setDashLoading(false);
    if (r.ok) setDash(r.dashboard); else setDash({ __error: r.msg || "看板拉取失败" });
  };

  const startEdit = (row: PlanAgentRow) => { setEditPlan(row.planId); setEditAgents([...row.agents]); };
  const cancelEdit = () => { setEditPlan(null); setEditAgents([]); };
  const saveEdit = async (planId: string) => {
    setSavingPlan(planId);
    const r = await setPlanAgents(planId, editAgents);
    setSavingPlan(null);
    if (r.ok) { setEditPlan(null); setEditAgents([]); await loadMatrix(); }
    else { alert(r.msg || "保存失败"); }
  };

  const planName = (id: string) => matrix.find((m) => m.planId === id)?.planName || id;

  return (
    <div className="space-y-5">
      {/* 顶部说明 */}
      <div className="text-[14px]" style={{ color: C.mid }}>
        Agent 中台把「可嵌入业务流的能力模块」作为一等资源统一管理：<b>资源池</b>注册能力并支持运营态热插拔启停，
        <b>套餐专家团</b>把能力打包进套餐，<b>各 Agent 看板</b>派发底层运营数据。新增能力只需注册 + 挂载路由。
      </div>

      {/* ═══ 构件 0：Agent 中台 · 运营驾驶舱 ═══ */}
      <AgentOverview />

      {/* ═══ 构件 0.5：活态化 P1-B · 业务实证采纳榜（回路三） ═══ */}
      <BusinessSignalsPanel />

      {/* ═══ 构件 A：能力资源池 ═══ */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Boxes className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[16px] font-medium" style={{ color: C.ink }}>能力资源池（构件 A）</span>
            <span className="text-[13px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
              {agents.length}
            </span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={() => loadAgents()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
          </Button>
        </div>

        {loading ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-8 text-center"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {agents.map((a) => {
              const active = a.status === "active";
              return (
                <Card key={a.agent_key} className="border shadow-none" style={{ borderColor: C.border }}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: active ? C.soft : "#F0F0F0" }}>
                          <Bot className="w-4 h-4" style={{ color: active ? C.primary : C.light }} />
                        </div>
                        <div>
                          <div className="text-[16px] font-medium" style={{ color: C.ink }}>{a.name}</div>
                          <div className="text-[13px] font-mono" style={{ color: C.light }}>{a.agent_key}</div>
                        </div>
                      </div>
                      <span className="text-[13px] px-2 py-0.5 rounded-full" style={{
                        background: active ? "#EAF2EE" : "#F0F0F0",
                        color: active ? "#2E5A4C" : C.light,
                      }}>{active ? "启用中" : "已停用"}</span>
                    </div>

                    {a.desc && <p className="text-[14px] leading-relaxed mb-2" style={{ color: C.mid }}>{a.desc}</p>}

                    <div className="flex flex-wrap gap-1.5 mb-2">
                      <span className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#F5F5F5", color: C.mid }}>
                        {a.category}
                      </span>
                      {a.engine && (
                        <span className="text-[12px] px-1.5 py-0.5 rounded font-mono" style={{ background: "#F5F5F5", color: C.mid }}>
                          {a.engine}
                        </span>
                      )}
                      {a.capabilities.map((c) => (
                        <span key={c} className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: C.soft, color: C.primary }}>
                          {c}
                        </span>
                      ))}
                    </div>

                    <div className="text-[13px] mb-3" style={{ color: C.light }}>
                      已纳入 <b style={{ color: C.mid }}>{a.included_in_plans.length}</b> 个套餐专家团
                      {a.included_in_plans.length > 0 && (
                        <span className="ml-1 font-mono">{a.included_in_plans.map(planName).join("、")}</span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <Button size="sm" className="h-7 text-[14px]" style={{ background: active ? "#8A6A1F" : C.primary }}
                        onClick={() => handleToggle(a)}>
                        <Plug className="w-3.5 h-3.5 mr-1" /> {active ? "停用" : "启用"}
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[14px]"
                        onClick={() => openDash(a.agent_key)}>
                        <Gauge className="w-3.5 h-3.5 mr-1" /> 看板
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[14px]"
                        style={trialFor === a.agent_key ? { borderColor: C.primary, color: C.primary } : undefined}
                        onClick={() => setTrialFor(trialFor === a.agent_key ? null : a.agent_key)}>
                        <Stethoscope className="w-3.5 h-3.5 mr-1" />
                        {trialFor === a.agent_key ? "收起" : "在线试用"}
                      </Button>
                      {a.agent_key === "health-assistant" && (
                        <Button size="sm" variant="outline" className="h-7 text-[14px]"
                          style={promptFor ? { borderColor: C.primary, color: C.primary } : undefined}
                          onClick={() => openPrompt(a.agent_key)}>
                          <PenLine className="w-3.5 h-3.5 mr-1" /> 营销语料
                        </Button>
                      )}
                    </div>

                    {/* 在线试用展开区（内嵌在能力卡片上） */}
                    {trialFor === a.agent_key && (
                      <div className="mt-3 pt-3 border-t" style={{ borderColor: C.border }}>
                        <AgentTrial agent={a} onClose={() => setTrialFor(null)} />
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
            {agents.length === 0 && (
              <Card className="border col-span-full" style={{ borderColor: C.border }}>
                <CardContent className="p-8 text-center" style={{ color: C.light }}>
                  <Boxes className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <div className="text-[15px]">资源池为空，部署期注册能力后将在此呈现</div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </section>

      {/* ═══ 构件 B：套餐专家团组合 ═══ */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Network className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[16px] font-medium" style={{ color: C.ink }}>套餐专家团组合（构件 B）</span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={() => loadMatrix()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
          </Button>
        </div>

        {matrixLoading ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-8 text-center"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</CardContent>
          </Card>
        ) : (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-4 space-y-3">
              {matrix.map((row) => {
                const editing = editPlan === row.planId;
                return (
                  <div key={row.planId} className="border-t first:border-t-0 pt-3 first:pt-0" style={{ borderColor: C.border }}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <CircleDot className="w-3.5 h-3.5" style={{ color: C.primary }} />
                        <span className="text-[15px] font-medium" style={{ color: C.ink }}>{row.planName}</span>
                        <span className="text-[13px] font-mono" style={{ color: C.light }}>{row.planId}</span>
                        <span className="text-[13px]" style={{ color: C.light }}>· {row.agents.length} 个能力</span>
                      </div>
                      {!editing ? (
                        <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={() => startEdit(row)}>编辑组合</Button>
                      ) : (
                        <div className="flex gap-2">
                          <Button size="sm" className="h-7 text-[14px]" style={{ background: C.primary }}
                            disabled={savingPlan === row.planId} onClick={() => saveEdit(row.planId)}>
                            {savingPlan === row.planId ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-1" />} 保存
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={cancelEdit}>取消</Button>
                        </div>
                      )}
                    </div>

                    {editing ? (
                      <div className="flex flex-wrap gap-2">
                        {agents.length === 0 && <span className="text-[14px]" style={{ color: C.light }}>资源池暂无可用能力</span>}
                        {agents.map((a) => {
                          const on = editAgents.includes(a.agent_key);
                          return (
                            <button key={a.agent_key} onClick={() =>
                              setEditAgents((prev) => on ? prev.filter((x) => x !== a.agent_key) : [...prev, a.agent_key])
                            }
                              className="flex items-center gap-1.5 text-[14px] px-2.5 py-1 rounded-full border transition-colors"
                              style={{
                                borderColor: on ? C.primary : C.border,
                                background: on ? C.soft : "white",
                                color: on ? C.primary : C.mid,
                              }}
                            >
                              {on ? <Check className="w-3 h-3" /> : <Plug className="w-3 h-3" />}
                              {a.name}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {row.agents.length === 0 ? (
                          <span className="text-[14px]" style={{ color: C.light }}>未打包任何 Agent 能力</span>
                        ) : row.agents.map((k) => (
                          <span key={k} className="text-[13px] px-2 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
                            {agents.find((a) => a.agent_key === k)?.name || k}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
              {matrix.length === 0 && (
                <div className="text-center py-8" style={{ color: C.light }}>
                  <Network className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <div className="text-[15px]">暂无套餐数据</div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </section>

      {/* ═══ 构件 C：各 Agent 看板 ═══ */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Gauge className="w-4 h-4" style={{ color: C.primary }} />
          <span className="text-[16px] font-medium" style={{ color: C.ink }}>各 Agent 运营看板（构件 C）</span>
        </div>
        {!dashKey ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-8 text-center" style={{ color: C.light }}>
              <Gauge className="w-8 h-8 mx-auto mb-2 opacity-40" />
              <div className="text-[15px]">在上方资源池点击「看板」查看对应能力的运营数据</div>
            </CardContent>
          </Card>
        ) : dashLoading ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-8 text-center"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />看板加载中…</CardContent>
          </Card>
        ) : dash ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[15px] font-medium" style={{ color: C.ink }}>{dashKey} 运营看板</span>
                <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={() => openDash(dashKey!)}>
                  <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
                </Button>
              </div>

              {dash.__error ? (
                <div className="text-[15px] text-red-600 flex items-center gap-2"><AlertTriangle className="w-4 h-4" />{dash.__error}</div>
              ) : (
                <>
                  {/* 指标卡 */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    {dash.total !== undefined && (
                      <Metric label="总量" value={String(dash.total)} color={C.primary} />
                    )}
                    {dash.states && Object.entries(dash.states as Record<string, number>).map(([k, v]) => (
                      <Metric key={k} label={stateLabel[k] || k} value={String(v)} color={stateColor[k] || C.mid} />
                    ))}
                  </div>

                  {/* 近期记录 */}
                  {Array.isArray(dash.recent) && dash.recent.length > 0 && (
                    <div>
                      <div className="text-[14px] mb-2" style={{ color: C.light }}>近期记录（最新 {dash.recent.length} 条）</div>
                      <table className="w-full text-[14px]">
                        <thead>
                          <tr className="text-left text-[13px]" style={{ color: C.light }}>
                            {["标识", "状态", "动作", "时间"].map((h) => <th key={h} className="pb-1.5 font-normal">{h}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {dash.recent.map((m: any, i: number) => (
                            <tr key={i} className="border-t" style={{ borderColor: C.border }}>
                              <td className="py-2 font-mono" style={{ color: C.mid }}>{m.material_key || m.key || "—"}</td>
                              <td className="py-2">
                                <span className="text-[13px] px-1.5 py-0.5 rounded" style={{
                                  background: (stateColor[m.state] ? stateColor[m.state] : C.mid) + "22",
                                  color: stateColor[m.state] || C.mid,
                                }}>{stateLabel[m.state] || m.state || "—"}</span>
                              </td>
                              <td className="py-2" style={{ color: C.mid }}>{m.action_taken || m.action || "—"}</td>
                              <td className="py-2 text-[13px]" style={{ color: C.light }}>{m.updated_at || m.created_at || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* 兜底：非合规结构时展示原始 JSON */}
                  {dash.total === undefined && !dash.states && (
                    <pre className="text-[13px] bg-[#F8FAF9] rounded-lg p-3 overflow-auto max-h-64" style={{ color: C.mid }}>
                      {JSON.stringify(dash, null, 2)}
                    </pre>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        ) : null}
      </section>

      {/* 喂料口：健康助手营销语料弹窗（B 端后台可视化编辑） */}
      {promptFor && (
        <HealthAssistantPromptModal
          key={promptRefreshKey}
          tenantId={getIdentity()?.tenant_id || ""}
          onClose={() => setPromptFor(null)}
        />
      )}
      </div>
  );
}

function Metric({ label, value, color, sub, icon, dark }: {
  label: string; value: string; color: string; sub?: string; icon?: ReactNode; dark?: boolean;
}) {
  return (
    <div className="rounded-xl px-4 py-3.5 relative overflow-hidden"
      style={dark
        ? { background: `linear-gradient(135deg, #22312B 0%, #2E5A4C 60%, #3D7363 100%)`, boxShadow: "0 6px 18px rgba(34,49,43,0.18)" }
        : { background: "white", border: "1px solid " + C.border }}>
      {dark && (
        <div className="absolute -right-4 -top-6 w-20 h-20 rounded-full opacity-20" style={{ background: "#C8A45D" }} />
      )}
      <div className="flex items-center justify-between mb-1">
        <span className="text-[13px]" style={{ color: dark ? "rgba(255,255,255,0.65)" : C.light }}>{label}</span>
        {icon && <span style={{ color: dark ? "rgba(255,255,255,0.8)" : color }}>{icon}</span>}
      </div>
      <div className="text-[28px] leading-tight font-semibold tracking-tight"
        style={{ color: dark ? "#F3F6F4" : color }}>
        {value}
      </div>
      {sub && (
        <div className="text-[12px] mt-0.5" style={{ color: dark ? "rgba(255,255,255,0.55)" : C.light }}>{sub}</div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   构件 0：Agent 中台 · 运营驾驶舱
   数据 100% 平台自身真实计量：
   - 4 指标卡 / 7日趋势 / 服务健康 ← /admin/v1/dashboard（真实 DB 聚合）
   - 场景调用分布 ← /admin/v1/billing/scene-usage（CallLog 本月）
   - Agent 活跃度排行 ← /admin/v1/agents/usage（CallLog 近7日）
   ═══════════════════════════════════════════ */

const SCENE_COLORS: Record<string, string> = { HEALTH: "#2E5A4C", MED: "#B03A2E", EDU: "#C8A45D" };
const SCENE_NAMES: Record<string, string> = { HEALTH: "大健康", MED: "医疗", EDU: "培训" };

function AgentOverview() {
  const [dash, setDash] = useState<any>(null);
  const [sceneUsage, setSceneUsage] = useState<any[]>([]);
  const [agentUsage, setAgentUsage] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([fetchDashboard(), fetchSceneUsage(), fetchAgentUsage()])
      .then(([d, s, u]) => { setDash(d); setSceneUsage(s); setAgentUsage(u.usage || []); })
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  // 近7日趋势：callTrend 三段求和还原真实每日调用
  const trend = (dash?.callTrend || []).map((t: any) => ({
    day: t.day,
    calls: (t["大健康"] || 0) + (t["医疗"] || 0) + (t["培训"] || 0),
  }));

  // 场景调用分布（本月真实 CallLog）
  const sceneData = (sceneUsage || [])
    .map((s: any) => ({
      name: SCENE_NAMES[s.sceneKey] || s.scene || "未分类",
      value: s.calls || 0,
      fill: SCENE_COLORS[s.sceneKey] || "#8FA9A0",
    }))
    .filter((x: any) => x.value > 0);

  // Agent 活跃度排行（近7日真实计量，按调用降序）
  const usageData = (agentUsage || []).slice(0, 8);

  const services = dash?.services || [];
  const okCount = services.filter((s: any) => s.ok).length;
  const llmStatus = services[services.length - 1]?.status || "—";
  const fmt = (n: number) => (n >= 10000 ? (n / 10000).toFixed(1) + "w" : n.toLocaleString());

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4" style={{ color: C.primary }} />
          <span className="text-[16px] font-medium" style={{ color: C.ink }}>Agent 中台 · 运营驾驶舱</span>
          <span className="text-[12px] px-1.5 py-0.5 rounded-full font-mono" style={{ background: C.soft, color: C.primary }}>
            真实计量
          </span>
        </div>
        <Button size="sm" variant="outline" className="h-7 text-[14px]" onClick={load}>
          <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
        </Button>
      </div>

      {loading ? (
        <Card className="border" style={{ borderColor: C.border }}>
          <CardContent className="p-10 text-center"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />驾驶舱加载中…</CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {/* 4 大指标（真实 DB 计量） */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Metric dark label="今日 API 调用" value={fmt(dash?.todayCalls || 0)} color="#F3F6F4"
              sub={`累计 ${fmt(dash?.apiCalls || 0)} 次`} icon={<Zap className="w-3.5 h-3.5" />} />
            <Metric label="活跃租户" value={String(dash?.activeTenants || 0)} color={C.primary}
              sub={`本月新增 ${dash?.newThisMonth ?? 0} 家`} icon={<Users className="w-3.5 h-3.5" />} />
            <Metric label="本月应收" value={`¥${fmt(Math.round((dash?.revenueCents || 0) / 100))}`} color="#8A6A1F"
              sub="账单计价（分累计）" icon={<Coins className="w-3.5 h-3.5" />} />
            <Metric label="服务健康" value={`${okCount}/${services.length}`}
              color={services.length && okCount === services.length ? "#2E5A4C" : "#B03A2E"}
              sub={services.length ? `LLM 集群 · ${llmStatus}` : "暂无服务数据"}
              icon={<Server className="w-3.5 h-3.5" />} />
          </div>

          {/* 图表区 1：趋势 + 场景分布 */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            <Card className="border lg:col-span-7" style={{ borderColor: C.border }}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <BarChart3 className="w-3.5 h-3.5" style={{ color: C.primary }} />
                  <span className="text-[14px] font-medium" style={{ color: C.ink }}>近 7 日 API 调用趋势</span>
                  <span className="text-[12px]" style={{ color: C.light }}>每日真实调用次数</span>
                </div>
                <div className="h-44">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trend} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#2E5A4C" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="#2E5A4C" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E3ECE8" vertical={false} />
                      <XAxis dataKey="day" tick={{ fontSize: 10, fill: "#8FA9A0" }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: "#8FA9A0" }} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E3ECE8" }}
                        formatter={(v: any) => [`${v} 次`, "调用"]} />
                      <Area type="monotone" dataKey="calls" stroke="#2E5A4C" strokeWidth={2} fill="url(#trendFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card className="border lg:col-span-5" style={{ borderColor: C.border }}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <CircleDot className="w-3.5 h-3.5" style={{ color: C.primary }} />
                  <span className="text-[14px] font-medium" style={{ color: C.ink }}>场景调用分布</span>
                  <span className="text-[12px]" style={{ color: C.light }}>本月真实计量</span>
                </div>
                {sceneData.length === 0 ? (
                  <div className="h-44 flex items-center justify-center text-[14px]" style={{ color: C.light }}>本月暂无调用数据</div>
                ) : (
                  <div className="flex items-center gap-3">
                    <div className="h-44 w-1/2">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={sceneData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                            innerRadius={38} outerRadius={62} paddingAngle={3} strokeWidth={0}>
                            {sceneData.map((x: any, i: number) => <Cell key={i} fill={x.fill} />)}
                          </Pie>
                          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E3ECE8" }}
                            formatter={(v: any, n: any) => [`${v} 次`, n]} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex-1 space-y-2">
                      {sceneData.map((x: any) => (
                        <div key={x.name} className="flex items-center justify-between text-[13px]">
                          <span className="flex items-center gap-1.5" style={{ color: C.mid }}>
                            <span className="w-2 h-2 rounded-full" style={{ background: x.fill }} />
                            {x.name}
                          </span>
                          <span className="font-mono" style={{ color: C.ink }}>{x.value.toLocaleString()}</span>
                        </div>
                      ))}
                      <div className="pt-1 border-t text-[12px]" style={{ borderColor: C.border, color: C.light }}>
                        合计 {sceneData.reduce((n: number, x: any) => n + x.value, 0).toLocaleString()} 次
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* 图表区 2：Agent 活跃度排行 + 服务健康 */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            <Card className="border lg:col-span-7" style={{ borderColor: C.border }}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Zap className="w-3.5 h-3.5" style={{ color: C.primary }} />
                  <span className="text-[14px] font-medium" style={{ color: C.ink }}>Agent 活跃度排行</span>
                  <span className="text-[12px]" style={{ color: C.light }}>近 7 日调用量（真实计量）</span>
                </div>
                {usageData.length === 0 ? (
                  <div className="h-44 flex items-center justify-center text-[14px]" style={{ color: C.light }}>
                    近 7 日暂无 Agent 调用，业务端接入后自动累积
                  </div>
                ) : (
                  <div className="h-44">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={usageData} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E3ECE8" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 10, fill: "#8FA9A0" }} axisLine={false} tickLine={false} />
                        <YAxis type="category" dataKey="name" width={96} tick={{ fontSize: 10, fill: "#4A5B54" }} axisLine={false} tickLine={false} />
                        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E3ECE8" }}
                          formatter={(v: any) => [`${v} 次`, "调用"]} />
                        <Bar dataKey="calls" radius={[0, 4, 4, 0]} barSize={14}>
                          {usageData.map((_: any, i: number) => (
                            <Cell key={i} fill={i === 0 ? "#8A6A1F" : i === 1 ? "#2E5A4C" : "#3D7363"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border lg:col-span-5" style={{ borderColor: C.border }}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <HeartPulse className="w-3.5 h-3.5" style={{ color: C.primary }} />
                  <span className="text-[14px] font-medium" style={{ color: C.ink }}>平台服务健康</span>
                  <span className="text-[12px]" style={{ color: C.light }}>依赖服务快照</span>
                </div>
                <div className="space-y-2">
                  {services.length === 0 && (
                    <div className="py-8 text-center text-[14px]" style={{ color: C.light }}>暂无服务数据</div>
                  )}
                  {services.map((s: any, i: number) => (
                    <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg"
                      style={{ background: s.ok ? "#F3F6F4" : "#FBF4E4" }}>
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ background: s.ok ? "#2E5A4C" : "#C8A45D" }} />
                        <span className="text-[14px]" style={{ color: C.ink }}>{s.name}</span>
                        {!s.ok && (
                          <span className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#FDF6E3", color: "#8A6A1F" }}>
                            {s.status}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-[12px] font-mono" style={{ color: C.light }}>
                        <span>{s.latency}</span>
                        <span>{s.uptime}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </section>
  );
}

/* ═══════════════════════════════════════════
   喂料口 · 健康助手营销语料弹窗（2026-08-22 老黄拍板 + #482 门店级语料槽）
   B 端后台可视化：白话一段话描述门店项目/卖点/引导话术；
   支持「平台默认（全部门店兜底）」+ 按门店（Org）分别编辑专属语料；
   保存自动过 compliance（违规拦截）；提供默认样例一键填充。
   ═══════════════════════════════════════════ */
function HealthAssistantPromptModal({
  tenantId, onClose,
}: { tenantId: string; onClose: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [sample, setSample] = useState("");
  const [platformDefault, setPlatformDefault] = useState("");
  const [orgs, setOrgs] = useState<{ id: string; name: string }[]>([]);
  const [scope, setScope] = useState(""); // "" = 平台默认；否则 orgId
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // 门店列表（喂料口门店选择器，仅一次；复用已有 fetchTenantOrgs → OrgItem[]）
  useEffect(() => {
    if (!tenantId) return;
    fetchTenantOrgs(tenantId).then((list) => {
      setOrgs(list || []);
    });
  }, [tenantId]);

  // 按当前归属加载语料（平台默认 or 门店专属；门店未配置时后端返回平台默认兜底展示）
  useEffect(() => {
    if (!tenantId) { setLoading(false); return; }
    let alive = true;
    setLoading(true); setError(null); setSaved(false);
    if (!scope) {
      fetchHealthAssistantPrompt(tenantId).then((r) => {
        if (!alive) return;
        if (r.ok && r.data) {
          setPrompt(r.data.health_assistant_prompt || "");
          setSample(r.data.sample || "");
        } else setError(r.msg || "加载语料失败");
        setLoading(false);
      });
    } else {
      fetchOrgHealthAssistantPrompt(tenantId, scope).then((r) => {
        if (!alive) return;
        if (r.ok && r.data) {
          setPrompt(r.data.health_assistant_prompt || "");
          setPlatformDefault(r.data.platform_default || "");
          setSample(r.data.sample || "");
        } else setError(r.msg || "加载语料失败");
        setLoading(false);
      });
    }
    return () => { alive = false; };
  }, [tenantId, scope]);

  const doSave = async () => {
    if (!prompt.trim()) { setError("语料不能为空"); return; }
    setSaving(true); setError(null); setSaved(false);
    const r = scope
      ? await saveOrgHealthAssistantPrompt(tenantId, scope, prompt.trim())
      : await saveHealthAssistantPrompt(tenantId, prompt.trim());
    setSaving(false);
    if (r.ok) { setSaved(true); setTimeout(() => onClose(), 900); }
    else { setError(r.msg || "保存失败"); }
  };

  const scopeLabel = scope
    ? (orgs.find((o) => o.id === scope)?.name || "该门店")
    : "平台默认（全部门店兜底）";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-2xl rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <PenLine className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[17px] font-semibold" style={{ color: C.ink }}>健康助手 · 营销语料喂料口</span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-black/5"><X className="w-4 h-4" style={{ color: C.mid }} /></button>
        </div>
        <div className="text-[13px] mb-3" style={{ color: C.light }}>
          租户 {tenantId || "（未识别）"} · 每次 C 端对话动态生效，改完即用、无需发版
        </div>

        {loading ? (
          <div className="h-40 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin" style={{ color: C.primary }} /></div>
        ) : (
          <>
            {/* 归属选择器：#482 平台默认 ↔ 门店专属 */}
            <div className="mb-3 flex items-center gap-2">
              <span className="text-[14px] font-medium shrink-0" style={{ color: C.ink }}>语料归属</span>
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                className="flex-1 rounded-lg border px-2 py-1.5 text-[14px] outline-none focus:border-[#2E5A4C]"
                style={{ borderColor: C.border, color: C.ink, background: "#FBFAF7" }}
              >
                <option value="">平台默认（全部门店兜底）</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </div>
            {scope && (
              <div className="mb-2 text-[13px]" style={{ color: C.light }}>
                门店专属语料；未配置时 C 端自动回落平台默认
                {platformDefault ? `：${platformDefault}` : ""}
              </div>
            )}

            <div className="mb-2 flex items-center gap-2">
              <span className="text-[14px] font-medium" style={{ color: C.ink }}>语料内容（≤500 字，白话一段话）</span>
              {sample && (
                <button
                  className="text-[13px] px-2 py-0.5 rounded flex items-center gap-1"
                  style={{ background: "#F3F6F4", color: C.primary }}
                  onClick={() => { setPrompt(sample); setError(null); }}
                >
                  <Copy className="w-3 h-3" /> 填入样例
                </button>
              )}
            </div>
            <textarea
              value={prompt}
              onChange={(e) => { setPrompt(e.target.value); setSaved(false); setError(null); }}
              maxLength={500}
              rows={8}
              placeholder={"例如：本店位于XX路，主营小儿推拿+成人艾灸。主打温阳灸（怕冷/宫寒）、脾胃推拿（积食）。引导话术：提到怕冷→介绍温阳灸并邀约到店；提到积食→推荐小儿推拿。禁忌：不承诺疗效、不硬广。"}
              className="w-full rounded-lg border p-3 text-[15px] leading-relaxed outline-none focus:border-[#2E5A4C]"
              style={{ borderColor: C.border, color: C.ink, background: "#FBFAF7" }}
            />
            <div className="flex justify-between items-center mt-1">
              <span className="text-[13px]" style={{ color: C.light }}>{prompt.length}/500</span>
              <span className="text-[13px]" style={{ color: C.light }}>硬规则：保存自动过合规审核 · 提示词已内建「不硬广、不编造、不承诺疗效」</span>
            </div>

            {sample && (
              <div className="mt-3 p-3 rounded-lg text-[13px] leading-relaxed" style={{ background: "#F3F6F4", color: C.mid }}>
                <span className="font-medium" style={{ color: C.primary }}>推荐写法（样例）</span>
                <div className="mt-1">{sample}</div>
              </div>
            )}

            {error && (
              <div className="mt-3 p-2.5 rounded-lg text-[14px] flex items-start gap-2" style={{ background: "#FDF0EC", color: "#B03A2E" }}>
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {error}
              </div>
            )}
            {saved && (
              <div className="mt-3 p-2.5 rounded-lg text-[14px] flex items-center gap-2" style={{ background: "#EAF3EF", color: "#2E5A4C" }}>
                <Check className="w-3.5 h-3.5" /> 已保存（{scopeLabel}），C 端对话即刻生效
              </div>
            )}

            <div className="flex justify-end gap-2 mt-4">
              <Button size="sm" variant="outline" className="h-8" onClick={onClose}>取消</Button>
              <Button size="sm" className="h-8" style={{ background: C.primary }} disabled={saving || !prompt.trim()} onClick={doSave}>
                {saving ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-1" />}
                {saving ? "保存中…" : "保存（自动过合规）"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   Agent 在线试用（内嵌能力卡片）
   按 agent_key 路由到对应能力的试用表单。
   当前：health-advisor 辨证试用；其余能力展示说明。
   ═══════════════════════════════════════════ */

function AgentTrial({ agent, onClose }: { agent: AgentDef; onClose: () => void }) {
  if (agent.agent_key === "health-advisor") {
    return <HealthAdvisorTrial onClose={onClose} />;
  }
  if (agent.agent_key === "store-coach") {
    return <StoreCoachTrial onClose={onClose} />;
  }
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Plug className="w-3.5 h-3.5" style={{ color: C.primary }} />
          <span className="text-[14px] font-medium" style={{ color: C.ink }}>「{agent.name}」API 契约</span>
        </div>
        <Button size="sm" variant="outline" className="h-6 text-[13px]" onClick={onClose}>关闭</Button>
      </div>
      {agent.desc && <p className="text-[13px] leading-relaxed" style={{ color: C.mid }}>{agent.desc}</p>}
      <div className="flex flex-wrap gap-1.5">
        <span className="text-[12px] px-1.5 py-0.5 rounded font-mono" style={{ background: C.soft, color: C.primary }}>
          {agent.router_prefix || "—"}
        </span>
        {agent.capabilities.map((c) => (
          <span key={c} className="text-[12px] px-1.5 py-0.5 rounded font-mono" style={{ background: "#F5F5F5", color: C.mid }}>
            {c}
          </span>
        ))}
      </div>
      <div className="text-[13px] flex items-center gap-2" style={{ color: C.light }}>
        <AlertTriangle className="w-3.5 h-3.5" />
        该能力由业务端按上述 API 契约调用（鉴权走登录态）；控制台内可直接用卡片「看板」查看它的真实运营数据。
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   门店话术教练在线试用
   直接对接 /api/v1/agent/store-coach/sessions，
   输入对练主题（可带课件文本），即时看到 AI 顾客开场白。
   ═══════════════════════════════════════════ */

function StoreCoachTrial({ onClose }: { onClose?: () => void }) {
  const [topic, setTopic] = useState("");
  const [profile, setProfile] = useState("");
  const [material, setMaterial] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!topic.trim()) { setErr("请输入对练主题"); return; }
    setLoading(true); setErr(null); setResult(null);
    const r = await consultStoreCoach({
      topic: topic.trim(),
      customer_profile: profile.trim() || undefined,
      material_text: material.trim() || undefined,
    });
    setLoading(false);
    if (r?.code === 0 && r.data) setResult(r.data);
    else setErr(r?.message || "调用失败");
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Stethoscope className="w-3.5 h-3.5" style={{ color: C.primary }} />
          <span className="text-[14px] font-medium" style={{ color: C.ink }}>门店话术教练 · 在线试用</span>
          <span className="text-[12px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>store-coach</span>
        </div>
        {onClose && (
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100" style={{ color: C.light }}>
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div>
        <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>对练主题（*）</label>
        <input
          value={topic} onChange={(e) => setTopic(e.target.value)}
          placeholder="例：顾客嫌养生套餐贵，怎么接"
          className="w-full rounded-lg border px-2.5 py-1.5 text-[14px] focus:outline-none"
          style={{ borderColor: C.border, color: C.ink }}
        />
      </div>

      <div>
        <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>顾客画像（选填）</label>
        <input
          value={profile} onChange={(e) => setProfile(e.target.value)}
          placeholder="例：50岁阿姨、注重养生、对价格敏感"
          className="w-full rounded-lg border px-2.5 py-1.5 text-[14px] focus:outline-none"
          style={{ borderColor: C.border, color: C.ink }}
        />
      </div>

      <div>
        <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>课件文本（选填，课件驱动 V2）</label>
        <textarea
          value={material} onChange={(e) => setMaterial(e.target.value)}
          rows={2}
          placeholder="粘贴店长上传课件的文本片段，AI 顾客将围绕课件知识点提问"
          className="w-full rounded-lg border p-2.5 text-[14px] resize-none focus:outline-none"
          style={{ borderColor: C.border, color: C.ink }}
        />
      </div>

      {err && (
        <div className="text-[13px] flex items-center gap-2" style={{ color: "#B03A2E" }}>
          <AlertTriangle className="w-3.5 h-3.5" />{err}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" className="h-7 text-[14px]" style={{ background: C.primary }}
          disabled={loading} onClick={run}>
          {loading
            ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            : <Stethoscope className="w-3.5 h-3.5 mr-1" />}
          {loading ? "AI 顾客开场中…" : "开始对练"}
        </Button>
      </div>

      {result && (
        <div className="border-t pt-2.5 space-y-2.5" style={{ borderColor: C.border }}>
          <div>
            <div className="text-[13px] mb-1" style={{ color: C.light }}>顾客画像</div>
            <div className="text-[14px]" style={{ color: C.ink }}>{result.customer_profile}</div>
          </div>
          <div>
            <div className="text-[13px] mb-1" style={{ color: C.light }}>AI 顾客开场白</div>
            <div className="text-[14px] leading-relaxed rounded-lg px-3 py-2" style={{ background: "#F3F6F4", color: C.ink }}>
              {result.opening}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <span className="text-[12px] px-1.5 py-0.5 rounded font-mono" style={{ background: C.soft, color: C.primary }}>
              {result.model}
            </span>
            {result.passing_score != null && (
              <span className="text-[12px] px-1.5 py-0.5 rounded font-mono" style={{ background: "#FDF6E3", color: "#8A6A1F" }}>
                合格线 {result.passing_score}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   中医健康顾问在线试用
   直接对接 /api/v1/agent/health-advisor/consult，
   让运营在控制台内输入问诊文本即时查看辨证结果。
   ═══════════════════════════════════════════ */

function HealthAdvisorTrial({ onClose }: { onClose?: () => void }) {
  const [question, setQuestion] = useState("");
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<HealthAdvisorConsultResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!question.trim()) { setErr("请输入问诊内容"); return; }
    setLoading(true); setErr(null); setResult(null);
    const tid = getIdentity()?.tenant_id || "tenant_default";
    const r = await consultHealthAdvisor({
      question: question.trim(),
      profile: { age: age ? Number(age) : undefined, gender: gender || undefined },
      store_id: tid,
      mode: "full",
    });
    setLoading(false);
    if (r?.code === 0 && r.data) setResult(r.data);
    else setErr(r?.message || "调用失败");
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Stethoscope className="w-3.5 h-3.5" style={{ color: C.primary }} />
          <span className="text-[14px] font-medium" style={{ color: C.ink }}>中医健康顾问 · 在线试用</span>
          <span className="text-[12px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>health-advisor</span>
        </div>
        {onClose && (
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100" style={{ color: C.light }}>
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div>
        <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>问诊内容（症状 / 舌象 / 脉象 / 病史）</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="例：患者男，45岁，主诉神疲乏力、畏寒肢冷、纳差便溏、舌淡胖边有齿痕苔白滑，脉沉细无力。"
          className="w-full rounded-lg border p-2.5 text-[14px] resize-none focus:outline-none"
          style={{ borderColor: C.border, color: C.ink }}
        />
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>年龄（选填）</label>
          <input
            value={age} onChange={(e) => setAge(e.target.value)}
            type="number" placeholder="45"
            className="w-full rounded-lg border px-2.5 py-1.5 text-[14px] focus:outline-none"
            style={{ borderColor: C.border, color: C.ink }}
          />
        </div>
        <div className="flex-1">
          <label className="text-[13px] mb-1 block" style={{ color: C.mid }}>性别（选填）</label>
          <input
            value={gender} onChange={(e) => setGender(e.target.value)}
            placeholder="男 / 女"
            className="w-full rounded-lg border px-2.5 py-1.5 text-[14px] focus:outline-none"
            style={{ borderColor: C.border, color: C.ink }}
          />
        </div>
      </div>

      {err && (
        <div className="text-[13px] flex items-center gap-2" style={{ color: "#B03A2E" }}>
          <AlertTriangle className="w-3.5 h-3.5" />{err}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" className="h-7 text-[14px]" style={{ background: C.primary }}
          disabled={loading} onClick={run}>
          {loading
            ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            : <Stethoscope className="w-3.5 h-3.5 mr-1" />}
          {loading ? "辨证中…" : "开始辨证"}
        </Button>
        {result?.partial && (
          <span className="text-[13px] px-2 py-0.5 rounded-full" style={{ background: "#FDF6E3", color: "#8A6A1F" }}>部分降级（partial）</span>
        )}
      </div>

      {result && (
        <div className="border-t pt-2.5 space-y-2.5" style={{ borderColor: C.border }}>
          {result.constitution?.type && (
            <Field label="体质辨识" value={result.constitution.type} sub={result.constitution.desc} />
          )}
          {result.syndrome?.name && (
            <Field
              label="辨证倾向（证型）"
              value={result.syndrome.name}
              sub={result.syndrome.confidence != null ? `置信度 ${Math.round(result.syndrome.confidence * 100)}%` : undefined}
            />
          )}
          {result.formulas && result.formulas.length > 0 && (
            <div>
              <div className="text-[13px] mb-1" style={{ color: C.light }}>推荐方剂</div>
              <div className="flex flex-wrap gap-1.5">
                {result.formulas.map((f, i) => (
                  <span key={i} className="text-[13px] px-2 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
                    {f.name}{f.desc ? `（${f.desc}）` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.suggestions && result.suggestions.length > 0 && (
            <div>
              <div className="text-[13px] mb-1" style={{ color: C.light }}>调理建议</div>
              <ul className="list-disc pl-5 space-y-0.5">
                {result.suggestions.map((s, i) => (
                  <li key={i} className="text-[14px] leading-relaxed" style={{ color: C.mid }}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          {result.report_id && (
            <div className="text-[13px]" style={{ color: C.light }}>报告 ID：<span className="font-mono">{result.report_id}</span></div>
          )}
          {result.reply && (
            <div>
              <div className="text-[13px] mb-1" style={{ color: C.light }}>辨证详述</div>
              <pre className="text-[13px] bg-[#F8FAF9] rounded-lg p-2.5 overflow-auto max-h-48 whitespace-pre-wrap" style={{ color: C.mid }}>{result.reply}</pre>
            </div>
          )}
          {result.disclaimer && (
            <div className="text-[13px] leading-relaxed" style={{ color: C.light }}>⚠️ {result.disclaimer}</div>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, value, sub }: { label: string; value?: string; sub?: string }) {
  return (
    <div>
      <div className="text-[14px] mb-0.5" style={{ color: C.light }}>{label}</div>
      <div className="text-[15px] font-medium" style={{ color: C.ink }}>{value}</div>
      {sub && <div className="text-[13px]" style={{ color: C.light }}>{sub}</div>}
    </div>
  );
}
