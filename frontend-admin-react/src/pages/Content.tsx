import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { BookOpenCheck, ShieldAlert, Search, Check, X, Bell, Loader2, Eye, Sparkles } from "lucide-react";
import { C } from "@/lib/types";
import type { TodoReviewItem, SensitiveWordItem } from "@/lib/types";
import { fetchReviews, fetchSensitiveWords, addSensitiveWord, deleteSensitiveWord, reviewAction, refineReview } from "@/lib/api";

/* ═══════════════════════════════════════════
   内容管控 — 真实接口驱动
   审核队列 → GET /admin/v1/kg/review/pending
   通过/驳回 → POST /admin/v1/kg/review/action
   AI 提炼   → POST /admin/v1/kg/review/{id}/refine
   敏感词库 → GET /admin/v1/content/words
   ═════════════════════════════════════════ */

const confColor = (v: number) => (v < 0.4 ? "#B03A2E" : v < 0.6 ? "#8A6A1F" : "#2E5A4C");

/** 依类型字符串稳定生成配色，避免写死枚举 */
function typeStyle(t: string) {
  const key = (t || "").toLowerCase();
  if (key.includes("herb") || key.includes("药")) return { color: "#2E5A4C", background: "#EAF2EE" };
  if (key.includes("formula") || key.includes("方")) return { color: "#2E5A4C", background: "#EAF2EE" }; // 经方
  if (key.includes("drug") || key.includes("西药")) return { color: "#B03A2E", background: "#FDECEA" }; // 西药
  if (key.includes("knowledge") || key.includes("知识")) return { color: "#2C5F87", background: "#E8F1F8" }; // 知识
  if (key.includes("syndrome") || key.includes("证")) return { color: "#8A6A1F", background: "#FBF4E4" };
  if (key.includes("case") || key.includes("案")) return { color: "#2C5F87", background: "#E8F1F8" };
  if (key.includes("classic") || key.includes("典")) return { color: "#7A4E8C", background: "#F3EBF7" };
  return { color: C.mid, background: "#F5F5F5" };
}

/** 审核队列类型中文标签（item_type 英文字段 → 中文展示） */
const TYPE_LABEL: Record<string, string> = {
  Formula: "经方", Drug: "西药", Knowledge: "知识", Syndrome: "证候",
  classic: "典籍", Classic: "典籍", formula: "经方", syndrome: "证候",
};

function actionStyle(a: string) {
  if (a === "拦截") return { color: "#B03A2E", background: "#FDECEA" };
  if (a === "替换") return { color: "#2E5A4C", background: "#EAF2EE" };
  return { color: "#8A6A1F", background: "#FBF4E4" };
}

/** 中文字符占比以外的「是否以英文为主」（字母占比 > 30% 视为英文） */
function isMostlyEnglish(text: string): boolean {
  if (!text) return false;
  const letters = (text.match(/[A-Za-z]/g) || []).length;
  return text.length > 0 && letters / text.length > 0.3;
}

/** 万方等站点抓取混入的浏览器警告垃圾文本 */
function isJunkText(text: string): boolean {
  return /检测到您的浏览器版本过低|万方数据知识服务平台|Google Chrome|Microsoft Edge|Firefox|Safari 浏览器|建议使用更高版本的浏览器/.test(text || "");
}

/** 是否为「典籍抽取」来源的待审条目（与后端 is_classics_content 对齐：有 entity_name 且非自生长文献） */
function isClassicsContent(c: any): boolean {
  if (!c || typeof c !== "object") return false;
  const hasEntityName = typeof c.entity_name === "string" && c.entity_name.trim().length > 0;
  if (!hasEntityName) return false;
  const isAutoGrowth = !!(c.clause_text || c.ai_extracted);
  return !isAutoGrowth;
}

export default function Content() {
  const [tab, setTab] = useState<"review" | "words">("review");
  const [reviews, setReviews] = useState<TodoReviewItem[]>([]);
  const [words, setWords] = useState<SensitiveWordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string>("");
  const [refiningId, setRefiningId] = useState<string>("");
  const [detail, setDetail] = useState<TodoReviewItem | null>(null);
  // 敏感词新增表单
  const [showAdd, setShowAdd] = useState(false);
  const [adding, setAdding] = useState(false);
  const [nw, setNw] = useState({ word: "", scene: "GLOBAL", level: "warn", replacement: "" });

  const loadWords = () => fetchSensitiveWords().then(setWords);

  const handleAddWord = async () => {
    const w = nw.word.trim();
    if (!w) return;
    setAdding(true);
    try {
      const ok = await addSensitiveWord(w, nw.scene, nw.level, nw.replacement.trim() || undefined);
      if (ok) {
        setShowAdd(false);
        setNw({ word: "", scene: "GLOBAL", level: "warn", replacement: "" });
        await loadWords();
      } else {
        alert("新增失败，请检查词条是否已存在或字段是否合法");
      }
    } finally {
      setAdding(false);
    }
  };

  const handleDeleteWord = async (w: SensitiveWordItem) => {
    if (!window.confirm(`确认删除敏感词「${w.word}」？`)) return;
    if (await deleteSensitiveWord(w.id)) await loadWords();
    else alert("删除失败");
  };

  const loadReviews = () => fetchReviews().then(setReviews);

  useEffect(() => {
    Promise.all([loadReviews(), fetchSensitiveWords().then(setWords)])
      .finally(() => setLoading(false));
  }, []);

  const handleAction = async (id: string, action: "approve" | "reject") => {
    setBusyId(id);
    try {
      await reviewAction(id, action);
      await loadReviews();   // 以后端为准重新拉取，不做本地假删除
      if (detail?.id === id) setDetail(null);
    } finally {
      setBusyId("");
    }
  };

  /** AI 提炼成功后，把 _refined 写回列表项与当前详情，避免重开抽屉丢失 */
  const handleRefined = (id: string, refined: any) => {
    setReviews((rs) => rs.map((r) => (r.id === id ? { ...r, content: { ...r.content, _refined: refined } } : r)));
    setDetail((d) => (d && d.id === id ? { ...d, content: { ...d.content, _refined: refined } } : d));
  };

  const handleRefine = async (id: string) => {
    setRefiningId(id);
    try {
      const r = await refineReview(id);
      if (r.ok && r.data?.refined) {
        handleRefined(id, r.data.refined);
      } else {
        alert(r.msg || "AI 提炼失败");
      }
    } finally {
      setRefiningId("");
    }
  };

  return (
    <div className="space-y-4">
      {/* 顶部说明 */}
      <div className="text-[14px]" style={{ color: C.mid }}>
        自生长引擎产出的新知识一律「先审后入图谱」，低置信度条目双人复核；敏感词按场景生效，命中策略在生成层执行。
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setTab("review")}
            className="flex items-center gap-1.5 text-[15px] pb-1 border-b-2 transition-colors"
            style={{
              color: tab === "review" ? C.primary : C.mid,
              borderColor: tab === "review" ? C.primary : "transparent",
            }}
          >
            知识审核队列
            {reviews.length > 0 && (
              <span className="text-[13px] px-1.5 py-0.5 rounded-full font-medium" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                {reviews.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("words")}
            className="flex items-center gap-1.5 text-[15px] pb-1 border-b-2 transition-colors"
            style={{
              color: tab === "words" ? C.primary : C.mid,
              borderColor: tab === "words" ? C.primary : "transparent",
            }}
          >
            敏感词库
            {words.length > 0 && (
              <span className="text-[13px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
                {words.length}
              </span>
            )}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
            <input
              placeholder="搜索租户 / 用户 / 密钥"
              className="pl-8 pr-3 py-1.5 w-48 text-[14px] rounded-lg border bg-white outline-none"
              style={{ borderColor: C.border }}
            />
          </div>
          <Bell className="w-4 h-4" style={{ color: C.light }} />
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-[12px] text-white" style={{ background: C.primary }}>
              管
            </div>
            <span className="text-[14px]" style={{ color: C.mid }}>管理员</span>
          </div>
        </div>
      </div>

      {/* 知识审核队列 */}
      {tab === "review" && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <BookOpenCheck className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[16px] font-medium" style={{ color: C.ink }}>待审知识条目（图谱入库门禁）</span>
            </div>
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  {["编号", "类型", "名称", "置信度", "来源", "审核人", "操作"].map((h) => (
                    <th key={h} className="pb-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviews.map((r, ri) => {
                  const ts = typeStyle(r.type);
                  const busy = busyId === r.id;
                  const hasRefined = !!(r.content && r.content._refined && !r.content._refined.error);
                  return (
                    <tr
                      key={r.id}
                      className="border-t hover:bg-[#F8FAF9] cursor-pointer"
                      style={{ borderColor: C.border }}
                      onClick={() => { if (!busy) setDetail(r); }}
                    >
                      <td className="py-3 font-mono text-[14px]" style={{ color: C.mid }} title={r.id}>#{ri + 1}</td>
                      <td className="py-3">
                        <span className="text-[13px] px-2 py-0.5 rounded" style={ts}>{TYPE_LABEL[r.type] || r.type}</span>
                      </td>
                      <td className="py-3" style={{ color: C.ink }}>{r.name}</td>
                      <td className="py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[14px] font-semibold" style={{ color: confColor(r.conf) }}>
                            {r.conf.toFixed(2)}
                          </span>
                          {r.conf < 0.4 && (
                            <span className="text-[12px] px-1.5 py-0.5 rounded" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                              需双人复核
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 text-[14px]" style={{ color: C.mid }}>{r.source || "—"}</td>
                      <td className="py-3 text-[14px]" style={{ color: C.mid }}>{r.reviewer || "—"}</td>
                      <td className="py-3">
                        <div className="flex gap-1.5 items-center">
                          {hasRefined && (
                            <span className="text-[12px] px-1.5 py-0.5 rounded flex items-center gap-0.5" style={{ background: C.soft, color: C.primary }}>
                              <Sparkles className="w-3 h-3" />已提炼
                            </span>
                          )}
                          <Button
                            size="sm" variant="ghost" className="h-7 px-2 text-[14px]"
                            disabled={busy}
                            style={{ color: C.primary }}
                            onClick={(e) => { e.stopPropagation(); setDetail(r); }}
                          >
                            <Eye className="w-3.5 h-3.5 mr-0.5" /> 详情
                          </Button>
                          <Button
                            size="sm" className="h-7 px-2 text-[14px]" disabled={busy}
                            style={{ background: C.primary }}
                            onClick={(e) => { e.stopPropagation(); handleAction(r.id, "approve"); }}
                          >
                            {busy ? <Loader2 className="w-3.5 h-3.5 mr-0.5 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-0.5" />} 通过
                          </Button>
                          <Button
                            size="sm" variant="outline" className="h-7 px-2 text-[14px]" disabled={busy}
                            style={{ borderColor: "#B03A2E", color: "#B03A2E" }}
                            onClick={(e) => { e.stopPropagation(); handleAction(r.id, "reject"); }}
                          >
                            <X className="w-3.5 h-3.5 mr-0.5" /> 驳回
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {reviews.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-12 text-center" style={{ color: C.light }}>
                      {loading ? (
                        <><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</>
                      ) : (
                        <>
                          <BookOpenCheck className="w-8 h-8 mx-auto mb-2 opacity-40" />
                          <div className="text-[15px]">审核队列已清空</div>
                          <div className="text-[13px] mt-1">自生长引擎产出新知识后会自动进入此队列</div>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 敏感词库 */}
      {tab === "words" && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <ShieldAlert className="w-4 h-4" style={{ color: "#B03A2E" }} />
                <span className="text-[16px] font-medium" style={{ color: C.ink }}>敏感词与合规词库</span>
              </div>
              <Button size="sm" style={{ background: C.primary }} onClick={() => setShowAdd(!showAdd)}>
                {showAdd ? "收起" : "+ 新增词条"}
              </Button>
            </div>
            {showAdd && (
              <div className="mb-4 p-3 rounded border flex flex-wrap items-end gap-2" style={{ borderColor: C.border, background: "#F8FAF9" }}>
                <div className="flex flex-col gap-1">
                  <span className="text-[13px]" style={{ color: C.mid }}>词条 *</span>
                  <input
                    value={nw.word}
                    onChange={(e) => setNw({ ...nw, word: e.target.value })}
                    placeholder="如：根治、包治百病"
                    className="h-8 px-2 text-[15px] rounded border outline-none"
                    style={{ borderColor: C.border, width: 180 }}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[13px]" style={{ color: C.mid }}>生效场景</span>
                  <select
                    value={nw.scene}
                    onChange={(e) => setNw({ ...nw, scene: e.target.value })}
                    className="h-8 px-2 text-[15px] rounded border outline-none bg-white"
                    style={{ borderColor: C.border }}
                  >
                    {["GLOBAL", "HEALTH", "MED", "EDU"].map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[13px]" style={{ color: C.mid }}>等级</span>
                  <select
                    value={nw.level}
                    onChange={(e) => setNw({ ...nw, level: e.target.value })}
                    className="h-8 px-2 text-[15px] rounded border outline-none bg-white"
                    style={{ borderColor: C.border }}
                  >
                    <option value="warn">warn</option>
                    <option value="block">block</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-[13px]" style={{ color: C.mid }}>替换为（可选）</span>
                  <input
                    value={nw.replacement}
                    onChange={(e) => setNw({ ...nw, replacement: e.target.value })}
                    placeholder="留空 = 拦截"
                    className="h-8 px-2 text-[15px] rounded border outline-none"
                    style={{ borderColor: C.border, width: 140 }}
                  />
                </div>
                <Button size="sm" style={{ background: C.primary }} disabled={!nw.word.trim() || adding} onClick={handleAddWord}>
                  {adding ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : null}提交
                </Button>
              </div>
            )}
            <table className="w-full text-[15px]">
              <thead>
                <tr className="text-left text-[13px]" style={{ color: C.light }}>
                  {["词条", "生效场景", "等级", "命中策略", "替换为", "启用", ""].map((h) => (
                    <th key={h} className="pb-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {words.map((w) => {
                  const as = actionStyle(w.action);
                  return (
                    <tr key={w.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="py-2.5 font-medium" style={{ color: C.ink }}>{w.word}</td>
                      <td className="py-2.5 text-[14px]" style={{ color: C.mid }}>{w.scene}</td>
                      <td className="py-2.5 text-[14px]" style={{ color: C.mid }}>{w.cat}</td>
                      <td className="py-2.5">
                        <span className="text-[13px] px-2 py-0.5 rounded" style={as}>{w.action}</span>
                      </td>
                      <td className="py-2.5 text-[14px]" style={{ color: w.replacement ? C.mid : C.light }}>
                        {w.replacement || "—"}
                      </td>
                      <td className="py-2.5">
                        <div
                          className="w-8 h-4 rounded-full relative transition-colors"
                          style={{ background: w.status ? C.primary : "#ddd" }}
                        >
                          <div
                            className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all"
                            style={{ left: w.status ? 18 : 2 }}
                          />
                        </div>
                      </td>
                      <td className="py-2.5">
                        <button
                          className="text-[14px] hover:underline"
                          style={{ color: "#B03A2E" }}
                          onClick={() => handleDeleteWord(w)}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {words.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-12 text-center" style={{ color: C.light }}>
                      {loading ? (
                        <><Loader2 className="w-4 h-4 animate-spin inline mr-2" />加载中…</>
                      ) : (
                        <>
                          <ShieldAlert className="w-8 h-8 mx-auto mb-2 opacity-40" />
                          <div className="text-[15px]">词库为空</div>
                        </>
                      )}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 详情抽屉（右侧滑入） */}
      <ReviewDetailDrawer
        detail={detail}
        busy={!!(detail && busyId === detail.id)}
        refining={!!(detail && refiningId === detail.id)}
        onRefine={handleRefine}
        onAction={handleAction}
        onClose={() => setDetail(null)}
      />
    </div>
  );
}

/* ═══════════════════════════════════════════
   详情抽屉 — 右侧滑入，分层呈现待审条目
   优先级：AI 提炼摘要 > 原文/AI萃取 > 结构化实体关系 > 来源 > 模型投票 > 完整 JSON(折叠)
   ═════════════════════════════════════════ */
function ReviewDetailDrawer({
  detail, busy, refining, onRefine, onAction, onClose,
}: {
  detail: TodoReviewItem | null;
  busy: boolean;
  refining: boolean;
  onRefine: (id: string) => void;
  onAction: (id: string, a: "approve" | "reject") => void;
  onClose: () => void;
}) {
  const c: any = detail?.content || {};
  const refined = c._refined;
  const hasRefined = !!refined && !refined.error;

  const isClassics = isClassicsContent(c);
  const classicsSource = (isClassics && c.props && typeof c.props.source_text === "string") ? c.props.source_text : "";
  const hasClassicsSource = !!classicsSource.trim();
  const classicsRefined = hasRefined && refined.entry_kind === "classics";

  const rawClause = typeof c.clause_text === "string" ? c.clause_text : "";
  const rawAi = typeof c.ai_extracted === "string" ? c.ai_extracted : "";
  const rawOriginal = typeof c.original_text === "string" ? c.original_text : "";
  const hasClause = !!rawClause.trim();
  const hasAiExtracted = !!rawAi.trim();
  const clauseIsJunk = isJunkText(rawClause);
  const hasSource = !!(c.source_doc || c.source_url);
  const entitiesDetail: any[] = Array.isArray(c.entities_detail) ? c.entities_detail : [];
  const relationsDetail: any[] = Array.isArray(c.relations_detail) ? c.relations_detail : [];
  const votes = c.model_votes || c.confidence_breakdown;

  const sourceText = !clauseIsJunk && hasClause ? rawClause : (hasAiExtracted ? rawAi : (rawOriginal.trim() || ""));
  const sourceLikelyEnglish = isMostlyEnglish(sourceText);
  const needRefine = !refined && (hasClause || hasAiExtracted || rawOriginal.trim().length > 0 || hasClassicsSource);
  const llmUnavailable = !!refined && refined.error === "LLM_UNAVAILABLE";

  return (
    <Dialog open={!!detail} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className="fixed top-0 right-0 left-auto translate-x-0 translate-y-0 h-screen max-w-md w-full sm:max-w-lg rounded-none border-l p-0 gap-0 overflow-hidden"
        style={{ background: "white" }}
      >
        {detail && (
          <>
            <DialogHeader className="px-5 py-4 border-b" style={{ borderColor: C.border }}>
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4" style={{ color: C.primary }} />
                <DialogTitle className="text-[17px] font-semibold">待审条目详情</DialogTitle>
              </div>
              <DialogDescription className="text-[14px] mt-1" style={{ color: C.mid }}>
                内容已 AI 预处理，审核前请重点核对「研究题目 / 结论 / 共识分歧」
              </DialogDescription>
            </DialogHeader>

            <ScrollArea className="h-[calc(100vh-180px)]">
              <div className="px-5 py-4 space-y-5">
                {/* 1. 基础信息 */}
                <Section title="基础信息">
                  <Row label="编号" value={<span className="font-mono">—</span>} />
                  <Row label="类型" value={
                    <span className="text-[13px] px-2 py-0.5 rounded" style={typeStyle(detail.type)}>
                      {TYPE_LABEL[detail.type] || detail.type}
                    </span>
                  } />
                  <Row label="名称" value={detail.name} />
                  <Row label="审核人" value={detail.reviewer || "—"} />
                  <Row label="置信度" value={
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold" style={{ color: confColor(detail.conf) }}>
                        {detail.conf.toFixed(2)}
                      </span>
                      {detail.conf < 0.4 && (
                        <Badge style={{ background: "#FDECEA", color: "#B03A2E", border: "none" }}>
                          需双人复核
                        </Badge>
                      )}
                    </div>
                  } />
                  <Row label="来源" value={detail.source || "—"} />
                  {c.item_id_in_kg && (
                    <Row label="KG ID" value={<span className="font-mono text-[13px]">{c.item_id_in_kg}</span>} />
                  )}
                </Section>

                {/* 2. AI 提炼入口 / 状态 */}
                {needRefine && !refining && !hasRefined && (
                  <div className="flex items-center justify-between gap-2 p-3 rounded-lg border" style={{ borderColor: C.primary, background: C.soft }}>
                    <div className="text-[14px]" style={{ color: C.ink }}>
                      {isClassics
                        ? "典籍条目，建议 AI 提炼方义 / 出处 / 主治"
                        : sourceLikelyEnglish
                          ? "检测到英文原文，建议 AI 翻译并提炼结论"
                          : "建议 AI 提炼研究题目 / 结论 / 共识分歧"}
                    </div>
                    <Button size="sm" className="h-7 px-2.5 text-[14px] shrink-0 flex items-center gap-1" style={{ background: C.primary }} onClick={() => onRefine(detail.id)}>
                      <Sparkles className="w-3.5 h-3.5" /> AI 提炼
                    </Button>
                  </div>
                )}
                {refining && (
                  <div className="flex items-center gap-2 text-[14px] p-3 rounded-lg" style={{ background: C.soft, color: C.primary }}>
                    <Loader2 className="w-4 h-4 animate-spin" /> AI 正在翻译并提炼，请稍候…
                  </div>
                )}
                {llmUnavailable && (
                  <div className="text-[14px] p-3 rounded-lg" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                    AI 提炼暂不可用（模型未配置或调用失败），可凭原文人工审核。
                  </div>
                )}

                {/* 3. AI 提炼结果（结构化中文摘要） */}
                {hasRefined && (
                  <>
                    <Separator />
                    <Section title={classicsRefined ? "AI 提炼 · 典籍审校摘要" : "AI 提炼 · 中文审核摘要"}>
                      <div className="flex items-center gap-1.5 mb-2">
                        <Sparkles className="w-3.5 h-3.5" style={{ color: C.primary }} />
                        <span className="text-[14px]" style={{ color: C.primary }}>由 AI 生成，供审核参考</span>
                      </div>
                      {classicsRefined ? <ClassicsRefinedBlock refined={refined} /> : <RefinedBlock refined={refined} />}
                    </Section>
                  </>
                )}

                {/* 3.5 典籍原文摘录（典籍抽取条目专用，避免只剩底 JSON） */}
                {isClassics && (
                  <>
                    <Separator />
                    <Section title="典籍原文摘录">
                      {hasClassicsSource ? (
                        <div className="text-[15px] leading-relaxed p-3 rounded whitespace-pre-wrap break-words" style={{ background: "#F8FAF9", color: C.ink }}>
                          {classicsSource}
                        </div>
                      ) : (
                        <div className="text-[13px]" style={{ color: C.light }}>（该条目无 props.source_text 原文摘录）</div>
                      )}
                      {c.entity_type && (
                        <div className="text-[13px] mt-1.5" style={{ color: C.light }}>条目类型：{c.entity_type}</div>
                      )}
                    </Section>
                  </>
                )}

                {/* 4. 原文摘录 */}
                {hasClause && (
                  <>
                    <Separator />
                    <Section title="原文摘录">
                      <div className="text-[15px] leading-relaxed p-3 rounded whitespace-pre-wrap break-words" style={{ background: "#F8FAF9", color: C.ink }}>
                        {rawClause}
                      </div>
                      {clauseIsJunk && (
                        <div className="text-[13px] mt-1" style={{ color: "#B03A2E" }}>⚠️ 疑似站点抓取噪声（浏览器警告等），提炼以 AI 萃取摘要为准</div>
                      )}
                      {sourceLikelyEnglish && !hasRefined && (
                        <div className="text-[13px] mt-1" style={{ color: C.light }}>原文为英文，点击上方「AI 提炼」可翻译</div>
                      )}
                    </Section>
                  </>
                )}

                {/* 5. AI 萃取摘要 */}
                {hasAiExtracted && (
                  <>
                    <Separator />
                    <Section title="AI 萃取摘要（自生长引擎）">
                      <div className="text-[15px] leading-relaxed p-3 rounded whitespace-pre-wrap break-words" style={{ background: "#F8FAF9", color: C.ink }}>
                        {rawAi}
                      </div>
                    </Section>
                  </>
                )}

                {/* 6. 模型候选实体 */}
                {entitiesDetail.length > 0 && (
                  <>
                    <Separator />
                    <Section title={`模型候选实体（${entitiesDetail.length}）`}>
                      <EntityCards items={entitiesDetail} />
                    </Section>
                  </>
                )}

                {/* 7. 模型候选关系 */}
                {relationsDetail.length > 0 && (
                  <>
                    <Separator />
                    <Section title={`模型候选关系（${relationsDetail.length}）`}>
                      <RelationCards items={relationsDetail} />
                    </Section>
                  </>
                )}

                {/* 8. 来源文献 */}
                {hasSource && (
                  <>
                    <Separator />
                    <Section title="来源文献">
                      {c.source_doc && <Row label="文献" value={c.source_doc} />}
                      {c.source_url && (
                        <Row label="链接" value={
                          <a href={c.source_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline break-all">
                            {c.source_url}
                          </a>
                        } />
                      )}
                    </Section>
                  </>
                )}

                {/* 9. 模型投票明细 */}
                {votes && (
                  <>
                    <Separator />
                    <Section title="模型投票明细">
                      <VoteTable votes={votes} />
                    </Section>
                  </>
                )}
              </div>
            </ScrollArea>

            <DialogFooter className="px-5 py-3 border-t flex-row justify-end gap-2" style={{ borderColor: C.border }}>
              <Button variant="outline" size="sm" onClick={onClose}>关闭</Button>
              <Button
                size="sm" variant="outline"
                disabled={busy}
                style={{ borderColor: "#B03A2E", color: "#B03A2E" }}
                onClick={() => onAction(detail.id, "reject")}
              >
                {busy ? <Loader2 className="w-3.5 h-3.5 mr-0.5 animate-spin" /> : <X className="w-3.5 h-3.5 mr-0.5" />} 驳回
              </Button>
              <Button
                size="sm" disabled={busy}
                style={{ background: C.primary }}
                onClick={() => onAction(detail.id, "approve")}
              >
                {busy ? <Loader2 className="w-3.5 h-3.5 mr-0.5 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-0.5" />} 通过
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ── AI 提炼结构化渲染 ── */
function RefinedBlock({ refined }: { refined: any }) {
  const title: string = refined?.research_title_zh || "";
  const conclusion: string = refined?.final_conclusion_zh || "";
  const translation: string = refined?.original_text_zh || "";
  const findings: string[] = Array.isArray(refined?.key_findings_zh) ? refined.key_findings_zh : [];
  const consensus: string[] = Array.isArray(refined?.consensus_points) ? refined.consensus_points : [];
  const divergence: string[] = Array.isArray(refined?.divergence_points) ? refined.divergence_points : [];
  return (
    <div className="space-y-3">
      {title && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>研究题目</div>
          <div className="text-[15px] font-semibold leading-snug" style={{ color: C.ink }}>{title}</div>
        </div>
      )}
      {conclusion && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>最终结论</div>
          <div className="text-[15px] leading-relaxed" style={{ color: C.ink }}>{conclusion}</div>
        </div>
      )}
      {translation && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>原文中文翻译</div>
          <div className="text-[14px] leading-relaxed p-2 rounded" style={{ background: "#F8FAF9", color: C.ink }}>{translation}</div>
        </div>
      )}
      <PointsList title="核心发现" items={findings} color="#2E5A4C" />
      <PointsList title="共识点" items={consensus} color="#2C5F87" />
      <PointsList title="分歧点" items={divergence} color="#B03A2E" />
      {refined?.provider && (
        <div className="text-[12px]" style={{ color: C.light }}>
          由 {refined.provider}（{refined.model}）提炼于 {(refined.refined_at || "").slice(0, 19)}
        </div>
      )}
    </div>
  );
}

/* ── 典籍抽取条目：AI 提炼结构化渲染（方义/出处/组成/主治）── */
function ClassicsRefinedBlock({ refined }: { refined: any }) {
  const name: string = refined?.entry_name_zh || "";
  const type: string = refined?.entry_type_zh || "";
  const source: string = refined?.source_text_zh || "";
  const fangyi: string = refined?.fangyi_zh || "";
  const attribution: string = refined?.source_attribution_zh || "";
  const components: string[] = Array.isArray(refined?.key_components_zh) ? refined.key_components_zh : [];
  const indication: string = refined?.indication_zh || "";
  return (
    <div className="space-y-3">
      {name && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>条目名称</div>
          <div className="text-[15px] font-semibold" style={{ color: C.ink }}>{name}</div>
        </div>
      )}
      {type && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>条目类型</div>
          <div className="text-[15px]" style={{ color: C.ink }}>{type}</div>
        </div>
      )}
      {source && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>原文摘录（精校）</div>
          <div className="text-[14px] leading-relaxed p-2 rounded" style={{ background: "#F8FAF9", color: C.ink }}>{source}</div>
        </div>
      )}
      {fangyi && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>方义 / 释义</div>
          <div className="text-[15px] leading-relaxed" style={{ color: C.ink }}>{fangyi}</div>
        </div>
      )}
      {attribution && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>出处</div>
          <div className="text-[15px] leading-relaxed" style={{ color: C.ink }}>{attribution}</div>
        </div>
      )}
      <PointsList title="关键组成 / 要点" items={components} color="#7A4E8C" />
      {indication && (
        <div>
          <div className="text-[13px] mb-0.5" style={{ color: C.light }}>主治 / 适用</div>
          <div className="text-[15px] leading-relaxed" style={{ color: C.ink }}>{indication}</div>
        </div>
      )}
      {refined?.provider && (
        <div className="text-[12px]" style={{ color: C.light }}>
          由 {refined.provider}（{refined.model}）提炼于 {(refined.refined_at || "").slice(0, 19)}
        </div>
      )}
    </div>
  );
}

function PointsList({ title, items, color }: { title: string; items: string[]; color: string }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="text-[13px] mb-1 font-medium" style={{ color }}>{title}</div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="text-[14px] leading-relaxed pl-3 relative" style={{ color: C.ink }}>
            <span className="absolute left-0 top-0" style={{ color }}>•</span>{it}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EntityCards({ items }: { items: any[] }) {
  return (
    <div className="space-y-2">
      {items.map((e, i) => (
        <div key={i} className="p-2.5 rounded-lg border" style={{ borderColor: C.border, background: "#fff" }}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[15px] font-medium" style={{ color: C.ink }}>{e.name}</span>
            <span className="text-[12px] px-1.5 py-0.5 rounded shrink-0" style={{ background: C.soft, color: C.primary }}>{e.type}</span>
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-[12px] flex-wrap" style={{ color: C.light }}>
            {Array.isArray(e.models) && e.models.length > 0 && <span>模型：{e.models.join(" / ")}</span>}
            {e.confidence != null && <span>置信 {Number(e.confidence).toFixed(2)}</span>}
            {e.level && <span>等级 {e.level}</span>}
            {e.count != null && <span>出现 {e.count} 次</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function RelationCards({ items }: { items: any[] }) {
  return (
    <div className="space-y-2">
      {items.map((r, i) => (
        <div key={i} className="p-2.5 rounded-lg border text-[14px]" style={{ borderColor: C.border, background: "#fff" }}>
          <div className="flex items-center gap-1.5 flex-wrap" style={{ color: C.ink }}>
            <span className="font-medium">{r.source}</span>
            <span style={{ color: C.primary }}>— {r.type} →</span>
            <span className="font-medium">{r.target}</span>
          </div>
          {r.evidence && <div className="mt-1.5 text-[13px] leading-relaxed" style={{ color: C.light }}>证据：{r.evidence}</div>}
        </div>
      ))}
    </div>
  );
}

function VoteTable({ votes }: { votes: any }) {
  if (Array.isArray(votes)) {
    return (
      <pre className="text-[13px] p-3 rounded font-mono whitespace-pre-wrap break-all max-h-48 overflow-auto" style={{ background: "#F8FAF9", color: C.ink }}>
        {JSON.stringify(votes, null, 2)}
      </pre>
    );
  }
  const entries = Object.entries(votes as Record<string, any>);
  return (
    <table className="w-full text-[14px]">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} className="border-t" style={{ borderColor: C.border }}>
            <td className="py-1.5 pr-3 w-1/3" style={{ color: C.light }}>{k}</td>
            <td className="py-1.5" style={{ color: C.ink }}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[13px] uppercase tracking-wider mb-2" style={{ color: C.light }}>{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-3 text-[14px] items-start">
      <span className="w-16 shrink-0" style={{ color: C.light }}>{label}</span>
      <span className="flex-1 min-w-0" style={{ color: C.ink }}>{value}</span>
    </div>
  );
}
