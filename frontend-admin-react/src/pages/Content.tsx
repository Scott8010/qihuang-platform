import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BookOpenCheck, ShieldAlert, Search, Check, X, Bell, Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import type { TodoReviewItem, SensitiveWordItem } from "@/lib/types";
import { fetchReviews, fetchSensitiveWords, reviewAction } from "@/lib/api";

/* ═══════════════════════════════════════════
   内容管控 — 真实接口驱动
   审核队列 → GET /admin/v1/kg/review/pending
   通过/驳回 → POST /admin/v1/kg/review/action
   敏感词库 → GET /admin/v1/content/words
   ═══════════════════════════════════════════ */

const confColor = (v: number) => (v < 0.4 ? "#B03A2E" : v < 0.6 ? "#8A6A1F" : "#2E5A4C");

/** 依类型字符串稳定生成配色，避免写死枚举 */
function typeStyle(t: string) {
  const key = (t || "").toLowerCase();
  if (key.includes("herb") || key.includes("药")) return { color: "#2E5A4C", background: "#EAF2EE" };
  if (key.includes("syndrome") || key.includes("证")) return { color: "#8A6A1F", background: "#FBF4E4" };
  if (key.includes("case") || key.includes("案")) return { color: "#2C5F87", background: "#E8F1F8" };
  if (key.includes("classic") || key.includes("典")) return { color: "#7A4E8C", background: "#F3EBF7" };
  return { color: C.mid, background: "#F5F5F5" };
}

function actionStyle(a: string) {
  if (a === "拦截") return { color: "#B03A2E", background: "#FDECEA" };
  if (a === "替换") return { color: "#2E5A4C", background: "#EAF2EE" };
  return { color: "#8A6A1F", background: "#FBF4E4" };
}

export default function Content() {
  const [tab, setTab] = useState<"review" | "words">("review");
  const [reviews, setReviews] = useState<TodoReviewItem[]>([]);
  const [words, setWords] = useState<SensitiveWordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string>("");

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
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="space-y-4">
      {/* 顶部说明 */}
      <div className="text-[12px]" style={{ color: C.mid }}>
        自生长引擎产出的新知识一律「先审后入图谱」，低置信度条目双人复核；敏感词按场景生效，命中策略在生成层执行。
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setTab("review")}
            className="flex items-center gap-1.5 text-[13px] pb-1 border-b-2 transition-colors"
            style={{
              color: tab === "review" ? C.primary : C.mid,
              borderColor: tab === "review" ? C.primary : "transparent",
            }}
          >
            知识审核队列
            {reviews.length > 0 && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-full font-medium" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                {reviews.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("words")}
            className="flex items-center gap-1.5 text-[13px] pb-1 border-b-2 transition-colors"
            style={{
              color: tab === "words" ? C.primary : C.mid,
              borderColor: tab === "words" ? C.primary : "transparent",
            }}
          >
            敏感词库
            {words.length > 0 && (
              <span className="text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: C.soft, color: C.primary }}>
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
              className="pl-8 pr-3 py-1.5 w-48 text-[12px] rounded-lg border bg-white outline-none"
              style={{ borderColor: C.border }}
            />
          </div>
          <Bell className="w-4 h-4" style={{ color: C.light }} />
          <div className="flex items-center gap-1.5">
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] text-white" style={{ background: C.primary }}>
              管
            </div>
            <span className="text-[12px]" style={{ color: C.mid }}>管理员</span>
          </div>
        </div>
      </div>

      {/* 知识审核队列 */}
      {tab === "review" && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-4">
              <BookOpenCheck className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[14px] font-medium" style={{ color: C.ink }}>待审知识条目（图谱入库门禁）</span>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
                  {["编号", "类型", "名称", "置信度", "来源", "审核人", "操作"].map((h) => (
                    <th key={h} className="pb-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviews.map((r) => {
                  const ts = typeStyle(r.type);
                  const busy = busyId === r.id;
                  return (
                    <tr key={r.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="py-3 font-mono text-[12px]" style={{ color: C.mid }}>{r.id}</td>
                      <td className="py-3">
                        <span className="text-[11px] px-2 py-0.5 rounded" style={ts}>{r.type}</span>
                      </td>
                      <td className="py-3" style={{ color: C.ink }}>{r.name}</td>
                      <td className="py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[12px] font-semibold" style={{ color: confColor(r.conf) }}>
                            {r.conf.toFixed(2)}
                          </span>
                          {r.conf < 0.4 && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                              需双人复核
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 text-[12px]" style={{ color: C.mid }}>{r.source || "—"}</td>
                      <td className="py-3 text-[12px]" style={{ color: C.mid }}>{r.reviewer || "—"}</td>
                      <td className="py-3">
                        <div className="flex gap-2">
                          <Button
                            size="sm" className="h-7 px-3 text-[12px]" disabled={busy}
                            style={{ background: C.primary }}
                            onClick={() => handleAction(r.id, "approve")}
                          >
                            {busy ? <Loader2 className="w-3.5 h-3.5 mr-0.5 animate-spin" /> : <Check className="w-3.5 h-3.5 mr-0.5" />} 通过
                          </Button>
                          <Button
                            size="sm" variant="outline" className="h-7 px-3 text-[12px]" disabled={busy}
                            style={{ borderColor: "#B03A2E", color: "#B03A2E" }}
                            onClick={() => handleAction(r.id, "reject")}
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
                          <div className="text-[13px]">审核队列已清空</div>
                          <div className="text-[11px] mt-1">自生长引擎产出新知识后会自动进入此队列</div>
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
                <span className="text-[14px] font-medium" style={{ color: C.ink }}>敏感词与合规词库</span>
              </div>
              <Button size="sm" style={{ background: C.primary }}>+ 新增词条</Button>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
                  {["词条", "生效场景", "等级", "命中策略", "替换为", "启用"].map((h) => (
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
                      <td className="py-2.5 text-[12px]" style={{ color: C.mid }}>{w.scene}</td>
                      <td className="py-2.5 text-[12px]" style={{ color: C.mid }}>{w.cat}</td>
                      <td className="py-2.5">
                        <span className="text-[11px] px-2 py-0.5 rounded" style={as}>{w.action}</span>
                      </td>
                      <td className="py-2.5 text-[12px]" style={{ color: w.replacement ? C.mid : C.light }}>
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
                          <div className="text-[13px]">词库为空</div>
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
    </div>
  );
}
