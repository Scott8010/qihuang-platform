import { useEffect, useState } from "react";
import {
  Bot, HeartPulse, PenLine, BookOpen, BarChart3, Sparkles, Lock, Loader2, Check,
} from "lucide-react";
import { C } from "@/lib/types";
import { fetchMyAgents, type MyAgentsOverview, type MyAgentItem } from "@/lib/api";

/** 机构端「我的能力」——当前套餐可用的 Agent 清单。
 *  数据源 /admin/v1/my/agents 与 require_agent_in_plan 门控同源：
 *  这里看到的能力 = 客户系统真能调用的能力，不造假、不漏展示。 */

const categoryIcon = (cat: string) => {
  switch (cat) {
    case "health": return HeartPulse;
    case "content": return PenLine;
    case "edu": return BookOpen;
    case "business": return BarChart3;
    case "mystic": return Sparkles;
    default: return Bot;
  }
};
const categoryLabel: Record<string, string> = {
  health: "健康", content: "内容", edu: "教育", business: "经营", mystic: "文化", general: "通用",
};
const sceneLabel: Record<string, string> = {
  MED: "医馆/医疗", EDU: "教育", RETAIL: "门店零售", HQ: "总部集团",
};
const capLabel: Record<string, string> = {
  scan: "内容送审", feedback: "反馈复核", dashboard: "数据看板",
  archive: "档案留存", cast: "排盘起卦", daily: "每日日签", report: "报告生成", analysis: "堪舆分析",
  consult: "问诊咨询", chat: "对话问答", analyze: "舌象分析",
  session: "陪练会话", evaluate: "评分评估", sessions: "话术训练",
  generate: "文案生成", diagnose: "经营诊断",
};

export default function MyAgents() {
  const [data, setData] = useState<MyAgentsOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    fetchMyAgents()
      .then((d) => { if (alive) setData(d); })
      .catch(() => { /* 接口异常走占位，不造假 */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-[15px]" style={{ color: C.light }}>
        <Loader2 className="w-4 h-4 animate-spin mr-2" />能力清单加载中...
      </div>
    );
  }
  if (!data) {
    return (
      <div className="rounded-xl p-8 text-center text-[15px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        能力清单暂不可用，请联系客户经理确认套餐状态。
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 概览条 */}
      <div className="rounded-xl p-5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div className="flex items-center gap-2">
          <Bot className="w-5 h-5" style={{ color: C.primary }} />
          <span className="text-[17px] font-semibold" style={{ color: C.primary }}>我的能力</span>
        </div>
        <p className="text-[13px] mt-2 leading-relaxed" style={{ color: C.mid }}>
          当前 <b style={{ color: C.primary }}>{data.plan || "—"}</b>
          {" · "}{sceneLabel[data.scene] || data.scene} 场景，已开通
          <b style={{ color: C.primary }}> {data.available.length} </b>项 Agent 能力。
          下列范围与平台实际调用权限完全一致；如需加购未开通能力，请联系客户经理。
        </p>
        {!data.has_subscription && (
          <div className="mt-3 rounded-lg px-3 py-2 text-[13px]" style={{ background: "#FDECEA", color: "#B03A2E" }}>
            当前无有效订阅，暂未开通任何能力，请联系客户经理。
          </div>
        )}
      </div>

      {/* 已开通能力 */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Check className="w-4 h-4" style={{ color: C.primary }} />
          <h2 className="text-[16px] font-semibold" style={{ color: C.ink }}>已开通能力</h2>
          <span className="px-2 py-0.5 rounded-full text-[12px]" style={{ background: C.soft, color: C.primary }}>
            {data.available.length} 项
          </span>
        </div>
        {data.available.length === 0 ? (
          <div className="rounded-xl p-6 text-center text-[14px]" style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.light }}>
            暂无已开通能力
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            {data.available.map((a: MyAgentItem) => {
              const Icon = categoryIcon(a.category);
              return (
                <div key={a.agent_key} className="rounded-xl p-4 bg-white" style={{ border: `1px solid ${C.border}` }}>
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: C.soft }}>
                      <Icon className="w-5 h-5" style={{ color: C.primary }} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[15px] font-semibold truncate" style={{ color: C.ink }}>{a.name}</span>
                        <span className="px-1.5 py-0.5 rounded text-[11px] shrink-0"
                          style={a.source === "addon"
                            ? { background: "#FBF3DC", color: "#8A6A1F" }
                            : { background: C.soft, color: C.primary }}>
                          {a.source === "addon" ? "单独加购" : "套餐包含"}
                        </span>
                      </div>
                      <div className="text-[12px] mt-0.5" style={{ color: C.light }}>
                        {categoryLabel[a.category] || a.category} · {a.agent_key}
                      </div>
                      <p className="text-[13px] mt-2 leading-relaxed" style={{
                        color: C.mid,
                        display: "-webkit-box", WebkitLineClamp: 3,
                        WebkitBoxOrient: "vertical", overflow: "hidden",
                      }}>{a.desc}</p>
                      {a.capabilities.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-3">
                          {a.capabilities.slice(0, 4).map((cap) => (
                            <span key={cap} className="px-1.5 py-0.5 rounded text-[11px]"
                              style={{ background: C.bg, color: C.mid }}>
                              {capLabel[cap] || cap}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 未开通能力（灰显占位，明确不造假） */}
      {data.locked.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Lock className="w-4 h-4" style={{ color: C.light }} />
            <h2 className="text-[16px] font-semibold" style={{ color: C.mid }}>未开通能力</h2>
            <span className="px-2 py-0.5 rounded-full text-[12px]" style={{ background: C.bg, color: C.light }}>
              {data.locked.length} 项
            </span>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {data.locked.map((a) => (
              <div key={a.agent_key} className="flex items-center gap-3 rounded-lg px-3 py-2.5"
                style={{ background: C.bg, border: `1px dashed ${C.border}`, opacity: 0.75 }}>
                <Lock className="w-4 h-4 shrink-0" style={{ color: C.light }} />
                <span className="text-[13px] truncate" style={{ color: C.mid }}>{a.name}</span>
                <span className="ml-auto text-[12px] shrink-0" style={{ color: C.light }}>未开通 · 联系客户经理</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
