import { useEffect, useMemo, useState } from "react";
import {
  Bot, HeartPulse, PenLine, BookOpen, BarChart3, Sparkles, Loader2, Check,
  Search, LayoutGrid, X,
} from "lucide-react";
import { C } from "@/lib/types";
import { fetchMyAgents, type MyAgentsOverview, type MyAgentItem } from "@/lib/api";

/** 机构端「我的能力」——应用市场风格的已开通 Agent 能力清单。
 *  数据源 /admin/v1/my/agents 与 require_agent_in_plan 门控同源：
 *  这里看到的能力 = 客户系统真能调用的能力，不造假、不漏展示。
 *  只展示已开通能力；分类/搜索为纯前端交互，不改动真实数据范围。 */

const categoryStyle: Record<string, { icon: typeof Bot; color: string; bg: string }> = {
  health: { icon: HeartPulse, color: "#2E8B6B", bg: "#E6F4EE" },
  content: { icon: PenLine, color: "#3B6FC4", bg: "#E8F0FE" },
  edu: { icon: BookOpen, color: "#8A6A1F", bg: "#FBF4E4" },
  business: { icon: BarChart3, color: "#B4682E", bg: "#FDF0E3" },
  mystic: { icon: Sparkles, color: "#7B5EA7", bg: "#F3EDFB" },
  general: { icon: Bot, color: "#2E5A4C", bg: "#EAF2EE" },
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
  const [keyword, setKeyword] = useState("");
  const [activeCat, setActiveCat] = useState("all");

  useEffect(() => {
    let alive = true;
    fetchMyAgents()
      .then((d) => { if (alive) setData(d); })
      .catch(() => { /* 接口异常走占位，不造假 */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  // 分类只从真实已开通能力里生成，不凭空造分类
  const categories = useMemo(() => {
    const set = new Set((data?.available || []).map((a) => a.category || "general"));
    return ["all", ...Array.from(set)];
  }, [data]);

  // 搜索 + 分类过滤：纯前端收窄，绝不新增数据
  const shown = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return (data?.available || []).filter((a) => {
      if (activeCat !== "all" && (a.category || "general") !== activeCat) return false;
      if (!kw) return true;
      return (a.name + " " + a.desc + " " + a.agent_key + " " + (a.capabilities || []).join(" "))
        .toLowerCase().includes(kw);
    });
  }, [data, keyword, activeCat]);

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
    <div className="space-y-5">
      {/* 顶部 Banner：应用市场头部 */}
      <div className="rounded-2xl px-6 py-5 relative overflow-hidden"
        style={{ background: "linear-gradient(120deg, #2E5A4C 0%, #3D7363 60%, #4E8B77 100%)" }}>
        <div className="flex items-center justify-between gap-4 relative z-10">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-white/15">
              <LayoutGrid className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-[20px] font-semibold text-white">能力市场</h1>
              <p className="text-[13px] mt-1 text-white/80">
                {data.plan || "当前套餐"} · {sceneLabel[data.scene] || data.scene} 场景 · 已开通
                <b className="text-white mx-1">{data.available.length}</b>项能力
              </p>
            </div>
          </div>
          <div className="text-right text-white/85 text-[12px] leading-relaxed hidden sm:block">
            下列能力与平台实际调用权限完全一致<br />看到的 = 能调用的
          </div>
        </div>
        <div className="absolute -right-8 -top-10 w-40 h-40 rounded-full bg-white/5" />
        <div className="absolute right-16 -bottom-16 w-32 h-32 rounded-full bg-white/5" />
      </div>

      {/* 无订阅提示 */}
      {!data.has_subscription && data.available.length === 0 && (
        <div className="rounded-lg px-4 py-3 text-[13px]" style={{ background: "#FDECEA", color: "#B03A2E" }}>
          当前无有效订阅，暂未开通任何能力，请联系客户经理。
        </div>
      )}

      {/* 工具条：搜索 + 分类 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-[340px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索能力名称、功能…"
            className="w-full rounded-lg pl-9 pr-8 py-2 text-[13px] outline-none"
            style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.ink }}
          />
          {keyword && (
            <button onClick={() => setKeyword("")} className="absolute right-2 top-1/2 -translate-y-1/2"
              style={{ color: C.light }} title="清除搜索">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {categories.map((cat) => (
            <button key={cat} onClick={() => setActiveCat(cat)}
              className="px-3 py-1.5 rounded-full text-[12px] transition-colors"
              style={activeCat === cat
                ? { background: C.primary, color: "#fff" }
                : { background: "#fff", color: C.mid, border: `1px solid ${C.border}` }}>
              {cat === "all" ? "全部" : (categoryLabel[cat] || cat)}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[12px]" style={{ color: C.light }}>共 {shown.length} 项</span>
      </div>

      {/* 应用市场卡片网格 */}
      {shown.length === 0 ? (
        <div className="rounded-xl p-10 text-center text-[14px]" style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.light }}>
          {data.available.length === 0 ? "当前套餐暂无已开通能力" : "没有匹配的能力，试试其他关键词或分类"}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {shown.map((a: MyAgentItem) => {
            const st = categoryStyle[a.category] || categoryStyle.general;
            const Icon = st.icon;
            return (
              <div key={a.agent_key}
                className="rounded-2xl p-5 bg-white transition-all hover:-translate-y-0.5 hover:shadow-lg"
                style={{ border: `1px solid ${C.border}` }}>
                <div className="flex items-start justify-between gap-2">
                  <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: st.bg }}>
                    <Icon className="w-6 h-6" style={{ color: st.color }} />
                  </div>
                  <span className="px-2 py-1 rounded-full text-[11px] shrink-0 inline-flex items-center gap-1"
                    style={a.source === "addon"
                      ? { background: "#FBF4E4", color: "#8A6A1F" }
                      : { background: C.soft, color: C.primary }}>
                    {a.source === "addon" ? "单独加购" : "套餐包含"}
                  </span>
                </div>

                <div className="mt-4 flex items-center gap-2">
                  <h3 className="text-[16px] font-semibold" style={{ color: C.ink }}>{a.name}</h3>
                  <span className="inline-flex items-center gap-0.5 text-[11px]" style={{ color: C.primary }}>
                    <Check className="w-3 h-3" />已开通
                  </span>
                </div>
                <div className="text-[12px] mt-1" style={{ color: C.light }}>
                  {categoryLabel[a.category] || a.category || "通用"}
                </div>

                <p className="text-[13px] mt-3 leading-relaxed" style={{
                  color: C.mid, minHeight: 40,
                  display: "-webkit-box", WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical", overflow: "hidden",
                }}>{a.desc}</p>

                {a.capabilities.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-4 pt-3" style={{ borderTop: `1px solid ${C.border}` }}>
                    {a.capabilities.slice(0, 4).map((cap) => (
                      <span key={cap} className="px-2 py-0.5 rounded text-[11px]"
                        style={{ background: C.bg, color: C.mid }}>
                        {capLabel[cap] || cap}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[12px] text-center" style={{ color: C.light }}>
        如需开通更多能力，请联系客户经理调整套餐
      </p>
    </div>
  );
}
