import { useEffect, useState } from "react";
import {
  BellRing, Wrench, Megaphone, AlertTriangle, Info, Loader2, Ticket,
} from "lucide-react";
import { C } from "@/lib/types";
import { bjTime } from "@/pages/MyTickets";
import {
  fetchMyNotices, createSupportTicket,
  type MyNoticesOverview, type NoticeItem, type TenantAlert,
} from "@/lib/api";

/** 机构端「平台公告与告警」——全部真实数据：
 *  公告 = 超管发布的 PlatformNotice（按本租户收窄）
 *  告警 = 后端从配额/套餐/工单/调用错误率真表实时算，不用假数。 */

const catStyle: Record<string, { bg: string; fg: string; icon: typeof Wrench }> = {
  维护: { bg: "#FBF3DC", fg: "#8A6A1F", icon: Wrench },
  公告: { bg: "#E8F0FE", fg: "#3B6FC4", icon: Megaphone },
  告警: { bg: "#FDECEA", fg: "#B03A2E", icon: AlertTriangle },
};
const sevStyle: Record<string, { bg: string; fg: string; icon: typeof BellRing }> = {
  danger: { bg: "#FDECEA", fg: "#B03A2E", icon: AlertTriangle },
  warning: { bg: "#FBF3DC", fg: "#8A6A1F", icon: AlertTriangle },
  info: { bg: "#E8F0FE", fg: "#3B6FC4", icon: Info },
};
const sevLabel: Record<string, string> = { danger: "严重", warning: "提醒", info: "提示" };

/** 公告时间展示：维护类若有"02:00-06:00"时段在 content 里带出，标题行只显示发布日期 */
function noticeDate(n: NoticeItem): string {
  if (!n.published_at) return "—";
  return bjTime(n.published_at).slice(0, 16) + " 发布";
}

export default function MyNotices() {
  const [data, setData] = useState<MyNoticesOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [ticketOpen, setTicketOpen] = useState<string | null>(null);
  const [ticketTitle, setTicketTitle] = useState("");
  const [ticketContent, setTicketContent] = useState("");
  const [ticketMsg, setTicketMsg] = useState("");

  useEffect(() => {
    let alive = true;
    fetchMyNotices()
      .then((d) => { if (alive) setData(d); })
      .catch(() => { /* 接口异常走占位，不造假 */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const submitTicket = async () => {
    if (!ticketTitle.trim() || !ticketContent.trim()) {
      setTicketMsg("请填写标题和说明"); return;
    }
    const ok = await createSupportTicket({
      category: "咨询", title: ticketTitle.trim(), content: ticketContent.trim(), priority: "normal",
    });
    setTicketMsg(ok ? "工单已提交，可在「工单中心」查看进度" : "提交失败，请稍后重试");
    if (ok) { setTicketOpen(null); setTicketTitle(""); setTicketContent(""); }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-[15px]" style={{ color: C.light }}>
        <Loader2 className="w-4 h-4 animate-spin mr-2" />公告与告警加载中...
      </div>
    );
  }
  if (!data) {
    return (
      <div className="rounded-xl p-8 text-center text-[15px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        公告与告警暂不可用，请稍后刷新或联系客户经理。
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 顶部概览 */}
      <div className="rounded-xl p-5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div className="flex items-center gap-2">
          <BellRing className="w-5 h-5" style={{ color: C.primary }} />
          <span className="text-[17px] font-semibold" style={{ color: C.primary }}>平台公告与告警</span>
        </div>
        <p className="text-[13px] mt-2 leading-relaxed" style={{ color: C.mid }}>
          共 <b style={{ color: C.primary }}>{data.announcements.length}</b> 条公告 ·
          <b style={{ color: data.alerts.length ? "#B03A2E" : C.primary }}> {data.alerts.length} </b>条告警。
          告警由平台根据您账户的真实用量、套餐和工单状态实时生成，非演示数据。
        </p>
      </div>

      {/* 告警区（有才显示） */}
      {data.alerts.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4" style={{ color: "#B03A2E" }} />
            <h2 className="text-[16px] font-semibold" style={{ color: C.ink }}>账户告警</h2>
            <span className="px-2 py-0.5 rounded-full text-[12px]" style={{ background: "#FDECEA", color: "#B03A2E" }}>
              {data.alerts.length} 条
            </span>
          </div>
          <div className="space-y-2">
            {data.alerts.map((a: TenantAlert) => {
              const st = sevStyle[a.severity] || sevStyle.info;
              const Icon = st.icon;
              return (
                <div key={a.id} className="rounded-xl p-4 bg-white flex items-start gap-3"
                  style={{ border: `1px solid ${C.border}`, borderLeft: `4px solid ${st.fg}` }}>
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                    style={{ background: st.bg }}>
                    <Icon className="w-4 h-4" style={{ color: st.fg }} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[14px] font-semibold" style={{ color: C.ink }}>{a.title}</span>
                      <span className="px-1.5 py-0.5 rounded text-[11px]" style={{ background: st.bg, color: st.fg }}>
                        {sevLabel[a.severity] || "提示"}
                      </span>
                    </div>
                    <p className="text-[13px] mt-1 leading-relaxed" style={{ color: C.mid }}>{a.detail}</p>
                    <div className="text-[12px] mt-1.5" style={{ color: C.light }}>
                      {a.timestamp ? bjTime(a.timestamp) : "—"}
                      {(a.type === "quota" || a.type === "expiry") && (
                        <button className="ml-3 underline" style={{ color: C.primary }}
                          onClick={() => setTicketOpen(a.id)}>联系客户经理</button>
                      )}
                    </div>
                    {ticketOpen === a.id && (
                      <div className="mt-3 rounded-lg p-3 space-y-2" style={{ background: C.bg, border: `1px solid ${C.border}` }}>
                        <input className="w-full rounded px-3 py-2 text-[13px]" style={{ border: `1px solid ${C.border}`, background: "#fff" }}
                          placeholder="标题（如：申请扩容）" value={ticketTitle} onChange={(e) => setTicketTitle(e.target.value)} />
                        <textarea className="w-full rounded px-3 py-2 text-[13px]" rows={2}
                          style={{ border: `1px solid ${C.border}`, background: "#fff" }}
                          placeholder="说明需求…" value={ticketContent} onChange={(e) => setTicketContent(e.target.value)} />
                        <div className="flex items-center gap-3">
                          <button className="px-3 py-1.5 rounded text-[13px] text-white" style={{ background: C.primary }}
                            onClick={submitTicket}>提交工单</button>
                          <button className="px-3 py-1.5 rounded text-[13px]" style={{ color: C.mid }}
                            onClick={() => setTicketOpen(null)}>取消</button>
                          {ticketMsg && <span className="text-[12px]" style={{ color: C.mid }}>{ticketMsg}</span>}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 公告区 */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <Megaphone className="w-4 h-4" style={{ color: C.primary }} />
          <h2 className="text-[16px] font-semibold" style={{ color: C.ink }}>平台公告</h2>
          <span className="px-2 py-0.5 rounded-full text-[12px]" style={{ background: C.soft, color: C.primary }}>
            {data.announcements.length} 条
          </span>
        </div>
        {data.announcements.length === 0 ? (
          <div className="rounded-xl p-6 text-center text-[14px]" style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.light }}>
            暂无平台公告
          </div>
        ) : (
          <div className="rounded-xl bg-white" style={{ border: `1px solid ${C.border}` }}>
            {data.announcements.map((n: NoticeItem, idx: number) => {
              const cs = catStyle[n.category] || catStyle["公告"];
              const Icon = cs.icon;
              return (
                <div key={n.id} className="flex items-center gap-3 px-4 py-4"
                  style={{ borderBottom: idx < data.announcements.length - 1 ? `1px solid ${C.border}` : "none" }}>
                  <span className="px-2 py-0.5 rounded text-[11px] shrink-0 inline-flex items-center gap-1"
                    style={{ background: cs.bg, color: cs.fg }}>
                    <Icon className="w-3 h-3" />{n.category}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[14px] font-medium truncate" style={{ color: C.ink }}>{n.title}</div>
                    {n.content && <div className="text-[12px] mt-0.5 truncate" style={{ color: C.light }}>{n.content}</div>}
                  </div>
                  <span className="text-[12px] shrink-0" style={{ color: C.light }}>{noticeDate(n)}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="flex items-center gap-2 text-[12px]" style={{ color: C.light }}>
        <Ticket className="w-3.5 h-3.5" />
        如有疑问可到「工单中心」提交咨询，平台会在处理后通知您。
      </div>
    </div>
  );
}
