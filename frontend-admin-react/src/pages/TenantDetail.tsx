import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { ArrowLeft, Plus, Boxes, KeyRound, RotateCcw, Ban, Sparkles } from "lucide-react";
import {
  C, sceneMap, statusMap, getOrgs, getUsers, userStatusMap,
  tenantTrend, endpointUsage, featureFlags, bills, billStatus,
} from "@/lib/mock";
import type { Tenant } from "@/lib/mock";

export default function TenantDetail({ tenant, onBack }: { tenant: Tenant; onBack: () => void }) {
  const t = tenant;
  const pct = Math.min(100, Math.round((t.usedCalls / t.quotaCalls) * 100));
  const [flags, setFlags] = useState(() => featureFlags(t));
  const [users, setUsers] = useState(() => getUsers(t));
  const [orgs] = useState(() => getOrgs(t));
  const [userOpen, setUserOpen] = useState(false);
  const [orgOpen, setOrgOpen] = useState(false);
  const [nu, setNu] = useState({ name: "", phone: "", role: "健康顾问", org: "" });
  const [saved, setSaved] = useState("");

  const flash = (msg: string) => { setSaved(msg); setTimeout(() => setSaved(""), 2500); };

  const addUser = () => {
    if (!nu.name.trim()) return;
    setUsers([{ id: `U-9${Math.floor(Math.random() * 9000 + 1000)}`, name: nu.name, phone: nu.phone || "—", role: nu.role, org: nu.org || orgs[0]?.name || "总部", status: "ACTIVE", lastActive: "刚刚" }, ...users]);
    setUserOpen(false);
    setNu({ name: "", phone: "", role: "健康顾问", org: "" });
    flash("账号已开设，初始密码已短信发送");
  };

  const myBills = bills.filter((b) => t.name.includes(b.tenant.slice(0, 4)) || b.tenant.includes(t.name.slice(0, 4)));

  return (
    <div className="space-y-4">
      {/* 头部 */}
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={onBack} style={{ borderColor: C.border, color: C.primary }}>
          <ArrowLeft className="w-4 h-4 mr-1" /> 返回列表
        </Button>
        <h2 className="text-[17px] font-semibold">{t.name}</h2>
        <span className="px-2 py-0.5 rounded text-[11px]" style={{ color: sceneMap[t.scene].color, background: sceneMap[t.scene].bg }}>
          {sceneMap[t.scene].label}场景
        </span>
        <span className={`px-2 py-0.5 rounded border text-[11px] ${statusMap[t.status].cls}`}>{statusMap[t.status].label}</span>
        {t.module3d && (
          <Badge variant="outline" className="border-amber-300 text-[11px]" style={{ color: C.gold }}>
            <Sparkles className="w-3 h-3 mr-1" /> 岐黄三境 3D
          </Badge>
        )}
        <div className="flex-1" />
        {saved && <span className="text-[12px] px-3 py-1.5 rounded-md" style={{ background: C.soft, color: C.primary }}>{saved}</span>}
      </div>

      {/* 概要条 */}
      <div className="grid grid-cols-5 gap-3 text-[13px]">
        {[
          { l: "租户 ID", v: t.id },
          { l: "套餐", v: `${t.plan} · 到期 ${t.expires}` },
          { l: "机构 / 用户", v: `${t.orgs} / ${t.users.toLocaleString()}` },
          { l: "本月调用", v: `${(t.usedCalls / 10000).toFixed(1)} 万次（${pct}%）` },
          { l: "数据隔离", v: "tenant_id 行级" },
        ].map((x) => (
          <Card key={x.l} className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-3">
              <div className="text-[11px]" style={{ color: C.light }}>{x.l}</div>
              <div className="mt-1 font-medium text-[12.5px]">{x.v}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">用量概览</TabsTrigger>
          <TabsTrigger value="orgs">机构管理</TabsTrigger>
          <TabsTrigger value="users">用户账号</TabsTrigger>
          <TabsTrigger value="features">功能开关</TabsTrigger>
          <TabsTrigger value="bills">账单记录</TabsTrigger>
        </TabsList>

        {/* ============ 用量概览 ============ */}
        <TabsContent value="overview" className="mt-4 space-y-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-2">近 30 天调用趋势</div>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={tenantTrend(t)} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: C.light }} tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Area dataKey="calls" name="调用量" stroke={C.primary} fill={C.primary} fillOpacity={0.2} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">端点级用量 TOP5</div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[11px]" style={{ color: C.light }}>
                    {["端点", "功能", "调用量", "平均耗时", "错误率"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {endpointUsage.map((e) => (
                    <tr key={e.endpoint} className="border-t" style={{ borderColor: C.border }}>
                      <td className="py-2.5 font-mono text-[12px]">{e.endpoint}</td>
                      <td className="py-2.5">{e.name}</td>
                      <td className="py-2.5">{e.calls.toLocaleString()}</td>
                      <td className="py-2.5">{e.avg}</td>
                      <td className="py-2.5" style={{ color: parseFloat(e.err) > 0.1 ? "#B03A2E" : C.mid }}>{e.err}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 机构管理 ============ */}
        <TabsContent value="orgs" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[14px] font-medium">下级机构（{t.orgs} 家，展示前 {orgs.length} 家）</span>
                <Dialog open={orgOpen} onOpenChange={setOrgOpen}>
                  <DialogTrigger asChild>
                    <Button size="sm" style={{ background: C.primary }}><Plus className="w-3.5 h-3.5 mr-1" /> 新增机构</Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-[400px]">
                    <DialogHeader><DialogTitle style={{ color: C.primary }}>新增机构</DialogTitle></DialogHeader>
                    <div className="space-y-3 py-2 text-[13px]">
                      <div className="space-y-1.5"><Label>机构名称</Label><Input placeholder="如：某某分馆 / 某某班级" /></div>
                      <div className="space-y-1.5">
                        <Label>机构类型</Label>
                        <Select defaultValue={t.scene === "EDU" ? "教学班级" : t.scene === "MED" ? "中医门诊" : "康养门店"}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {(t.scene === "EDU" ? ["教学班级", "教研组"] : t.scene === "MED" ? ["中医门诊", "住院部", "药房"] : ["康养门店", "线上渠道", "体验中心"]).map((x) => (
                              <SelectItem key={x} value={x}>{x}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setOrgOpen(false)}>取消</Button>
                      <Button style={{ background: C.primary }} onClick={() => { setOrgOpen(false); flash("机构已创建，可为其开设账号"); }}>创建</Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[11px]" style={{ color: C.light }}>
                    {["机构 ID", "名称", "类型", "用户数", "状态", "操作"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {orgs.map((o) => (
                    <tr key={o.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="py-2.5 font-mono text-[12px]">{o.id}</td>
                      <td className="py-2.5 font-medium">{o.name}</td>
                      <td className="py-2.5" style={{ color: C.mid }}>{o.type}</td>
                      <td className="py-2.5">{o.users}</td>
                      <td className="py-2.5"><Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200">正常</Badge></td>
                      <td className="py-2.5">
                        <button className="text-[12px] mr-3" style={{ color: C.primary }}>编辑</button>
                        <button className="text-[12px]" style={{ color: C.light }}>停用</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 用户账号 ============ */}
        <TabsContent value="users" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[14px] font-medium">用户账号（共 {t.users.toLocaleString()} 个，展示前 {users.length} 个）</span>
                <Dialog open={userOpen} onOpenChange={setUserOpen}>
                  <DialogTrigger asChild>
                    <Button size="sm" style={{ background: C.primary }}><Plus className="w-3.5 h-3.5 mr-1" /> 开设账号</Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-[420px]">
                    <DialogHeader><DialogTitle style={{ color: C.primary }}>开设用户账号</DialogTitle></DialogHeader>
                    <div className="space-y-3 py-2 text-[13px]">
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5"><Label>姓名</Label><Input value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} /></div>
                        <div className="space-y-1.5"><Label>手机号（登录账号）</Label><Input value={nu.phone} onChange={(e) => setNu({ ...nu, phone: e.target.value })} placeholder="138****" /></div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <Label>角色（受场景上限约束）</Label>
                          <Select value={nu.role} onValueChange={(v) => setNu({ ...nu, role: v })}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {(t.scene === "MED" ? ["执业医师", "科室主任", "机构管理员"]
                                : t.scene === "EDU" ? ["教师", "学员", "教研专家"]
                                : ["健康顾问", "C端用户", "机构管理员"]).map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1.5">
                          <Label>所属机构</Label>
                          <Select value={nu.org} onValueChange={(v) => setNu({ ...nu, org: v })}>
                            <SelectTrigger><SelectValue placeholder="选择机构" /></SelectTrigger>
                            <SelectContent>{orgs.map((o) => <SelectItem key={o.id} value={o.name}>{o.name}</SelectItem>)}</SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="text-[12px] rounded-lg p-3" style={{ background: C.bg, color: C.mid }}>
                        初始密码通过短信下发，首次登录强制改密；账号创建写入审计日志（tenant.user.create）。
                      </div>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setUserOpen(false)}>取消</Button>
                      <Button style={{ background: C.primary }} onClick={addUser}>开设</Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </div>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[11px]" style={{ color: C.light }}>
                    {["用户", "手机号", "角色", "机构", "最近活跃", "状态", "操作"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                      <td className="py-2.5">
                        <div className="font-medium">{u.name}</div>
                        <div className="text-[11px] font-mono" style={{ color: C.light }}>{u.id}</div>
                      </td>
                      <td className="py-2.5" style={{ color: C.mid }}>{u.phone}</td>
                      <td className="py-2.5">{u.role}</td>
                      <td className="py-2.5" style={{ color: C.mid }}>{u.org}</td>
                      <td className="py-2.5" style={{ color: C.light }}>{u.lastActive}</td>
                      <td className="py-2.5"><Badge variant="outline" className={userStatusMap[u.status].cls}>{userStatusMap[u.status].label}</Badge></td>
                      <td className="py-2.5">
                        <button className="text-[12px] mr-3 inline-flex items-center gap-0.5" style={{ color: C.primary }}>
                          <RotateCcw className="w-3 h-3" /> 重置密码
                        </button>
                        <button
                          className="text-[12px] inline-flex items-center gap-0.5"
                          style={{ color: u.status === "ACTIVE" ? "#B03A2E" : C.primary }}
                          onClick={() => setUsers(users.map((x) => x.id === u.id ? { ...x, status: x.status === "ACTIVE" ? "DISABLED" : "ACTIVE" } : x))}
                        >
                          <Ban className="w-3 h-3" /> {u.status === "ACTIVE" ? "禁用" : "启用"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 功能开关 ============ */}
        <TabsContent value="features" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[14px] font-medium">features_json 功能开关</span>
                <Button size="sm" style={{ background: C.primary }} onClick={() => flash("开关已下发，网关鉴权响应即时生效")}>保存并下发</Button>
              </div>
              <div className="text-[12px] mb-3" style={{ color: C.light }}>开关随 Token / 签名响应下发至租户前端，按开关渲染入口；增值项单独计量。</div>
              <div className="space-y-2">
                {flags.map((f) => (
                  <div key={f.key} className="flex items-center justify-between rounded-lg border p-3.5" style={{ borderColor: C.border, background: f.addon ? "#FDF9F0" : "#fff" }}>
                    <div className="flex items-center gap-3">
                      {f.addon && <Boxes className="w-4 h-4" style={{ color: C.accent }} />}
                      <div>
                        <div className="text-[13px] font-medium flex items-center gap-2">
                          {f.name}
                          <span className="font-mono text-[11px]" style={{ color: C.light }}>{f.key}</span>
                          {f.addon && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "#FBF4E4", color: C.gold }}>增值·单独计费</span>}
                        </div>
                        <div className="text-[12px]" style={{ color: C.mid }}>{f.desc}</div>
                      </div>
                    </div>
                    {f.locked
                      ? <span className="text-[12px]" style={{ color: C.light }}>当前套餐不可用</span>
                      : <Switch checked={f.on} onCheckedChange={(v) => setFlags(flags.map((x) => x.key === f.key ? { ...x, on: v } : x))} />}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ============ 账单记录 ============ */}
        <TabsContent value="bills" className="mt-4">
          <Card className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[14px] font-medium mb-3">历史账单</div>
              {myBills.length === 0 ? (
                <div className="py-10 text-center text-[13px]" style={{ color: C.light }}>该租户暂无出账记录（体验版或新建租户在首个账期末出账）</div>
              ) : (
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="text-left text-[11px]" style={{ color: C.light }}>
                      {["账单号", "账期", "调用量", "Token", "金额", "状态"].map((h) => <th key={h} className="pb-2 font-normal">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {myBills.map((b) => (
                      <tr key={b.id} className="border-t" style={{ borderColor: C.border }}>
                        <td className="py-2.5 font-mono text-[12px]">{b.id}</td>
                        <td className="py-2.5">{b.period}</td>
                        <td className="py-2.5">{b.calls}</td>
                        <td className="py-2.5">{b.tokens}</td>
                        <td className="py-2.5 font-medium">¥{b.amount.toLocaleString()}</td>
                        <td className="py-2.5"><Badge variant="outline" className={billStatus[b.status].cls}>{billStatus[b.status].label}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="mt-3 flex items-center gap-1.5 text-[11.5px]" style={{ color: C.light }}>
                <KeyRound className="w-3.5 h-3.5" /> 续费与套餐变更在「计量计费」页操作；逾期 7 天自动只读降级。
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
