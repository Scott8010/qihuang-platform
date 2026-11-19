import { useEffect, useState } from "react";
import { BellRing, Megaphone, Loader2, Plus, Wrench, AlertTriangle } from "lucide-react";
import { C } from "@/lib/types";
import { bjTime } from "@/pages/MyTickets";
import {
  fetchAdminNotices, publishNotice, setNoticeStatus, fetchTenants,
  type NoticeItem,
} from "@/lib/api";

/** 超管端「平台公告」管理：发布维护/公告/告警，全体或指定租户；下架/重新发布。 */

const catStyle: Record<string, { bg: string; fg: string; icon: typeof Wrench }> = {
  维护: { bg: "#FBF3DC", fg: "#8A6A1F", icon: Wrench },
  公告: { bg: "#E8F0FE", fg: "#3B6FC4", icon: Megaphone },
  告警: { bg: "#FDECEA", fg: "#B03A2E", icon: AlertTriangle },
};

export default function AdminNotices() {
  const [rows, setRows] = useState<NoticeItem[]>([]);
  const [tenants, setTenants] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("公告");
  const [audience, setAudience] = useState("all");
  const [targetTenant, setTargetTenant] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([fetchAdminNotices(), fetchTenants()])
      .then(([n, t]) => { setRows(n); setTenants(t.map((x) => ({ id: x.id, name: x.name }))); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const submit = async () => {
    if (!title.trim() || !content.trim()) { setMsg("请填写标题和内容"); return; }
    if (audience === "tenant" && !targetTenant) { setMsg("请选择目标租户"); return; }
    setBusy(true);
    const ok = await publishNotice({
      title: title.trim(), content: content.trim(), category, audience,
      target_tenant_id: audience === "tenant" ? targetTenant : undefined,
      status: "published",
    });
    setBusy(false);
    setMsg(ok ? "公告已发布" : "发布失败，请重试");
    if (ok) {
      setTitle(""); setContent(""); setShowForm(false);
      load();
    }
  };

  const changeStatus = async (id: string, status: "published" | "withdrawn") => {
    const ok = await setNoticeStatus(id, status);
    setMsg(ok ? (status === "published" ? "已重新发布" : "已下架") : "操作失败");
    if (ok) load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BellRing className="w-5 h-5" style={{ color: C.primary }} />
          <h2 className="text-[17px] font-semibold" style={{ color: C.ink }}>平台公告</h2>
          <span className="text-[12px]" style={{ color: C.light }}>发布的公告会出现在机构端「平台公告与告警」</span>
        </div>
        <button onClick={() => setShowForm(!showForm)}
          className="px-3 py-2 rounded-lg text-[13px] text-white inline-flex items-center gap-1.5" style={{ background: C.primary }}>
          <Plus className="w-4 h-4" />发布公告
        </button>
      </div>

      {msg && <div className="text-[13px] px-3 py-2 rounded-lg" style={{ background: C.soft, color: C.primary }}>{msg}</div>}

      {showForm && (
        <div className="rounded-xl p-5 bg-white space-y-3" style={{ border: `1px solid ${C.border}` }}>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-3">
              <label className="text-[12px]" style={{ color: C.mid }}>标题</label>
              <input className="w-full mt-1 rounded px-3 py-2 text-[13px]" style={{ border: `1px solid ${C.border}` }}
                value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：华东1可用区B网络设备升级维护" />
            </div>
            <div>
              <label className="text-[12px]" style={{ color: C.mid }}>分类</label>
              <select className="w-full mt-1 rounded px-3 py-2 text-[13px]" style={{ border: `1px solid ${C.border}`, background: "#fff" }}
                value={category} onChange={(e) => setCategory(e.target.value)}>
                <option>维护</option><option>公告</option><option>告警</option>
              </select>
            </div>
            <div>
              <label className="text-[12px]" style={{ color: C.mid }}>接收范围</label>
              <select className="w-full mt-1 rounded px-3 py-2 text-[13px]" style={{ border: `1px solid ${C.border}`, background: "#fff" }}
                value={audience} onChange={(e) => setAudience(e.target.value)}>
                <option value="all">全体租户</option><option value="tenant">指定租户</option>
              </select>
            </div>
            {audience === "tenant" && (
              <div>
                <label className="text-[12px]" style={{ color: C.mid }}>目标租户</label>
                <select className="w-full mt-1 rounded px-3 py-2 text-[13px]" style={{ border: `1px solid ${C.border}`, background: "#fff" }}
                  value={targetTenant} onChange={(e) => setTargetTenant(e.target.value)}>
                  <option value="">请选择…</option>
                  {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </div>
            )}
            <div className="lg:col-span-3">
              <label className="text-[12px]" style={{ color: C.mid }}>内容</label>
              <textarea className="w-full mt-1 rounded px-3 py-2 text-[13px]" rows={3}
                style={{ border: `1px solid ${C.border}` }} value={content}
                onChange={(e) => setContent(e.target.value)} placeholder="公告正文 / 维护时段 / 影响说明…" />
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy}
              className="px-4 py-2 rounded-lg text-[13px] text-white" style={{ background: C.primary }}>
              {busy ? "发布中…" : "确认发布"}
            </button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 rounded-lg text-[13px]" style={{ color: C.mid }}>取消</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin mr-2" />公告加载中...
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-xl p-8 text-center text-[14px]" style={{ background: "#fff", border: `1px solid ${C.border}`, color: C.light }}>
          暂无公告，点右上角「发布公告」创建第一条。
        </div>
      ) : (
        <div className="rounded-xl bg-white overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
          {rows.map((n, idx) => {
            const cs = catStyle[n.category] || catStyle["公告"];
            const Icon = cs.icon;
            return (
              <div key={n.id} className="flex items-center gap-3 px-5 py-3"
                style={{ borderBottom: idx < rows.length - 1 ? `1px solid ${C.border}` : "none" }}>
                <span className="px-2 py-0.5 rounded text-[11px] inline-flex items-center gap-1 shrink-0"
                  style={{ background: cs.bg, color: cs.fg }}><Icon className="w-3 h-3" />{n.category}</span>
                <span className="text-[11px] px-2 py-0.5 rounded shrink-0"
                  style={{ background: C.bg, color: C.mid }}>{n.audience === "all" ? "全体" : "指定租户"}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium truncate" style={{ color: C.ink }}>{n.title}</div>
                  <div className="text-[12px] truncate" style={{ color: C.light }}>{n.content}</div>
                </div>
                <span className="text-[12px] shrink-0" style={{ color: C.light }}>
                  {n.published_at ? bjTime(n.published_at).slice(0, 16) : "—"}
                </span>
                <button onClick={() => changeStatus(n.id, "withdrawn")}
                  className="px-2 py-1 rounded text-[12px] shrink-0" style={{ color: "#B03A2E", border: `1px solid #F3C9C4` }}>
                  下架
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
