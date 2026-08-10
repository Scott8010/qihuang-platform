import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Layers, ArrowRight, SkipForward, CheckCircle2, Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import type { DeckTask } from "@/lib/types";

const toneMap: Record<string, { color: string; bg: string }> = {
  red: { color: "#B03A2E", bg: "#FDECEA" },
  amber: { color: "#8A6A1F", bg: "#FBF4E4" },
  blue: { color: "#2B5A8A", bg: "#EAF1F8" },
  gold: { color: "#8A6A1F", bg: "#FDF9F0" },
  green: { color: "#2E5A4C", bg: "#EAF2EE" },
};

/** 任务卡片堆 — tasks 由 Dashboard 根据真实后端信号派生，无待办时显示空态 */
export default function TaskDeck({
  tasks, go, loading = false,
}: { tasks: DeckTask[]; go: (p: string) => void; loading?: boolean }) {
  const [start, setStart] = useState(0);
  const n = tasks.length;
  const s = n > 0 ? start % n : 0;
  const ordered = n > 0 ? [...tasks.slice(s), ...tasks.slice(0, s)] : [];

  return (
    <Card className="border" style={{ borderColor: C.border }}>
      <CardHeader className="pb-1">
        <div className="flex items-center justify-between">
          <CardTitle className="text-[15px] flex items-center gap-2" style={{ color: C.primary }}>
            <Layers className="w-4 h-4" /> 待办任务
          </CardTitle>
          <div className="flex items-center gap-1.5">
            {tasks.map((t, i) => (
              <button
                key={t.id}
                onClick={() => setStart(i)}
                className="w-1.5 h-1.5 rounded-full transition-all"
                style={{ background: i === s ? C.primary : C.border, width: i === s ? 14 : 6 }}
              />
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pb-5">
        {n === 0 ? (
          <div className="h-[196px] flex flex-col items-center justify-center gap-2 text-[13px]" style={{ color: C.light }}>
            {loading ? (
              <><Loader2 className="w-5 h-5 animate-spin" /> 加载中…</>
            ) : (
              <>
                <CheckCircle2 className="w-7 h-7" style={{ color: C.primaryLight }} />
                当前没有待办任务
                <span className="text-[11.5px]">待审知识、逾期账单与系统告警出现时会自动汇聚到这里</span>
              </>
            )}
          </div>
        ) : (
          <div className="relative h-[196px]">
            {ordered.slice(0, 3).map((t, i) => {
              const tone = toneMap[t.tone] || toneMap.green;
              const isTop = i === 0;
              return (
                <div
                  key={t.id}
                  className="absolute inset-x-0 top-0 rounded-xl border bg-white transition-all duration-300 ease-out"
                  style={{
                    transform: `translateY(${i * 13}px) scale(${1 - i * 0.045})`,
                    transformOrigin: "top center",
                    zIndex: 30 - i,
                    borderColor: isTop ? tone.color : C.border,
                    boxShadow: isTop ? "0 8px 22px rgba(34,49,43,0.10)" : "0 2px 6px rgba(34,49,43,0.04)",
                    pointerEvents: isTop ? "auto" : "none",
                  }}
                >
                  <div className="h-1 rounded-t-xl" style={{ background: isTop ? tone.color : C.border }} />
                  <div className="p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] px-2 py-0.5 rounded-full font-medium" style={{ color: tone.color, background: tone.bg }}>
                        {t.type}
                      </span>
                      <span className="text-[11px]" style={{ color: isTop ? tone.color : C.light }}>{t.tag}</span>
                    </div>
                    <div className="mt-2.5 text-[14px] font-semibold truncate" style={{ color: isTop ? C.ink : C.light }}>
                      {t.title}
                    </div>
                    {isTop && (
                      <>
                        <div className="mt-1.5 text-[12px] leading-5 line-clamp-2" style={{ color: C.mid }}>
                          {t.desc}
                        </div>
                        <div className="mt-3 flex gap-2">
                          <Button size="sm" className="h-8 text-[12px]" style={{ background: C.primary }} onClick={() => go(t.page)}>
                            去处理 <ArrowRight className="w-3.5 h-3.5 ml-1" />
                          </Button>
                          {n > 1 && (
                            <Button size="sm" variant="outline" className="h-8 text-[12px]" style={{ borderColor: C.border, color: C.mid }} onClick={() => setStart((s + 1) % n)}>
                              <SkipForward className="w-3.5 h-3.5 mr-1" /> 下一张
                            </Button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div className="mt-2 flex items-center justify-between text-[11.5px]" style={{ color: C.light }}>
          <span>{n > 0 ? `共 ${n} 项待办 · 点圆点可直达任意一张` : "待办自动汇聚，无需手工维护"}</span>
          {tasks.filter((t) => t.tone === "red").length > 0 && (
            <Badge variant="outline" className="border-red-300 text-red-600">
              {tasks.filter((t) => t.tone === "red").length} 项紧急
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
