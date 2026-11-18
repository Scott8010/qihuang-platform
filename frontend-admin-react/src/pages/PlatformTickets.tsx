import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import { fetchPlatformTickets, fetchTenantExtended, replyTicket, type TicketItem } from "@/lib/api";
import { bjTime } from "./MyTickets";

const STATUS_TEXT: Record<string, string> = {
  open: "待处理", processing: "处理中", resolved: "已解决", closed: "已关闭",
};

/** 平台侧工单处理台：看到所有租户提交的请求，标记处理状态并留下回复。 */
export default function PlatformTickets() {
  const [list, setList] = useState<TicketItem[]>([]);
  const [tenantNames, setTenantNames] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      fetchPlatformTickets(filter || undefined),
      fetchTenantExtended(100),
    ]).then(([tickets, tenants]) => {
      setList(tickets.items);
      setTenantNames(Object.fromEntries(tenants.map((t) => [t.id, t.name || t.displayName])));
      setLoading(false);
    });
  };
  useEffect(load, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const handle = async (id: string, status: "processing" | "resolved" | "closed") => {
    setBusy(true); setMsg("");
    const r = await replyTicket(id, status, note);
    setBusy(false);
    if (!r.ok) { setMsg("处理失败：" + r.msg); return; }
    setMsg("已更新工单状态"); setNote(""); setExpanded(""); load();
  };

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        客户通过「平台工单」提交的申请和问题会汇总在这里。处理后请留下回复，客户在自己的工作台就能看到。
      </div>
      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>平台工单处理台</CardTitle>
            <div className="flex gap-2">
              {[["", "全部"], ["open", "待处理"], ["processing", "处理中"], ["resolved", "已解决"]].map(([v, l]) => (
                <button key={v} onClick={() => setFilter(v)} className="px-2.5 py-1 rounded-full text-[12px] border"
                  style={{ borderColor: C.border, background: filter === v ? C.soft : "transparent", color: filter === v ? C.primary : C.mid }}>
                  {l}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {msg && <div className="text-[13px] mb-3" style={{ color: C.mid }}>{msg}</div>}
          {loading ? (
            <div className="flex items-center gap-2 py-10 justify-center text-[14px]" style={{ color: C.light }}>
              <Loader2 className="w-4 h-4 animate-spin" />加载中…
            </div>
          ) : list.length === 0 ? (
            <div className="py-10 text-center text-[14px]" style={{ color: C.light }}>暂无工单。</div>
          ) : (
            <div className="space-y-3">
              {list.map((t) => (
                <div key={t.id} className="rounded-lg border p-4" style={{ borderColor: C.border }}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[14px] font-medium" style={{ color: C.ink }}>
                        {t.title} <span className="text-[12px] font-normal" style={{ color: C.light }}>
                          [{STATUS_TEXT[t.status] || t.status}]
                        </span>
                      </div>
                      <div className="text-[12px] mt-1" style={{ color: C.light }}>
                        {t.ticket_no} · {tenantNames[t.tenant_id] || t.tenant_id} · {t.category} · {bjTime(t.created_at)}
                      </div>
                    </div>
                    <Button variant="outline" size="sm" className="text-[12px]"
                      onClick={() => { setExpanded(expanded === t.id ? "" : t.id); setNote(t.handler_note || ""); }}>
                      {expanded === t.id ? "收起" : "处理"}
                    </Button>
                  </div>
                  <div className="text-[13px] mt-2 leading-relaxed" style={{ color: C.mid }}>{t.content}</div>
                  {t.handler_note && (
                    <div className="text-[13px] mt-2 rounded-md p-2" style={{ background: C.soft, color: C.primary }}>
                      已有回复：{t.handler_note}
                    </div>
                  )}
                  {expanded === t.id && (
                    <div className="mt-3 space-y-2 border-t pt-3" style={{ borderColor: C.border }}>
                      <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                        placeholder="给客户的回复（客户可见）"
                        className="w-full px-3 py-2 rounded-lg border text-[13px] outline-none resize-y"
                        style={{ borderColor: C.border }} />
                      <div className="flex gap-2">
                        <Button size="sm" disabled={busy} className="text-white text-[12px]" style={{ background: C.primary }}
                          onClick={() => handle(t.id, "processing")}>标记处理中</Button>
                        <Button size="sm" disabled={busy} variant="outline" className="text-[12px]"
                          onClick={() => handle(t.id, "resolved")}>标记已解决</Button>
                      </div>
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
