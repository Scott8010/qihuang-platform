import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Bot, Boxes, RefreshCw, Check, Loader2, Network, Gauge, Plug,
  CircleDot, AlertTriangle, Stethoscope, X, BarChart3,
} from "lucide-react";
import { C } from "@/lib/types";
import {
  fetchAgentCenter, toggleAgent, fetchAgentDashboard,
  fetchPlanAgentMatrix, setPlanAgents,
  getIdentity, consultHealthAdvisor,
  type AgentDef, type PlanAgentRow, type HealthAdvisorConsultResult,
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
      <div className="text-[12px]" style={{ color: C.mid }}>
        Agent 中台把「可嵌入业务流的能力模块」作为一等资源统一管理：<b>资源池</b>注册能力并支持运营态热插拔启停，
        <b>套餐专家团</b>把能力打包进套餐，<b>各 Agent 看板</b>派发底层运营数据。新增能力只需注册 + 挂载路由。
      </div>

      {/* ═══ 构件 0：平台总览（汇总可视化） ═══ */}
      <AgentOverview agents={agents} onOpenTrial={setTrialFor} />

      {/* ═══ 构件 A：能力资源池 ═══ */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Boxes className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[14px] font-medium" style={{ color: C.ink }}>能力资源池（构件 A）</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
              {agents.length}
            </span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={() => loadAgents()}>
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
                          <div className="text-[14px] font-medium" style={{ color: C.ink }}>{a.name}</div>
                          <div className="text-[11px] font-mono" style={{ color: C.light }}>{a.agent_key}</div>
                        </div>
                      </div>
                      <span className="text-[11px] px-2 py-0.5 rounded-full" style={{
                        background: active ? "#EAF2EE" : "#F0F0F0",
                        color: active ? "#2E5A4C" : C.light,
                      }}>{active ? "启用中" : "已停用"}</span>
                    </div>

                    {a.desc && <p className="text-[12px] leading-relaxed mb-2" style={{ color: C.mid }}>{a.desc}</p>}

                    <div className="flex flex-wrap gap-1.5 mb-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "#F5F5F5", color: C.mid }}>
                        {a.category}
                      </span>
                      {a.engine && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ background: "#F5F5F5", color: C.mid }}>
                          {a.engine}
                        </span>
                      )}
                      {a.capabilities.map((c) => (
                        <span key={c} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: C.soft, color: C.primary }}>
                          {c}
                        </span>
                      ))}
                    </div>

                    <div className="text-[11px] mb-3" style={{ color: C.light }}>
                      已纳入 <b style={{ color: C.mid }}>{a.included_in_plans.length}</b> 个套餐专家团
                      {a.included_in_plans.length > 0 && (
                        <span className="ml-1 font-mono">{a.included_in_plans.map(planName).join("、")}</span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <Button size="sm" className="h-7 text-[12px]" style={{ background: active ? "#8A6A1F" : C.primary }}
                        onClick={() => handleToggle(a)}>
                        <Plug className="w-3.5 h-3.5 mr-1" /> {active ? "停用" : "启用"}
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[12px]"
                        onClick={() => openDash(a.agent_key)}>
                        <Gauge className="w-3.5 h-3.5 mr-1" /> 看板
                      </Button>
                      {(a.agent_key === "health-advisor" || a.agent_key === "store-coach" || a.agent_key === "content-writer" || a.agent_key === "insight") && (
                        <Button size="sm" variant="outline" className="h-7 text-[12px]"
                          style={trialFor === a.agent_key ? { borderColor: C.primary, color: C.primary } : undefined}
                          onClick={() => setTrialFor(trialFor === a.agent_key ? null : a.agent_key)}>
                          <Stethoscope className="w-3.5 h-3.5 mr-1" />
                          {trialFor === a.agent_key ? "收起" : "在线试用"}
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
                  <div className="text-[13px]">资源池为空，部署期注册能力后将在此呈现</div>
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
            <span className="text-[14px] font-medium" style={{ color: C.ink }}>套餐专家团组合（构件 B）</span>
          </div>
          <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={() => loadMatrix()}>
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
                        <span className="text-[13px] font-medium" style={{ color: C.ink }}>{row.planName}</span>
                        <span className="text-[11px] font-mono" style={{ color: C.light }}>{row.planId}</span>
                        <span className="text-[11px]" style={{ color: C.light }}>· {row.agents.length} 个能力</span>
                      </div>
                      {!editing ? (
                        <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={() => startEdit(row)}>编辑组合</Button>
                      ) : (
                        <div className="flex gap-2">
                          <Button size="sm" className="h-7 text-[12px]" style={{ background: C.primary }}
                            disabled={savingPlan === row.planId} onClick={() => saveEdit(row.planId)}>
                            {savingPlan === row.planId ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-1" />} 保存
                          </Button>
                          <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={cancelEdit}>取消</Button>
                        </div>
                      )}
                    </div>

                    {editing ? (
                      <div className="flex flex-wrap gap-2">
                        {agents.length === 0 && <span className="text-[12px]" style={{ color: C.light }}>资源池暂无可用能力</span>}
                        {agents.map((a) => {
                          const on = editAgents.includes(a.agent_key);
                          return (
                            <button key={a.agent_key} onClick={() =>
                              setEditAgents((prev) => on ? prev.filter((x) => x !== a.agent_key) : [...prev, a.agent_key])
                            }
                              className="flex items-center gap-1.5 text-[12px] px-2.5 py-1 rounded-full border transition-colors"
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
                          <span className="text-[12px]" style={{ color: C.light }}>未打包任何 Agent 能力</span>
                        ) : row.agents.map((k) => (
                          <span key={k} className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
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
                  <div className="text-[13px]">暂无套餐数据</div>
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
          <span className="text-[14px] font-medium" style={{ color: C.ink }}>各 Agent 运营看板（构件 C）</span>
        </div>
        {!dashKey ? (
          <Card className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-8 text-center" style={{ color: C.light }}>
              <Gauge className="w-8 h-8 mx-auto mb-2 opacity-40" />
              <div className="text-[13px]">在上方资源池点击「看板」查看对应能力的运营数据</div>
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
                <span className="text-[13px] font-medium" style={{ color: C.ink }}>{dashKey} 运营看板</span>
                <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={() => openDash(dashKey!)}>
                  <RefreshCw className="w-3.5 h-3.5 mr-1" /> 刷新
                </Button>
              </div>

              {dash.__error ? (
                <div className="text-[13px] text-red-600 flex items-center gap-2"><AlertTriangle className="w-4 h-4" />{dash.__error}</div>
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
                      <div className="text-[12px] mb-2" style={{ color: C.light }}>近期记录（最新 {dash.recent.length} 条）</div>
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr className="text-left text-[11px]" style={{ color: C.light }}>
                            {["标识", "状态", "动作", "时间"].map((h) => <th key={h} className="pb-1.5 font-normal">{h}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          {dash.recent.map((m: any, i: number) => (
                            <tr key={i} className="border-t" style={{ borderColor: C.border }}>
                              <td className="py-2 font-mono" style={{ color: C.mid }}>{m.material_key || m.key || m.id || "—"}</td>
                              <td className="py-2">
                                <span className="text-[11px] px-1.5 py-0.5 rounded" style={{
                                  background: (stateColor[m.state] ? stateColor[m.state] : C.mid) + "22",
                                  color: stateColor[m.state] || C.mid,
                                }}>{stateLabel[m.state] || m.state || "—"}</span>
                              </td>
                              <td className="py-2" style={{ color: C.mid }}>{m.action_taken || m.action || "—"}</td>
                              <td className="py-2 text-[11px]" style={{ color: C.light }}>{m.updated_at || m.created_at || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* 兜底：非合规结构时展示原始 JSON */}
                  {dash.total === undefined && !dash.states && (
                    <pre className="text-[11px] bg-[#F8FAF9] rounded-lg p-3 overflow-auto max-h-64" style={{ color: C.mid }}>
                      {JSON.stringify(dash, null, 2)}
                    </pre>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        ) : null}
      </section>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: C.border }}>
      <div className="text-[11px] mb-1" style={{ color: C.light }}>{label}</div>
      <div className="text-[20px] font-semibold" style={{ color }}>{value}</div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   构件 0：平台总览（汇总可视化）
   纯前端聚合 agents/plans，不新增后端接口。
   ═══════════════════════════════════════════ */

const categoryLabel: Record<string, string> = {
  content: "内容", mystic: "玄学", health: "健康", edu: "培训", business: "经营",
};
const categoryColor: Record<string, string> = {
  content: "#2E5A4C", mystic: "#8A6A1F", health: "#3D7363", edu: "#C8A45D", business: "#5B7F8A",
};

function AgentOverview({ agents, onOpenTrial }: {
  agents: AgentDef[];
  onOpenTrial: (key: string) => void;
}) {
  const total = agents.length;
  const active = agents.filter((a) => a.status === "active").length;
  const inactive = total - active;
  const activeRate = total ? Math.round((active / total) * 100) : 0;

  // 分类分布
  const byCat = new Map<string, number>();
  agents.forEach((a) => byCat.set(a.category, (byCat.get(a.category) || 0) + 1));
  const cats = Array.from(byCat.entries()).sort((x, y) => y[1] - x[1]);

  // 套餐覆盖
  const covered = agents.filter((a) => a.included_in_plans.length > 0).length;

  return (
    <section>
      <Card className="border" style={{ borderColor: C.border }}>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
            <span className="text-[14px] font-medium" style={{ color: C.ink }}>平台总览</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
              {active}/{total} 启用
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <Metric label="能力总数" value={String(total)} color={C.primary} />
            <Metric label="启用中" value={String(active)} color="#2E5A4C" />
            <Metric label="已停用" value={String(inactive)} color={inactive ? "#B03A2E" : C.mid} />
            <Metric label="覆盖套餐" value={`${covered}/${total}`} color="#8A6A1F" />
          </div>

          {/* 启用率进度条 */}
          <div className="mb-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px]" style={{ color: C.light }}>启用率</span>
              <span className="text-[11px] font-medium" style={{ color: C.primary }}>{activeRate}%</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden" style={{ background: "#F0F0F0" }}>
              <div className="h-full rounded-full" style={{ width: `${activeRate}%`, background: C.primary }} />
            </div>
          </div>

          {/* 分类分布 */}
          <div className="flex flex-wrap gap-2 mb-3">
            {cats.map(([k, v]) => (
              <span key={k} className="text-[11px] px-2 py-0.5 rounded-full" style={{
                background: (categoryColor[k] || C.mid) + "18", color: categoryColor[k] || C.mid,
              }}>
                {categoryLabel[k] || k} × {v}
              </span>
            ))}
            {cats.length === 0 && <span className="text-[11px]" style={{ color: C.light }}>暂无分类数据</span>}
          </div>

          {/* 各能力状态条（点「试用」直接展开对应能力） */}
          <div className="flex flex-wrap gap-1.5">
            {agents.map((a) => {
              const on = a.status === "active";
              return (
                <button key={a.agent_key}
                  onClick={() => onOpenTrial(a.agent_key)}
                  className="flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full border transition-colors"
                  style={{
                    borderColor: on ? C.border : "#E5E5E5",
                    background: on ? "#FAFCFB" : "#F7F7F7",
                    color: on ? C.ink : C.light,
                  }}
                  title={on ? "已启用 · 点击在线试用" : "已停用 · 点击在线试用"}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: on ? "#2E5A4C" : "#CCCCCC" }} />
                  {a.name}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </section>
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
  return (
    <div className="text-[12px] flex items-center justify-between" style={{ color: C.mid }}>
      <span className="flex items-center gap-2">
        <AlertTriangle className="w-3.5 h-3.5" style={{ color: C.light }} />
        「{agent.name}」暂未提供控制台内试用表单，可直接在卡片「看板」查看运营数据，或由业务端按 API 契约调用。
      </span>
      <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onClose}>关闭</Button>
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
          <span className="text-[12px] font-medium" style={{ color: C.ink }}>中医健康顾问 · 在线试用</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>health-advisor</span>
        </div>
        {onClose && (
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100" style={{ color: C.light }}>
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <div>
        <label className="text-[11px] mb-1 block" style={{ color: C.mid }}>问诊内容（症状 / 舌象 / 脉象 / 病史）</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="例：患者男，45岁，主诉神疲乏力、畏寒肢冷、纳差便溏、舌淡胖边有齿痕苔白滑，脉沉细无力。"
          className="w-full rounded-lg border p-2.5 text-[12px] resize-none focus:outline-none"
          style={{ borderColor: C.border, color: C.ink }}
        />
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <label className="text-[11px] mb-1 block" style={{ color: C.mid }}>年龄（选填）</label>
          <input
            value={age} onChange={(e) => setAge(e.target.value)}
            type="number" placeholder="45"
            className="w-full rounded-lg border px-2.5 py-1.5 text-[12px] focus:outline-none"
            style={{ borderColor: C.border, color: C.ink }}
          />
        </div>
        <div className="flex-1">
          <label className="text-[11px] mb-1 block" style={{ color: C.mid }}>性别（选填）</label>
          <input
            value={gender} onChange={(e) => setGender(e.target.value)}
            placeholder="男 / 女"
            className="w-full rounded-lg border px-2.5 py-1.5 text-[12px] focus:outline-none"
            style={{ borderColor: C.border, color: C.ink }}
          />
        </div>
      </div>

      {err && (
        <div className="text-[11px] flex items-center gap-2" style={{ color: "#B03A2E" }}>
          <AlertTriangle className="w-3.5 h-3.5" />{err}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" className="h-7 text-[12px]" style={{ background: C.primary }}
          disabled={loading} onClick={run}>
          {loading
            ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
            : <Stethoscope className="w-3.5 h-3.5 mr-1" />}
          {loading ? "辨证中…" : "开始辨证"}
        </Button>
        {result?.partial && (
          <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: "#FDF6E3", color: "#8A6A1F" }}>部分降级（partial）</span>
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
              <div className="text-[11px] mb-1" style={{ color: C.light }}>推荐方剂</div>
              <div className="flex flex-wrap gap-1.5">
                {result.formulas.map((f, i) => (
                  <span key={i} className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
                    {f.name}{f.desc ? `（${f.desc}）` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.suggestions && result.suggestions.length > 0 && (
            <div>
              <div className="text-[11px] mb-1" style={{ color: C.light }}>调理建议</div>
              <ul className="list-disc pl-5 space-y-0.5">
                {result.suggestions.map((s, i) => (
                  <li key={i} className="text-[12px] leading-relaxed" style={{ color: C.mid }}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          {result.report_id && (
            <div className="text-[11px]" style={{ color: C.light }}>报告 ID：<span className="font-mono">{result.report_id}</span></div>
          )}
          {result.reply && (
            <div>
              <div className="text-[11px] mb-1" style={{ color: C.light }}>辨证详述</div>
              <pre className="text-[11px] bg-[#F8FAF9] rounded-lg p-2.5 overflow-auto max-h-48 whitespace-pre-wrap" style={{ color: C.mid }}>{result.reply}</pre>
            </div>
          )}
          {result.disclaimer && (
            <div className="text-[11px] leading-relaxed" style={{ color: C.light }}>⚠️ {result.disclaimer}</div>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, value, sub }: { label: string; value?: string; sub?: string }) {
  return (
    <div>
      <div className="text-[12px] mb-0.5" style={{ color: C.light }}>{label}</div>
      <div className="text-[13px] font-medium" style={{ color: C.ink }}>{value}</div>
      {sub && <div className="text-[11px]" style={{ color: C.light }}>{sub}</div>}
    </div>
  );
}
