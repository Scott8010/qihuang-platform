import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Plus, Search, Boxes, Loader2, Clock } from "lucide-react";
import { C, sceneMap, statusMap } from "@/lib/types";
import { fetchTenants, createTenant, deleteTenant } from "@/lib/api";
import { toast } from "sonner";
import type { Tenant } from "@/lib/types";
import TenantDetail from "./TenantDetail";

const tabs = [
  { id: "ALL", label: "全部租户" },
  { id: "MED", label: "医疗" },
  { id: "HEALTH", label: "大健康" },
  { id: "EDU", label: "培训" },
];

export default function Tenants() {
  const [list, setList] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("ALL");
  const [kw, setKw] = useState("");
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Tenant | null>(null);
  const [form, setForm] = useState({ name: "", scene: "HEALTH", plan: "标准版", contact: "", m3d: false });

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
    (t) => (tab === "ALL" || t.scene === tab) && (!kw || t.name.includes(kw) || t.id.includes(kw))
  );

  const create = async () => {
    if (!form.name.trim()) return;
    await createTenant({
      name: form.name,
      scene: form.scene,
      plan: form.plan,
      contact: form.contact,
      module3d: form.m3d,
    });
    setOpen(false);
    setForm({ name: "", scene: "HEALTH", plan: "标准版", contact: "", m3d: false });
    await load();
  };

  if (detail) return <TenantDetail tenant={detail} onBack={() => setDetail(null)} />;

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
          <DialogContent className="sm:max-w-[460px]">
            <DialogHeader>
              <DialogTitle style={{ color: C.primary }}>新建租户开户</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2 text-[13px]">
              <div className="space-y-1.5">
                <Label>租户名称（合同主体）</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如：某某中医馆连锁有限公司" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>场景类型（创建后不可变更）</Label>
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
                  <Label>套餐</Label>
                  <Select value={form.plan} onValueChange={(v) => setForm({ ...form, plan: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {["体验版", "标准版", "专业版", "企业版"].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>商务联系人</Label>
                <Input value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="姓名 / 电话" />
              </div>
              <div className="flex items-center justify-between rounded-lg p-3" style={{ background: "#FBF4E4" }}>
                <div className="flex items-center gap-2">
                  <Boxes className="w-4 h-4" style={{ color: C.gold }} />
                  <div>
                    <div className="font-medium" style={{ color: C.gold }}>岐黄三境 · 3D 增值模块</div>
                    <div className="text-[11px]" style={{ color: C.mid }}>module_3d 开关 · 穴位范围/皮肤/文案可配置</div>
                  </div>
                </div>
                <Switch checked={form.m3d} onCheckedChange={(v) => setForm({ ...form, m3d: v })} />
              </div>
              <div className="text-[12px] rounded-lg p-3" style={{ background: C.bg, color: C.mid }}>
                开户流程：创建租户 → 初始化机构与角色模板 → 签发租户管理员账号与 API Key → 启用。全程将记录审计日志。
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
              <Button style={{ background: C.primary }} onClick={create}>确认开户</Button>
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
                        <div className="text-[11px] font-mono truncate" style={{ color: C.light, maxWidth: 260 }} title={t.id}>{t.id}</div>
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
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-[12px] hover:bg-gray-100" style={{ color: C.mid }}>续费</Button>
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
