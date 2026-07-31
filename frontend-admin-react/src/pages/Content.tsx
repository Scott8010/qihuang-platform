import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { BookOpenCheck, ShieldAlert, Search, Check, X, Bell, User } from "lucide-react";
import { C } from "@/lib/types";

/* ═══════════════════════════════════════════
   内容管控 — 按 KIMI 截图设计
   ═══════════════════════════════════════════ */

interface ReviewItem {
  id: string; type: string; typeColor: string; typeBg: string;
  name: string; conf: number; needReview?: boolean;
  source: string; reviewer: string;
}

interface WordItem {
  word: string; scene: string; cat: string;
  action: string; actionColor: string; actionBg: string;
  status: boolean;
}

const REVIEWS: ReviewItem[] = [
  { id: "KR-8812", type: "Herb", typeColor: "#2E5A4C", typeBg: "#EAF2EE", name: "炒酸枣仁", conf: 0.58, source: "自生长-文献雷达", reviewer: "小张" },
  { id: "KR-8811", type: "Syndrome", typeColor: "#2E5A4C", typeBg: "#EAF2EE", name: "少阳郁热证", conf: 0.44, source: "自生长-PubMed", reviewer: "大张" },
  { id: "KR-8809", type: "MedicalCase", typeColor: "#2E5A4C", typeBg: "#EAF2EE", name: "桂枝汤治自汗案（共享回流）", conf: 0.61, source: "租户医案回流", reviewer: "大张" },
  { id: "KR-8806", type: "ClassicText", typeColor: "#2E5A4C", typeBg: "#EAF2EE", name: "《温病条辨》上焦篇第十四条校注", conf: 0.37, needReview: true, source: "专家手工提交", reviewer: "小张" },
];

const WORDS: WordItem[] = [
  { word: "包治百病", scene: "全部场景", cat: "虚假宣传", action: "拦截", actionColor: "#B03A2E", actionBg: "#FDECEA", status: true },
  { word: "祖传秘方", scene: "全部场景", cat: "虚假宣传", action: "拦截", actionColor: "#B03A2E", actionBg: "#FDECEA", status: true },
  { word: "西医无用", scene: "全部场景", cat: "贬低同行", action: "替换", actionColor: "#2E5A4C", actionBg: "#EAF2EE", status: true },
  { word: "根治糖尿病", scene: "大健康", cat: "疗效承诺", action: "转人工", actionColor: "#8A6A1F", actionBg: "#FBF4E4", status: true },
  { word: "无效退款", scene: "全部场景", cat: "商业诱导", action: "替换", actionColor: "#2E5A4C", actionBg: "#EAF2EE", status: false },
];

const confColor = (v: number) => (v < 0.4 ? "#B03A2E" : v < 0.6 ? "#8A6A1F" : "#2E5A4C");

export default function Content() {
  const [tab, setTab] = useState<"review" | "words">("review");
  const [reviews, setReviews] = useState(REVIEWS);
  const [words] = useState(WORDS);

  const handleAction = (id: string, action: "approve" | "reject") => {
    setReviews((prev) => prev.filter((r) => r.id !== id));
  };

  return (
    <div className="space-y-4">
      {/* 顶部说明 + 搜索 + 用户 */}
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
            <span className="text-[11px] px-1.5 py-0.5 rounded-full font-medium" style={{ background: "#FDECEA", color: "#B03A2E" }}>
              {reviews.length}
            </span>
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
              王
            </div>
            <span className="text-[12px]" style={{ color: C.mid }}>王运营</span>
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
                {reviews.map((r) => (
                  <tr key={r.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-3 font-mono text-[12px]" style={{ color: C.mid }}>{r.id}</td>
                    <td className="py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={{ color: r.typeColor, background: r.typeBg }}>
                        {r.type}
                      </span>
                    </td>
                    <td className="py-3" style={{ color: C.ink }}>{r.name}</td>
                    <td className="py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12px] font-semibold" style={{ color: confColor(r.conf) }}>
                          {r.conf.toFixed(2)}
                        </span>
                        {r.needReview && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "#FDECEA", color: "#B03A2E" }}>
                            需双人复核
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 text-[12px]" style={{ color: C.mid }}>{r.source}</td>
                    <td className="py-3 text-[12px]" style={{ color: C.mid }}>{r.reviewer}</td>
                    <td className="py-3">
                      <div className="flex gap-2">
                        <Button
                          size="sm" className="h-7 px-3 text-[12px]"
                          style={{ background: C.primary }}
                          onClick={() => handleAction(r.id, "approve")}
                        >
                          <Check className="w-3.5 h-3.5 mr-0.5" /> 通过
                        </Button>
                        <Button
                          size="sm" variant="outline" className="h-7 px-3 text-[12px]"
                          style={{ borderColor: "#B03A2E", color: "#B03A2E" }}
                          onClick={() => handleAction(r.id, "reject")}
                        >
                          <X className="w-3.5 h-3.5 mr-0.5" /> 驳回
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {reviews.length === 0 && (
                  <tr><td colSpan={7} className="py-10 text-center text-[13px]" style={{ color: C.light }}>队列已清空</td></tr>
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
                  {["词条", "生效场景", "分类", "命中策略", "启用"].map((h) => (
                    <th key={h} className="pb-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {words.map((w) => (
                  <tr key={w.word} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-medium" style={{ color: C.ink }}>{w.word}</td>
                    <td className="py-2.5 text-[12px]" style={{ color: C.mid }}>{w.scene}</td>
                    <td className="py-2.5 text-[12px]" style={{ color: C.mid }}>{w.cat}</td>
                    <td className="py-2.5">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={{ color: w.actionColor, background: w.actionBg }}>
                        {w.action}
                      </span>
                    </td>
                    <td className="py-2.5">
                      <div
                        className="w-8 h-4 rounded-full relative cursor-pointer transition-colors"
                        style={{ background: w.status ? C.primary : "#ddd" }}
                      >
                        <div
                          className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all"
                          style={{ left: w.status ? 18 : 2 }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
