import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Plus, Search, Boxes, Loader2, Clock, UploadCloud, X, FileText, Lock, CheckCircle2 } from "lucide-react";
import { C, sceneMap, statusMap } from "@/lib/types";
import { fetchTenants, fetchPlans, createTenant, deleteTenant, uploadFile } from "@/lib/api";
import { toast } from "sonner";
import type { Tenant, PlanItem } from "@/lib/types";
import TenantDetail from "./TenantDetail";

const tabs = [
  { id: "ALL", label: "全部租户" },
  { id: "MED", label: "医疗" },
  { id: "HEALTH", label: "大健康" },
  { id: "EDU", label: "培训" },
];

export default function Tenants({ go }: { go: (p: string) => void }) {
  const [list, setList] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("ALL");
  const [kw, setKw] = useState("");
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Tenant | null>(null);
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState<"" | "business" | "medical">("");
  const [form, setForm] = useState({
    name: "", code: "", scene: "HEALTH", plan: "standard",
    contactName: "", contactPhone: "", contactEmail: "",
    addressCountry: "中国", addressProvince: "", addressCity: "", addressDistrict: "", addressDetail: "",
    orgIntro: "",
    licenseBusiness: "", licenseBusinessName: "",
    licenseMedical: "", licenseMedicalName: "",
  });

  // 电话：手机 11 位 / 座机带区号；邮箱常规校验（与后端 _ONBOARD_* 一致）
  const PHONE_RE = /^(1[3-9]\d{9}|(\+?\d{1,4}-)?0\d{2,3}-?\d{7,8})$/;
  const EMAIL_RE = /^[\w.+-]+@[\w-]+(\.[\w-]+)+$/;

  // 打开弹窗时拉真实套餐库（价格/配额/说明一并展示，不硬编码）
  useEffect(() => {
    if (!open || plans.length) return;
    fetchPlans().then((ps) => {
      const active = ps.filter((p) => p.status !== "disabled");
      setPlans(active);
      if (active.length && !active.some((p) => p.planName === form.plan)) {
        setForm((f) => ({ ...f, plan: active[0].planName }));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 删除
  const [delTenant, setDelTenant] = useState<Tenant | null>(null);
  const [deleting, setDeleting] = useState(false);

  const doDelete = async () => {
    if (!delTenant) return;
    setDeleting(true);
    const r = await deleteTenant(delTenant.id);
    setDeleting(false);
    if (r.ok) {
      toast.success(`已删除租户 ${delTenant.name}`);
      setDelTenant(null);
      await load();
    } else {
      toast.error(r.msg || "删除失败");
    }
  };

  const load = async () => {
    setLoading(true);
    const data = await fetchTenants();
    setList(data);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const shown = list.filter(
    (t) => (tab === "ALL" || t.scene === tab) && (!kw || t.name.includes(kw) || (t.code || "").includes(kw) || t.id.includes(kw))
  );

  const create = async () => {
    if (!form.name.trim()) { toast.error("请填写机构名称"); return; }
    if (!form.contactName.trim()) { toast.error("请填写联系人姓名"); return; }
    if (!form.contactPhone.trim()) { toast.error("请填写联系电话"); return; }
    if (!PHONE_RE.test(form.contactPhone.trim())) {
      toast.error("电话格式不正确：手机须为 11 位（1 开头），座机须带区号（如 021-12345678）"); return;
    }
    if (form.contactEmail.trim() && !EMAIL_RE.test(form.contactEmail.trim())) { toast.error("电子邮箱格式不正确"); return; }
    const isMed = form.scene === "MED";
    if (isMed) {
      if (!form.licenseBusiness) { toast.error("医疗场景必须上传营业执照"); return; }
      if (!form.licenseMedical) { toast.error("医疗场景必须上传医疗机构执业许可证"); return; }
    }
    setSubmitting(true);
    const r: any = await createTenant({
      name: form.name.trim(),
      code: form.code.trim() || undefined,
      scene: form.scene,
      plan: form.plan,
      contactName: form.contactName.trim(),
      contactPhone: form.contactPhone.trim(),
      contactEmail: form.contactEmail.trim() || undefined,
      addressCountry: form.addressCountry.trim() || undefined,
      addressProvince: form.addressProvince.trim() || undefined,
      addressCity: form.addressCity.trim() || undefined,
      addressDistrict: form.addressDistrict.trim() || undefined,
      addressDetail: form.addressDetail.trim() || undefined,
      orgIntro: form.orgIntro.trim() || undefined,
      licenseBusiness: form.licenseBusiness || undefined,
      licenseBusinessName: form.licenseBusinessName || undefined,
      licenseMedical: form.licenseMedical || undefined,
      licenseMedicalName: form.licenseMedicalName || undefined,
      module3d: !!plans.find((p) => p.planName === form.plan)?.features?.module_3d,
    });
    setSubmitting(false);
    if (r?.code === 0) {
      toast.success(`租户 ${form.name} 开户成功：套餐已生效、根机构已创建`);
      setOpen(false);
      setForm({ name: "", code: "", scene: "HEALTH", plan: "standard", contactName: "", contactPhone: "", contactEmail: "", addressCountry: "中国", addressProvince: "", addressCity: "", addressDistrict: "", addressDetail: "", orgIntro: "", licenseBusiness: "", licenseBusinessName: "", licenseMedical: "", licenseMedicalName: "" });
      await load();
    } else {
      // 后端校验失败（如医疗两证缺失/电话格式）提示原话，不假装成功
      toast.error(r?.message || r?.msg || r?.detail?.[0]?.msg || "开户失败，请重试");
    }
  };

  // 证照上传（营业执照 / 医疗机构执业许可证）
  const handleUpload = async (kind: "business" | "medical", file: File) => {
    setUploading(kind);
    const r = await uploadFile(file, kind === "business" ? "license_business" : "license_medical");
    setUploading("");
    if (r.ok && r.data) {
      if (kind === "business") setForm({ ...form, licenseBusiness: r.data.url, licenseBusinessName: r.data.name });
      else setForm({ ...form, licenseMedical: r.data.url, licenseMedicalName: r.data.name });
      toast.success(`已上传 ${r.data.name}`);
    } else {
      toast.error(r.msg || "上传失败，请重试");
    }
  };

  if (detail) return <TenantDetail tenant={detail} onBack={() => setDetail(null)} go={go} />;

  return (
    <div className="space-y-4">
      {/* 顶部操作条 */}
      <div className="flex items-center gap-3">
        <div className="flex rounded-lg border bg-white p-1" style={{ borderColor: C.border }}>
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className="px-4 py-1.5 text-[13px] rounded-md transition-colors"
              style={{
                background: tab === t.id ? C.primary : "transparent",
                color: tab === t.id ? "#fff" : C.mid,
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
          <Input
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            placeholder="搜索租户名称 / ID"
            className="pl-9 w-60 text-[13px] bg-white"
            style={{ borderColor: C.border }}
          />
        </div>
        <div className="flex-1" />
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button style={{ background: C.primary }}>
              <Plus className="w-4 h-4 mr-1" /> 新建租户开户
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[680px] max-h-[88vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle style={{ color: C.primary }}>新建租户开户</DialogTitle>
              <DialogDescription className="text-xs" style={{ color: C.light }}>
                完整机构信息 + 资质证照 + 套餐订阅一次落库，全程审计留痕
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2 text-[13px]">
              {/* ── ① 机构信息 ── */}
              <div className="rounded-xl p-4 space-y-3" style={{ background: C.soft }}>
                <div className="text-[12px] font-semibold tracking-wider" style={{ color: C.primary }}>① 机构信息</div>
                <div className="space-y-1.5">
                  <Label>机构名称（合同主体）<span style={{ color: "#B03A2E" }}> *</span></Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如：某某中医馆连锁有限公司" />
                </div>
                <div className="space-y-1.5">
                  <Label>机构代号（code，可选）<span className="text-[11px]" style={{ color: C.light }}> · 留空自动生成 JGxxxx，替代复杂 uuid</span></Label>
                  <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="如 JG0007 或拼音 jbh（2-16 位大写字母/数字/下划线）" maxLength={16} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label>场景类型（创建后不可变更）<span style={{ color: "#B03A2E" }}> *</span></Label>
                    <Select value={form.scene} onValueChange={(v) => setForm({ ...form, scene: v })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="MED">医疗场景</SelectItem>
                        <SelectItem value="HEALTH">大健康场景</SelectItem>
                        <SelectItem value="EDU">培训学习场景</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>套餐<span style={{ color: "#B03A2E" }}> *</span></Label>
                    <Select value={form.plan} onValueChange={(v) => setForm({ ...form, plan: v })}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {plans.length === 0 && <div className="px-3 py-2 text-[12px]" style={{ color: C.light }}>套餐加载中…</div>}
                        {plans.map((p) => (
                          <SelectItem key={p.planName} value={p.planName}>
                            {p.name}（¥{(p.priceCents / 100).toFixed(0)}/月 · {p.monthCalls.toLocaleString()}次/月）
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label>机构地址<span className="text-[11px]" style={{ color: C.light }}> · 前 4 项为行政区划，详细地址单独填</span></Label>
                  <div className="grid grid-cols-2 gap-2 mt-1.5">
                    <Input value={form.addressCountry} onChange={(e) => setForm({ ...form, addressCountry: e.target.value })} placeholder="国家（如：中国）" />
                    <Input value={form.addressProvince} onChange={(e) => setForm({ ...form, addressProvince: e.target.value })} placeholder="省份（如：上海市）" />
                    <Input value={form.addressCity} onChange={(e) => setForm({ ...form, addressCity: e.target.value })} placeholder="城市（如：上海市）" />
                    <Input value={form.addressDistrict} onChange={(e) => setForm({ ...form, addressDistrict: e.target.value })} placeholder="区县（如：浦东新区）" />
                  </div>
                  <Input
                    className="mt-2"
                    value={form.addressDetail}
                    onChange={(e) => setForm({ ...form, addressDetail: e.target.value })}
                    placeholder="📍 详细地址（街道/门牌/楼栋/楼层/房间号，200 字内）"
                    maxLength={200}
                  />
                  {form.addressDetail && (
                    <div className="text-right text-[11px] mt-0.5" style={{ color: form.addressDetail.length >= 200 ? "#B03A2E" : C.light }}>
                      {form.addressDetail.length} / 200
                    </div>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label>机构介绍（限 150 字）</Label>
                  <Textarea
                    value={form.orgIntro}
                    onChange={(e) => setForm({ ...form, orgIntro: e.target.value })}
                    placeholder="机构简介、主营业务、服务范围等（医疗机构建议注明执业范围）"
                    rows={3}
                    maxLength={150}
                  />
                  <div className="text-right text-[11px]" style={{ color: form.orgIntro.length >= 150 ? "#B03A2E" : C.light }}>
                    {form.orgIntro.length}/150
                  </div>
                </div>
              </div>

              {/* ── ② 资质证照 ── */}
              <div className="rounded-xl p-4 space-y-3" style={{ background: "#FBF4E4" }}>
                <div className="text-[12px] font-semibold tracking-wider" style={{ color: C.gold }}>
                  ② 资质证照
                  {form.scene === "MED" && <span className="ml-2 text-[11px] font-normal" style={{ color: "#B03A2E" }}>医疗场景：两证必传</span>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label>营业执照{form.scene === "MED" ? <span style={{ color: "#B03A2E" }}> *</span> : <span className="text-[11px]" style={{ color: C.light }}>（选填）</span>}</Label>
                    <div className="flex items-center gap-2">
                      <input
                        type="file" id="lic-business" className="hidden" accept="image/*,.pdf"
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload("business", f); e.target.value = ""; }}
                      />
                      <label htmlFor="lic-business" className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium cursor-pointer border"
                        style={{ background: "#fff", color: C.primary, borderColor: C.border }}>
                        <UploadCloud className="w-3.5 h-3.5" />
                        {uploading === "business" ? "上传中…" : "选择文件"}
                      </label>
                      {form.licenseBusinessName && (
                        <span className="inline-flex items-center gap-1 text-[12px] truncate max-w-[130px]" style={{ color: C.mid }} title={form.licenseBusinessName}>
                          <FileText className="w-3.5 h-3.5 shrink-0" style={{ color: C.gold }} />
                          <span className="truncate">{form.licenseBusinessName}</span>
                          <button onClick={() => setForm({ ...form, licenseBusiness: "", licenseBusinessName: "" })} className="shrink-0" style={{ color: C.light }}><X className="w-3.5 h-3.5" /></button>
                        </span>
                      )}
                      {!form.licenseBusinessName && <span className="text-[12px]" style={{ color: C.light }}>未上传</span>}
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label>医疗机构执业许可证{form.scene === "MED" ? <span style={{ color: "#B03A2E" }}> *</span> : <span className="text-[11px]" style={{ color: C.light }}>（医疗专用）</span>}</Label>
                    <div className="flex items-center gap-2">
                      <input
                        type="file" id="lic-medical" className="hidden" accept="image/*,.pdf"
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload("medical", f); e.target.value = ""; }}
                      />
                      <label htmlFor="lic-medical" className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium cursor-pointer border"
                        style={{ background: "#fff", color: C.primary, borderColor: C.border }}>
                        <UploadCloud className="w-3.5 h-3.5" />
                        {uploading === "medical" ? "上传中…" : "选择文件"}
                      </label>
                      {form.licenseMedicalName && (
                        <span className="inline-flex items-center gap-1 text-[12px] truncate max-w-[130px]" style={{ color: C.mid }} title={form.licenseMedicalName}>
                          <FileText className="w-3.5 h-3.5 shrink-0" style={{ color: C.gold }} />
                          <span className="truncate">{form.licenseMedicalName}</span>
                          <button onClick={() => setForm({ ...form, licenseMedical: "", licenseMedicalName: "" })} className="shrink-0" style={{ color: C.light }}><X className="w-3.5 h-3.5" /></button>
                        </span>
                      )}
                      {!form.licenseMedicalName && <span className="text-[12px]" style={{ color: C.light }}>未上传</span>}
                    </div>
                  </div>
                </div>
                <div className="text-[11px] leading-relaxed" style={{ color: C.light }}>
                  {form.scene === "MED"
                    ? "医疗场景强制要求：营业执照 + 医疗机构执业许可证 两证齐全方可开户（上传后由平台人工复核）。"
                    : "早期接入选填；医疗机构（医疗场景）强制要求营业执照 + 医疗机构执业许可证两证必传。"}
                </div>
              </div>

              {/* ── ③ 套餐与增值 ── */}
              <div className="rounded-xl p-4 space-y-3" style={{ background: C.bg }}>
                <div className="text-[12px] font-semibold tracking-wider" style={{ color: C.primary }}>③ 套餐与增值服务</div>
                {(() => {
                  const sel = plans.find((p) => p.planName === form.plan);
                  if (!sel) return null;
                  return (
                    <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: "#fff", color: C.mid, border: `1px solid ${C.border}` }}>
                      <span className="font-medium" style={{ color: C.ink }}>{sel.name}：</span>
                      {sel.desc || "—"}
                      <div className="mt-1" style={{ color: C.light }}>订阅期 12 个月，到期后可在「计量计费」页续费或变更套餐。</div>
                    </div>
                  );
                })()}
                {/* 2026-08-22 老黄拍板：3D 岐黄三境不做单独加购/开关，严格按套餐门槛——
                    体验版/标准版标灰不可操作，专业版/企业版自动亮起（后端 onboard 同步强制，前端不设开关） */}
                {(() => {
                  const sel = plans.find((p) => p.planName === form.plan);
                  const planHas3d = !!sel?.features?.module_3d;
                  return (
                    <div
                      className="flex items-center justify-between rounded-lg p-3 transition-colors"
                      style={
                        planHas3d
                          ? { background: "#FBF4E4", border: "1px solid #EDD9A8", opacity: 1 }
                          : { background: "#F5F5F4", border: "1px solid #E7E5E4", opacity: 0.75 }
                      }
                    >
                      <div className="flex items-center gap-2">
                        <Boxes className="w-4 h-4" style={{ color: planHas3d ? C.gold : "#A8A29E" }} />
                        <div>
                          <div className="font-medium" style={{ color: planHas3d ? C.gold : "#78716C" }}>
                            岐黄三境 · 3D 增值模块
                          </div>
                          <div className="text-[11px]" style={{ color: planHas3d ? C.mid : "#A8A29E" }}>
                            {planHas3d
                              ? `当前套餐（${sel?.name || form.plan}）已含 · 开户后自动开通，穴位范围/皮肤/文案可配置`
                              : `当前套餐（${sel?.name || form.plan}）不含 3D 模块 · 升级专业版/企业版自动开通`}
                          </div>
                        </div>
                      </div>
                      {planHas3d ? (
                        <Badge variant="outline" className="border-amber-300 text-[11px] font-medium whitespace-nowrap" style={{ color: C.gold, background: "#fff" }}>
                          <CheckCircle2 className="w-3 h-3 mr-1" />已含 · 自动开通
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-[11px] font-medium whitespace-nowrap" style={{ color: "#78716C", borderColor: "#E7E5E4", background: "#FAFAF9" }}>
                          <Lock className="w-3 h-3 mr-1" />不含 · 不可操作
                        </Badge>
                      )}
                    </div>
                  );
                })()}
              </div>

              {/* ── ④ 联系人 ── */}
              <div className="rounded-xl p-4 space-y-3" style={{ background: C.soft }}>
                <div className="text-[12px] font-semibold tracking-wider" style={{ color: C.primary }}>④ 联系人信息</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label>联系人姓名<span style={{ color: "#B03A2E" }}> *</span></Label>
                    <Input value={form.contactName} onChange={(e) => setForm({ ...form, contactName: e.target.value })} placeholder="商务对接人" />
                  </div>
                  <div className="space-y-1.5">
                    <Label>联系电话<span style={{ color: "#B03A2E" }}> *</span></Label>
                    <Input value={form.contactPhone} onChange={(e) => setForm({ ...form, contactPhone: e.target.value })} placeholder="手机 11 位 / 座机须带区号" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label>电子邮箱</Label>
                    <Input value={form.contactEmail} onChange={(e) => setForm({ ...form, contactEmail: e.target.value })} placeholder="用于接收账单与通知" />
                  </div>
                </div>
                <div className="text-[11px]" style={{ color: C.light }}>座机示例：021-12345678（须带区号）· 国际：+86-021-12345678</div>
              </div>

              <div className="text-[12px] rounded-lg p-3" style={{ background: C.bg, color: C.mid }}>
                开户流程：创建租户 → 按所选套餐开通订阅（即时生效）→ 初始化根机构 → 记录机构资质与联系人 → 全程审计留痕。
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
              <Button style={{ background: C.primary }} onClick={create} disabled={submitting}>
                {submitting && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}确认开户
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[13px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 正在加载真实租户数据…
        </div>
      )}

      {/* 租户表（横向滚动：表格最小宽度 1180px，容器窄时自动横向滚动，不挤压内容） */}
      <Card className="border" style={{ borderColor: C.border }}>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]" style={{ minWidth: 1180 }}>
              <thead>
                <tr className="border-b" style={{ borderColor: C.border, background: C.soft }}>
                  <th className="px-5 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 280 }}>租户</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 96 }}>场景</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 108 }}>套餐</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 116 }}>机构 / 用户</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 220 }}>月调用量 / 配额</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 96 }}>3D 模块</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 92 }}>状态</th>
                  <th className="px-3 py-3 text-left text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 116 }}>到期时间</th>
                  <th className="px-4 py-3 text-right text-[12px] font-semibold whitespace-nowrap" style={{ color: C.mid, letterSpacing: "0.04em", minWidth: 168 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => {
                  const hasQuota = t.quotaCalls > 0;
                  const pct = hasQuota ? Math.min(100, Math.round((t.usedCalls / t.quotaCalls) * 100)) : 0;
                  const over = hasQuota && pct >= 95;
                  return (
                    <tr key={t.id} className="border-b last:border-0 hover:bg-[#F8FAF9] transition-colors" style={{ borderColor: C.border }}>
                      <td className="px-5 py-3.5 align-middle">
                        <div className="font-medium whitespace-nowrap truncate" style={{ color: C.ink, maxWidth: 260 }} title={t.name}>{t.name}</div>
                        <div className="text-[11px] font-mono truncate" style={{ color: C.light, maxWidth: 260 }} title={`${t.name} · ${t.id}`}>{t.code || t.id}</div>
                      </td>
                      <td className="px-3 py-3.5 align-middle">
                        <span className="inline-block px-2.5 py-1 rounded text-[11px] font-medium whitespace-nowrap" style={{ color: sceneMap[t.scene].color, background: sceneMap[t.scene].bg }}>
                          {sceneMap[t.scene].label}
                        </span>
                      </td>
                      <td className="px-3 py-3.5 align-middle whitespace-nowrap" style={{ color: C.mid }}>
                        {t.plan}
                        {(t as any).pendingPlan && (t as any).pendingEffectiveDate && (
                          <span
                            className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium"
                            style={{ background: "#FBF4E4", color: "#8A6A1F", border: "1px solid #EDD9A8" }}
                            title={`将于 ${(t as any).pendingEffectiveDate} 升级到 ${(t as any).pendingPlan}`}
                          >
                            <Clock className="w-3 h-3" />
                            {(t as any).pendingEffectiveDate} → {(t as any).pendingPlan}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3.5 align-middle whitespace-nowrap" style={{ color: C.mid }}>{t.orgs} / {t.users.toLocaleString()}</td>
                      <td className="px-3 py-3.5 align-middle">
                        <div className="flex justify-between text-[11px] mb-1 whitespace-nowrap" style={{ color: over ? "#B03A2E" : C.light }}>
                          <span>{t.usedCalls.toLocaleString()} / {hasQuota ? t.quotaCalls.toLocaleString() : "不限"}</span>
                          <span>{hasQuota ? `${pct}%` : "—"}</span>
                        </div>
                        <Progress value={pct} className="h-1.5" />
                      </td>
                      <td className="px-3 py-3.5 align-middle whitespace-nowrap">
                        {t.module3d
                          ? <Badge variant="outline" className="border-amber-300 text-[11px] font-medium" style={{ color: C.gold }}>已开通</Badge>
                          : <span className="text-[12px]" style={{ color: C.light }}>—</span>}
                      </td>
                      <td className="px-3 py-3.5 align-middle whitespace-nowrap">
                        <span className={`inline-block px-2.5 py-1 rounded border text-[11px] font-medium ${statusMap[t.status].cls}`}>{statusMap[t.status].label}</span>
                      </td>
                      <td className="px-3 py-3.5 align-middle whitespace-nowrap text-[12px]" style={{ color: C.mid }}>{t.expires}</td>
                      <td className="px-4 py-3.5 align-middle text-right">
                        <div className="inline-flex items-center gap-1">
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-[12px] hover:bg-[#EAF2EE]" style={{ color: C.primary }} onClick={() => setDetail(t)}>详情</Button>
                          <span className="w-px h-3" style={{ background: C.border }} />
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-[12px] hover:bg-gray-100" style={{ color: C.mid }} onClick={() => go("billing")}>续费</Button>
                          <span className="w-px h-3" style={{ background: C.border }} />
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-[12px] hover:bg-red-50" style={{ color: "#B03A2E" }} onClick={() => setDelTenant(t)}>删除</Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <div className="text-[12px]" style={{ color: C.light }}>共 {shown.length} 家租户 · 数据权限按 tenant_id 行级隔离</div>

      {/* 删除确认 */}
      <Dialog open={!!delTenant} onOpenChange={(o) => !o && setDelTenant(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle style={{ color: "#B03A2E" }}>删除租户</DialogTitle>
            <DialogDescription className="text-xs">
              将软删除 <b>{delTenant?.name}</b>（{delTenant?.id}），操作不可撤销，相关机构与用户将一并进入停用态。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setDelTenant(null)}>取消</Button>
            <Button size="sm" className="text-white" style={{ background: "#B03A2E" }}
              disabled={deleting} onClick={doDelete}>
              {deleting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
