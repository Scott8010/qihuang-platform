import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Boxes, Globe, Lock, FilePlus2, Send, CheckCircle2, XCircle, Loader2,
  ShieldCheck, Eye,
} from "lucide-react";
import { C } from "@/lib/types";
import {
  fetchCapabilityTemplates, fetchCapabilitySubmissions, createCapabilityTemplate,
  submitCapabilityTemplate, approveCapabilitySubmission, rejectCapabilitySubmission,
  type CapabilityTemplate, type CapabilitySubmission,
} from "@/lib/api";
import { toast } from "sonner";

/* ═══════════════════════════════════════════
   多租户能力中心 — 模板市场 + 平台审核工作台
   后端 /admin/v1/template-center/*（已上线）
   ═══════════════════════════════════════════ */

const KIND_LABEL: Record<string, string> = {
  herb: "中药", formula: "方剂", syndrome: "证候", disease: "疾病",
  script: "话术脚本", product: "产品培训", project: "项目培训", knowledge: "知识课件", other: "其他",
};

function visInfo(v: string | null | undefined) {
  if (v === "platform") return { label: "平台模板", color: "#2E5A4C", bg: "#EAF2EE" };
  if (v === "public") return { label: "共享池", color: "#8A6A1F", bg: "#FBF4E4" };
  return { label: "私有", color: "#5F5E5A", bg: "#F1EFE8" };
}

function TemplateRow({ t, onView, onSubmit }: {
  t: CapabilityTemplate;
  onView: (t: CapabilityTemplate) => void;
  onSubmit: (t: CapabilityTemplate) => void;
}) {
  const vis = visInfo(t.ownership?.visibility);
  const isPlatform = t.ownership?.source === "platform";
  return (
    <tr className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
      <td className="px-4 py-3">
        <div className="font-medium" style={{ color: C.ink }}>{t.name}</div>
        <div className="text-[11px] font-mono" style={{ color: C.light }}>{t.id.slice(0, 12)}…</div>
      </td>
      <td className="px-3 py-3">
        <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: C.soft, color: C.primary }}>
          {KIND_LABEL[t.kind] || t.kind}
        </span>
      </td>
      <td className="px-3 py-3" style={{ color: C.mid }}>{t.current_version}</td>
      <td className="px-3 py-3">
        <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium" style={{ color: vis.color, background: vis.bg }}>
          {vis.label === "共享池" ? <Globe className="w-3 h-3" /> : vis.label === "私有" ? <Lock className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
          {vis.label}
        </span>
        {isPlatform && <span className="ml-1.5 text-[11px] px-1.5 py-0.5 rounded" style={{ background: "#F5EDD9", color: "#8A6A1F" }}>官方</span>}
      </td>
      <td className="px-3 py-3 text-[12px]" style={{ color: C.light }}>
        {(t.created_at || "").slice(0, 10)}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="inline-flex items-center gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-[12px]" style={{ color: C.mid }}
            onClick={() => onView(t)}>
            <Eye className="w-3.5 h-3.5 mr-1" /> 详情
          </Button>
          {!isPlatform && (
            <Button size="sm" variant="outline" className="h-7 text-[12px]" style={{ color: C.primary }}
              onClick={() => onSubmit(t)}>
              <Send className="w-3.5 h-3.5 mr-1" /> 提交审核
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function CapabilityCenter() {
  const [tab, setTab] = useState<"templates" | "reviews">("templates");
  const [templates, setTemplates] = useState<CapabilityTemplate[]>([]);
  const [submissions, setSubmissions] = useState<CapabilitySubmission[]>([]);
  const [loading, setLoading] = useState(true);

  // 新建模板
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState("script");
  const [newContent, setNewContent] = useState("");
  const [creating, setCreating] = useState(false);

  // 详情
  const [viewTpl, setViewTpl] = useState<CapabilityTemplate | null>(null);

  // 审核
  const [reviewSub, setReviewSub] = useState<CapabilitySubmission | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewing, setReviewing] = useState(false);

  const load = async () => {
    setLoading(true);
    const [ts, ss] = await Promise.all([fetchCapabilityTemplates(), fetchCapabilitySubmissions()]);
    setTemplates(ts);
    setSubmissions(ss);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const doCreate = async () => {
    if (!newName.trim()) { toast.error("请填写模板名称"); return; }
    let contentJson: Record<string, unknown> = {};
    try {
      contentJson = newContent.trim() ? JSON.parse(newContent) : { note: "空模板" };
    } catch {
      toast.error("content JSON 格式不正确");
      return;
    }
    setCreating(true);
    const r = await createCapabilityTemplate({ name: newName.trim(), kind: newKind, content_json: contentJson });
    setCreating(false);
    if (r.ok) {
      toast.success("模板已创建");
      setCreateOpen(false);
      setNewName(""); setNewKind("script"); setNewContent("");
      await load();
    } else {
      toast.error(r.msg || "创建失败");
    }
  };

  const doSubmit = async (t: CapabilityTemplate) => {
    const r = await submitCapabilityTemplate(t.id);
    if (r.ok) {
      toast.success(`已提交审核：${t.name}`);
      await load();
    } else {
      toast.error(r.msg || "提交失败");
    }
  };

  const doReview = async (approve: boolean) => {
    if (!reviewSub) return;
    setReviewing(true);
    const r = approve
      ? await approveCapabilitySubmission(reviewSub.id, reviewNote)
      : await rejectCapabilitySubmission(reviewSub.id, reviewNote);
    setReviewing(false);
    if (r.ok) {
      toast.success(approve ? "已采纳，模板进入共享池" : "已强下架，模板收回私有");
      setReviewSub(null);
      setReviewNote("");
      await load();
    } else {
      toast.error(r.msg || (approve ? "采纳失败" : "下架失败"));
    }
  };

  const pendingCount = submissions.filter((s) => s.status === "PENDING").length;

  return (
    <div className="space-y-4">
      {/* 标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Boxes className="w-5 h-5" style={{ color: C.primary }} />
          <span className="text-[15px] font-semibold" style={{ color: C.primary }}>能力中心</span>
          <span className="text-[12px]" style={{ color: C.light }}>多租户能力模板 · 平台↔机构归属全模型</span>
        </div>
        <Button size="sm" style={{ background: C.primary }} onClick={() => setCreateOpen(true)}>
          <FilePlus2 className="w-4 h-4 mr-1" /> 新建模板
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b pb-2" style={{ borderColor: C.border }}>
        <button
          className="px-3 py-1.5 rounded-t-md text-[13px] font-medium transition-colors"
          style={{ color: tab === "templates" ? C.primary : C.light, background: tab === "templates" ? C.soft : "transparent", borderBottom: tab === "templates" ? `2px solid ${C.primary}` : "2px solid transparent" }}
          onClick={() => setTab("templates")}
        >
          模板市场（{templates.length}）
        </button>
        <button
          className="px-3 py-1.5 rounded-t-md text-[13px] font-medium transition-colors"
          style={{ color: tab === "reviews" ? C.primary : C.light, background: tab === "reviews" ? C.soft : "transparent", borderBottom: tab === "reviews" ? `2px solid ${C.primary}` : "2px solid transparent" }}
          onClick={() => setTab("reviews")}
        >
          审核工作台
          {pendingCount > 0 && (
            <span className="ml-1.5 text-[11px] px-1.5 py-0.5 rounded-full" style={{ background: "#FDECEA", color: "#B03A2E" }}>{pendingCount}</span>
          )}
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[13px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 加载能力中心…
        </div>
      )}

      {/* ─── Tab 1: 模板市场 ─── */}
      {tab === "templates" && !loading && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-0">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: C.border, background: C.soft }}>
                  <th className="px-4 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>模板</th>
                  <th className="px-3 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>类型</th>
                  <th className="px-3 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>版本</th>
                  <th className="px-3 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>归属</th>
                  <th className="px-3 py-3 text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>创建时间</th>
                  <th className="px-4 py-3 text-right text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <TemplateRow key={t.id} t={t} onView={setViewTpl} onSubmit={doSubmit} />
                ))}
                {templates.length === 0 && (
                  <tr><td colSpan={6} className="py-10 text-center text-[12px]" style={{ color: C.light }}>暂无模板</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* ─── Tab 2: 审核工作台 ─── */}
      {tab === "reviews" && !loading && (
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-0">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left" style={{ borderColor: C.border, background: C.soft }}>
                  <th className="px-4 py-3 text-[12px] font-semibold" style={{ color: C.mid }}>审核单</th>
                  <th className="px-3 py-3 text-[12px] font-semibold" style={{ color: C.mid }}>提交机构</th>
                  <th className="px-3 py-3 text-[12px] font-semibold" style={{ color: C.mid }}>状态</th>
                  <th className="px-3 py-3 text-[12px] font-semibold" style={{ color: C.mid }}>提交时间</th>
                  <th className="px-3 py-3 text-[12px] font-semibold" style={{ color: C.mid }}>审核意见</th>
                  <th className="px-4 py-3 text-right text-[12px] font-semibold" style={{ color: C.mid }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {submissions.map((s) => {
                  const tpl = templates.find((t) => t.id === s.template_id);
                  const st = s.status === "PENDING" ? { label: "待审核", color: "#8A6A1F", bg: "#FBF4E4" }
                    : s.status === "APPROVED" ? { label: "已采纳", color: "#2E5A4C", bg: "#EAF2EE" }
                    : { label: "已驳回", color: "#B03A2E", bg: "#FDECEA" };
                  return (
                    <tr key={s.id} className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="px-4 py-3">
                        <div className="font-medium" style={{ color: C.ink }}>{tpl?.name || s.template_id.slice(0, 12)}</div>
                        <div className="text-[11px] font-mono" style={{ color: C.light }}>{s.id.slice(0, 12)}…</div>
                      </td>
                      <td className="px-3 py-3" style={{ color: C.mid }}>{s.submitter_org_id || "—"}</td>
                      <td className="px-3 py-3">
                        <span className="text-[11px] px-2 py-0.5 rounded-full font-medium" style={{ color: st.color, background: st.bg }}>{st.label}</span>
                      </td>
                      <td className="px-3 py-3 text-[12px]" style={{ color: C.light }}>{(s.submitted_at || "").replace("T", " ").slice(0, 16)}</td>
                      <td className="px-3 py-3 text-[12px] max-w-[160px] truncate" style={{ color: C.light }} title={s.review_note || ""}>{s.review_note || "—"}</td>
                      <td className="px-4 py-3 text-right">
                        {s.status === "PENDING" ? (
                          <Button size="sm" variant="outline" className="h-7 text-[12px]" style={{ color: C.primary }}
                            onClick={() => { setReviewSub(s); setReviewNote(""); }}>
                            <ShieldCheck className="w-3.5 h-3.5 mr-1" /> 审核
                          </Button>
                        ) : (
                          <span className="text-[11px]" style={{ color: C.light }}>
                            {s.reviewed_at ? s.reviewed_at.replace("T", " ").slice(0, 16) : "—"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {submissions.length === 0 && (
                  <tr><td colSpan={6} className="py-10 text-center text-[12px]" style={{ color: C.light }}>暂无审核单</td></tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <div className="text-[11px]" style={{ color: C.light }}>
        归属模型：平台模板（source=platform）全网可见；机构自建（private）仅本机构；提交平台审核通过后提升为共享池（public），驳回则强收回私有。
      </div>

      {/* 新建模板 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建能力模板</DialogTitle>
            <DialogDescription>创建平台级或机构级模板，提交审核通过后进入共享池。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[12px]">名称</Label>
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="如：门店接单话术模板" className="mt-1 h-8" />
            </div>
            <div>
              <Label className="text-[12px]">类型</Label>
              <select value={newKind} onChange={(e) => setNewKind(e.target.value)}
                className="w-full text-[13px] rounded-lg border px-3 py-2 bg-white outline-none mt-1" style={{ borderColor: C.border }}>
                {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <Label className="text-[12px]">内容（JSON）</Label>
              <textarea value={newContent} onChange={(e) => setNewContent(e.target.value)}
                placeholder='{"steps": ["欢迎语", "需求挖掘", "价值塑造"]}'
                className="w-full text-[12px] font-mono rounded-lg border p-2 outline-none mt-1 h-24"
                style={{ borderColor: C.border }} />
            </div>
          </div>
          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button size="sm" style={{ background: C.primary }} disabled={creating} onClick={doCreate}>
              {creating && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 模板详情 */}
      <Dialog open={!!viewTpl} onOpenChange={(o) => { if (!o) setViewTpl(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>模板详情</DialogTitle>
          </DialogHeader>
          {viewTpl && (
            <div className="space-y-2 text-[13px]">
              <div><span style={{ color: C.light }}>名称：</span><b>{viewTpl.name}</b></div>
              <div><span style={{ color: C.light }}>类型：</span>{KIND_LABEL[viewTpl.kind] || viewTpl.kind} · 版本 {viewTpl.current_version}</div>
              <div><span style={{ color: C.light }}>归属：</span>{visInfo(viewTpl.ownership?.visibility).label}（{viewTpl.ownership?.source || "—"}）</div>
              <div><span style={{ color: C.light }}>创建：</span>{viewTpl.created_at || "—"}</div>
              <div>
                <div className="text-[12px] mb-1" style={{ color: C.light }}>内容：</div>
                <pre className="text-[11px] bg-[#F8FAF9] rounded p-2 overflow-auto max-h-48 font-mono" style={{ color: C.mid }}>
                  {JSON.stringify(viewTpl.content_json, null, 2)}
                </pre>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => setViewTpl(null)}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 审核弹窗 */}
      <Dialog open={!!reviewSub} onOpenChange={(o) => { if (!o) setReviewSub(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>审核模板提交</DialogTitle>
            <DialogDescription>
              {(() => {
                const tpl = reviewSub ? templates.find((t) => t.id === reviewSub.template_id) : null;
                return tpl ? `「${tpl.name}」提交自 ${reviewSub?.submitter_org_id || "—"}。采纳=进入共享池；驳回=强收回私有。` : "模板提交审核";
              })()}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label className="text-[12px]">审核意见</Label>
            <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}
              placeholder="填写采纳/驳回理由（必填）"
              className="w-full text-[12px] rounded-lg border p-2 outline-none h-20" style={{ borderColor: C.border }} />
          </div>
          <DialogFooter className="gap-2">
            <Button size="sm" variant="outline" onClick={() => setReviewSub(null)}>取消</Button>
            <Button size="sm" style={{ background: "#B03A2E" }} disabled={reviewing || !reviewNote.trim()} onClick={() => doReview(false)}>
              {reviewing ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <XCircle className="w-3.5 h-3.5 mr-1" />}驳回
            </Button>
            <Button size="sm" style={{ background: C.primary }} disabled={reviewing || !reviewNote.trim()} onClick={() => doReview(true)}>
              {reviewing ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1" />}采纳
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}