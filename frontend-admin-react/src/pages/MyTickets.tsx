import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Send, Ticket as TicketIcon } from "lucide-react";
import { C } from "@/lib/types";
import { createMyTicket, fetchMyTickets, type TicketItem } from "@/lib/api";

const STATUS_TEXT: Record<string, string> = {
  open: "待处理", processing: "处理中", resolved: "已解决", closed: "已关闭",
};
const STATUS_COLOR: Record<string, string> = {
  open: "#B03A2E", processing: "#C8A45D", resolved: "#2E5A4C", closed: "#8FA9A0",
};

export function bjTime(v?: string | null): string {
  if (!v) return "—";
  // DB 存 UTC 且 often naive：无时区后缀时按 UTC 解析，再转北京时间展示。
  const s = /[Zz]|[+-]\d\d:\d\d$/.test(v) ? v : v + "Z";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return v;
  return new Date(d.getTime() + 8 * 3600 * 1000).toISOString().replace("T", " ").slice(0, 16);
}

/** 客户工作台「平台工单」：向平台提交申请/咨询，并跟踪处理进度。 */
export default function MyTickets() {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("咨询");
  const [priority, setPriority] = useState("normal");
  const [content, setContent] = useState("");
  const [filter, setFilter] = useState("");
  const [list, setList] = useState<TicketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = () => {
    setLoading(true);
    fetchMyTickets(filter || undefined).then((r) => { setList(r.items); setLoading(false); });
  };
  useEffect(load, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    setErr(""); setMsg("");
    if (title.trim().length < 2) { setErr("请填写工单标题（至少 2 个字）"); return; }
    if (content.trim().length < 2) { setErr("请简单描述你的问题或需求"); return; }
    setSubmitting(true);
    const r = await createMyTicket({ title: title.trim(), content: content.trim(), category, priority });
    setSubmitting(false);
    if (!r.ok) { setErr(r.msg || "提交失败，请稍后再试"); return; }
    setMsg(`工单已提交，单号 ${r.data?.ticket_no || ""}。平台处理后这里会显示进度。`);
    setTitle(""); setContent(""); setCategory("咨询"); setPriority("normal");
    setFilter("");
    load();
  };

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        需要开通新能力、调整套餐，或使用中遇到问题？在这里提交给平台，处理进度会显示在下方，不用在微信里翻聊天记录。
      </div>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[16px] flex items-center gap-2" style={{ color: C.primary }}>
            <TicketIcon className="w-4 h-4" /> 提交新工单
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="一句话说清要办什么事，例如：申请开通内容审核能力"
            className="w-full px-4 py-2.5 rounded-lg border text-[14px] outline-none"
            style={{ borderColor: C.border }}
          />
          <div className="flex gap-3">
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="px-3 py-2.5 rounded-lg border text-[14px] bg-white" style={{ borderColor: C.border, color: C.ink }}>
              {["咨询", "申请", "故障", "其他"].map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}
              className="px-3 py-2.5 rounded-lg border text-[14px] bg-white" style={{ borderColor: C.border, color: C.ink }}>
              <option value="normal">普通</option><option value="urgent">紧急</option><option value="low">不着急</option>
            </select>
          </div>
          <textarea
            value={content} onChange={(e) => setContent(e.target.value)} rows={4}
            placeholder="补充细节：什么功能、什么时间出现、期望怎么处理……"
            className="w-full px-4 py-2.5 rounded-lg border text-[14px] outline-none resize-y"
            style={{ borderColor: C.border }}
          />
          {err && <div className="text-[13px] text-red-600">{err}</div>}
          {msg && <div className="text-[13px] text-emerald-700">{msg}</div>}
          <Button onClick={submit} disabled={submitting} className="text-[14px] text-white" style={{ background: C.primary }}>
            {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
            提交给平台
          </Button>
        </CardContent>
      </Card>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>我的工单</CardTitle>
            <div className="flex gap-2">
              {[["", "全部"], ["open", "待处理"], ["processing", "处理中"], ["resolved", "已解决"]].map(([v, l]) => (
                <button key={v} onClick={() => setFilter(v)}
                  className="px-2.5 py-1 rounded-full text-[12px] border"
                  style={{
                    borderColor: C.border,
                    background: filter === v ? C.soft : "transparent",
                    color: filter === v ? C.primary : C.mid,
                  }}>{l}</button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center gap-2 py-10 justify-center text-[14px]" style={{ color: C.light }}>
              <Loader2 className="w-4 h-4 animate-spin" />加载中…
            </div>
          ) : list.length === 0 ? (
            <div className="py-10 text-center text-[14px]" style={{ color: C.light }}>还没有工单，有需要随时提交。</div>
          ) : (
            <div className="space-y-3">
              {list.map((t) => (
                <div key={t.id} className="rounded-lg border p-4" style={{ borderColor: C.border }}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[14px] font-medium truncate" style={{ color: C.ink }}>{t.title}</div>
                      <div className="text-[12px] mt-1" style={{ color: C.light }}>
                        单号 {t.ticket_no} · {t.category} · {bjTime(t.created_at)}
                      </div>
                    </div>
                    <span className="shrink-0 text-[12px] px-2 py-0.5 rounded-full text-white"
                      style={{ background: STATUS_COLOR[t.status] || "#8FA9A0" }}>
                      {STATUS_TEXT[t.status] || t.status}
                    </span>
                  </div>
                  <div className="text-[13px] mt-2 whitespace-pre-wrap leading-relaxed" style={{ color: C.mid }}>{t.content}</div>
                  {t.handler_note && (
                    <div className="text-[13px] mt-2 rounded-md p-2 leading-relaxed"
                      style={{ background: C.soft, color: C.primary }}>
                      平台回复：{t.handler_note}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
