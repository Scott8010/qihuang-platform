import { useState, useEffect, useMemo, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Users as UsersIcon, Search, Plus, Loader2, Trash2, KeyRound,
  Pencil, ShieldCheck, Power, Copy, Check,
} from "lucide-react";
import { toast } from "sonner";
import { C, userStatusMap } from "@/lib/types";
import {
  fetchUsers, fetchRoles, createUser, updateUser, deleteUser,
  resetUserPassword, assignRole, revokeRole,
} from "@/lib/api";
import type { PlatformUser, RoleTpl } from "@/lib/types";

const EMPTY_NEW = { username: '', password: '', display_name: '', phone: '', email: '' };

function validatePassword(pwd: string): string | null {
  if (!pwd) return '密码不能为空';
  if (pwd.length < 8 || pwd.length > 64) return '密码长度需为 8-64 位';
  if (!/[a-z]/.test(pwd)) return '密码须包含小写字母';
  if (!/[A-Z]/.test(pwd)) return '密码须包含大写字母';
  if (!/\d/.test(pwd)) return '密码须包含数字';
  const SPECIAL = '!@#$%^&*()_+-=[]{}|;:,.<>?/`~';
  if (![...pwd].some(c => SPECIAL.includes(c))) return '密码须包含特殊字符（如 !@#$%^&*）';
  return null;
}

export default function Users() {
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [roles, setRoles] = useState<RoleTpl[]>([]);
  const [loading, setLoading] = useState(true);
  const [kw, setKw] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "disabled">("all");

  // 新建
  const [createOpen, setCreateOpen] = useState(false);
  const [nu, setNu] = useState({ ...EMPTY_NEW });
  const [creating, setCreating] = useState(false);

  // 编辑
  const [editUser, setEditUser] = useState<PlatformUser | null>(null);
  const [ef, setEf] = useState({ display_name: "", phone: "", email: "" });
  const [savingEdit, setSavingEdit] = useState(false);

  // 角色分配
  const [roleUser, setRoleUser] = useState<PlatformUser | null>(null);
  const [roleBusy, setRoleBusy] = useState("");

  // 重置密码
  const [pwdUser, setPwdUser] = useState<PlatformUser | null>(null);
  const [pwdInput, setPwdInput] = useState("");
  const [pwdResult, setPwdResult] = useState("");
  const [pwdBusy, setPwdBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  // 删除
  const [delUser, setDelUser] = useState<PlatformUser | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 行级忙碌（启停）
  const [rowBusy, setRowBusy] = useState("");

  const load = useCallback(async () => {
    const [us, rs] = await Promise.all([fetchUsers(), fetchRoles()]);
    setUsers(us);
    setRoles(rs);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const k = kw.trim().toLowerCase();
    return users.filter((u) => {
      if (statusFilter !== "all" && (u.status || "active") !== statusFilter) return false;
      if (!k) return true;
      return [u.username, u.displayName, u.phone, u.email]
        .some((v) => (v || "").toLowerCase().includes(k));
    });
  }, [users, kw, statusFilter]);

  const stat = useMemo(() => ({
    total: users.length,
    active: users.filter((u) => (u.status || "active") === "active").length,
    disabled: users.filter((u) => u.status === "disabled").length,
    noRole: users.filter((u) => !u.roles || u.roles.length === 0).length,
  }), [users]);

  // ── 新建 ──
  async function doCreate() {
    if (!/^[a-zA-Z][a-zA-Z0-9_]{2,31}$/.test(nu.username)) {
      toast.error("用户名需 3-32 位，字母开头，仅含字母数字下划线");
      return;
    }
    const perr = validatePassword(nu.password);
    if (perr) {
      toast.error(perr);
      return;
    }
    setCreating(true);
    const r = await createUser({
      username: nu.username.trim(),
      password: nu.password,
      display_name: nu.display_name.trim() || undefined,
      phone: nu.phone.trim() || undefined,
      email: nu.email.trim() || undefined,
    });
    setCreating(false);
    if (r.ok) {
      toast.success(`用户 ${nu.username} 已创建，默认角色：健康用户`);
      setCreateOpen(false);
      setNu({ ...EMPTY_NEW });
      load();
    } else {
      toast.error(r.msg || "创建失败");
    }
  }

  // ── 编辑 ──
  function openEdit(u: PlatformUser) {
    setEditUser(u);
    setEf({ display_name: u.displayName || "", phone: u.phone || "", email: u.email || "" });
  }
  async function doEdit() {
    if (!editUser) return;
    setSavingEdit(true);
    const r = await updateUser(editUser.id, {
      display_name: ef.display_name.trim(),
      phone: ef.phone.trim(),
      email: ef.email.trim(),
    });
    setSavingEdit(false);
    if (r.ok) {
      toast.success("资料已更新");
      setEditUser(null);
      load();
    } else {
      toast.error(r.msg || "更新失败");
    }
  }

  // ── 启停 ──
  async function toggleStatus(u: PlatformUser) {
    const next = (u.status || "active") === "active" ? "disabled" : "active";
    setRowBusy(u.id);
    const r = await updateUser(u.id, { status: next });
    setRowBusy("");
    if (r.ok) {
      toast.success(next === "active" ? `已启用 ${u.username}` : `已停用 ${u.username}`);
      load();
    } else {
      toast.error(r.msg || "操作失败");
    }
  }

  // ── 角色分配 ──
  async function toggleRole(u: PlatformUser, roleName: string, had: boolean) {
    setRoleBusy(roleName);
    const r = had ? await revokeRole(u.id, roleName) : await assignRole(u.id, roleName);
    setRoleBusy("");
    if (r.ok) {
      toast.success(had ? `已移除 ${roleName}` : `已授予 ${roleName}`);
      const us = await fetchUsers();
      setUsers(us);
      setRoleUser(us.find((x) => x.id === u.id) || null);
    } else {
      toast.error(r.msg || "操作失败");
    }
  }

  // ── 重置密码 ──
  async function doResetPwd() {
    if (!pwdUser) return;
    if (pwdInput) {
      const perr = validatePassword(pwdInput);
      if (perr) {
        toast.error(perr);
        return;
      }
    }
    setPwdBusy(true);
    const r = await resetUserPassword(pwdUser.id, pwdInput || undefined);
    setPwdBusy(false);
    if (r.ok) {
      setPwdResult(r.data?.new_password || pwdInput || "");
      toast.success("密码已重置");
    } else {
      toast.error(r.msg || "重置失败");
    }
  }

  // ── 删除 ──
  async function doDelete() {
    if (!delUser) return;
    setDeleting(true);
    const r = await deleteUser(delUser.id);
    setDeleting(false);
    if (r.ok) {
      toast.success(`已删除用户 ${delUser.username}`);
      setDelUser(null);
      load();
    } else {
      toast.error(r.msg || "删除失败");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-sm" style={{ color: C.mid }}>
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />正在加载用户数据…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 概览 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { k: "平台用户总数", v: stat.total, c: C.primary },
          { k: "正常", v: stat.active, c: "#2E7D5B" },
          { k: "已停用", v: stat.disabled, c: "#8A6A1F" },
          { k: "未分配角色", v: stat.noRole, c: stat.noRole > 0 ? "#B03A2E" : C.mid },
        ].map((s) => (
          <Card key={s.k} style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-xs" style={{ color: C.mid }}>{s.k}</div>
              <div className="text-2xl font-semibold mt-1" style={{ color: s.c }}>{s.v}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card style={{ borderColor: C.border }}>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base flex items-center gap-2" style={{ color: C.ink }}>
              <UsersIcon className="w-4 h-4" style={{ color: C.primary }} />
              用户管理
            </CardTitle>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
                <Input
                  value={kw}
                  onChange={(e) => setKw(e.target.value)}
                  placeholder="搜索用户名 / 姓名 / 手机 / 邮箱"
                  className="pl-8 h-8 w-64 text-sm"
                />
              </div>
              <div className="flex rounded-md overflow-hidden border" style={{ borderColor: C.border }}>
                {([["all", "全部"], ["active", "正常"], ["disabled", "停用"]] as const).map(([v, t]) => (
                  <button
                    key={v}
                    onClick={() => setStatusFilter(v)}
                    className="px-2.5 py-1 text-xs transition-colors"
                    style={{
                      background: statusFilter === v ? C.primary : "#fff",
                      color: statusFilter === v ? "#fff" : C.mid,
                    }}
                  >{t}</button>
                ))}
              </div>
              <Button
                size="sm" className="h-8 text-white"
                style={{ background: C.primary }}
                onClick={() => setCreateOpen(true)}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />新建用户
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {filtered.length === 0 ? (
            <div className="py-16 text-center text-sm" style={{ color: C.light }}>
              {users.length === 0
                ? "平台暂无用户记录"
                : "没有符合筛选条件的用户"}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ background: C.bg, color: C.mid }}>
                    {["用户名", "姓名", "联系方式", "角色", "状态", "创建时间", "操作"].map((h) => (
                      <th key={h} className="text-left font-medium px-4 py-2.5 whitespace-nowrap text-xs">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => {
                    const st = userStatusMap[u.status || "active"] || userStatusMap.active;
                    return (
                      <tr key={u.id} className="border-t hover:bg-gray-50/60" style={{ borderColor: C.border }}>
                        <td className="px-4 py-2.5 font-medium whitespace-nowrap" style={{ color: C.ink }}>
                          {u.username || <span style={{ color: "#B03A2E" }}>(用户名缺失)</span>}
                        </td>
                        <td className="px-4 py-2.5 whitespace-nowrap" style={{ color: C.mid }}>
                          {u.displayName || <span style={{ color: C.light }}>—</span>}
                        </td>
                        <td className="px-4 py-2.5 text-xs" style={{ color: C.mid }}>
                          {u.phone || u.email
                            ? <>{u.phone}{u.phone && u.email ? " · " : ""}{u.email}</>
                            : <span style={{ color: C.light }}>—</span>}
                        </td>
                        <td className="px-4 py-2.5">
                          {u.roles && u.roles.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {u.roles.map((r) => (
                                <Badge key={r.id} variant="outline" className="text-[11px] font-normal"
                                  style={{ borderColor: C.border, color: C.primary, background: C.soft }}>
                                  {r.displayName || r.name}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs" style={{ color: "#B03A2E" }}>未分配</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge variant="outline" className={`text-[11px] font-normal ${st.cls}`}>{st.label}</Badge>
                        </td>
                        <td className="px-4 py-2.5 text-xs whitespace-nowrap" style={{ color: C.light }}>
                          {u.createdAt ? u.createdAt.slice(0, 10) : "—"}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-1">
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                              onClick={() => openEdit(u)} title="编辑资料">
                              <Pencil className="w-3.5 h-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                              onClick={() => setRoleUser(u)} title="角色分配">
                              <ShieldCheck className="w-3.5 h-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                              onClick={() => { setPwdUser(u); setPwdInput(""); setPwdResult(""); setCopied(false); }}
                              title="重置密码">
                              <KeyRound className="w-3.5 h-3.5" />
                            </Button>
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                              disabled={rowBusy === u.id}
                              onClick={() => toggleStatus(u)}
                              title={(u.status || "active") === "active" ? "停用" : "启用"}>
                              {rowBusy === u.id
                                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                : <Power className="w-3.5 h-3.5"
                                    style={{ color: (u.status || "active") === "active" ? "#8A6A1F" : "#2E7D5B" }} />}
                            </Button>
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
                              onClick={() => setDelUser(u)} title="删除用户">
                              <Trash2 className="w-3.5 h-3.5" style={{ color: "#B03A2E" }} />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 新建用户 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle style={{ color: C.ink }}>新建用户</DialogTitle>
            <DialogDescription className="text-xs">
              创建后系统自动授予「健康用户」默认角色，可在角色分配中调整。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {([
              ["username", "用户名 *", "字母开头，3-32 位"],
              ["password", "初始密码 *", "至少 8 位"],
              ["display_name", "姓名", "选填"],
              ["phone", "手机号", "选填"],
              ["email", "邮箱", "选填"],
            ] as const).map(([k, label, ph]) => (
              <div key={k}>
                <div className="text-xs mb-1" style={{ color: C.mid }}>{label}</div>
                <Input
                  type={k === "password" ? "password" : "text"}
                  value={(nu as any)[k]}
                  placeholder={ph}
                  onChange={(e) => setNu({ ...nu, [k]: e.target.value })}
                  className="h-8 text-sm"
                />
                {k === 'password' && (
                  <div className='text-[11px] mt-1.5 leading-relaxed' style={{ color: C.light }}>
                    需 8-64 位，且必须同时包含大小写字母、数字及特殊字符（如 !@#$%^&*）；留空由系统生成随机强密码。
                  </div>
                )}
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button size="sm" className="text-white" style={{ background: C.primary }}
              disabled={creating} onClick={doCreate}>
              {creating && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 编辑资料 */}
      <Dialog open={!!editUser} onOpenChange={(o) => !o && setEditUser(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle style={{ color: C.ink }}>编辑资料 · {editUser?.username}</DialogTitle>
            <DialogDescription className="text-xs">用户名不可修改，如需改密请使用重置密码。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {([["display_name", "姓名"], ["phone", "手机号"], ["email", "邮箱"]] as const).map(([k, label]) => (
              <div key={k}>
                <div className="text-xs mb-1" style={{ color: C.mid }}>{label}</div>
                <Input value={(ef as any)[k]} onChange={(e) => setEf({ ...ef, [k]: e.target.value })}
                  className="h-8 text-sm" />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditUser(null)}>取消</Button>
            <Button size="sm" className="text-white" style={{ background: C.primary }}
              disabled={savingEdit} onClick={doEdit}>
              {savingEdit && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 角色分配 */}
      <Dialog open={!!roleUser} onOpenChange={(o) => !o && setRoleUser(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle style={{ color: C.ink }}>角色分配 · {roleUser?.username}</DialogTitle>
            <DialogDescription className="text-xs">勾选即时生效，直接写入后端权限表。</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 max-h-80 overflow-y-auto">
            {roles.length === 0 ? (
              <div className="py-8 text-center text-sm" style={{ color: C.light }}>暂无可分配角色</div>
            ) : roles.map((r) => {
              const had = !!roleUser?.roles?.some((x) => x.name === r.code);
              const busy = roleBusy === r.code;
              return (
                <label key={r.id}
                  className="flex items-center gap-2.5 px-3 py-2 rounded-md border cursor-pointer hover:bg-gray-50"
                  style={{ borderColor: had ? C.primary : C.border, background: had ? C.soft : "#fff" }}>
                  {busy
                    ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: C.primary }} />
                    : <Checkbox checked={had} onCheckedChange={() => roleUser && toggleRole(roleUser, r.code, had)} />}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm" style={{ color: C.ink }}>{r.name}</div>
                    <div className="text-[11px]" style={{ color: C.light }}>
                      {r.code} · {r.permissions.length} 项权限
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setRoleUser(null)}>完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 重置密码 */}
      <Dialog open={!!pwdUser} onOpenChange={(o) => { if (!o) { setPwdUser(null); setPwdResult(""); } }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle style={{ color: C.ink }}>重置密码 · {pwdUser?.username}</DialogTitle>
            <DialogDescription className="text-xs">留空则由系统生成随机强密码，重置后仅显示一次。</DialogDescription>
          </DialogHeader>
          {pwdResult ? (
            <div className="rounded-md border p-3" style={{ borderColor: C.border, background: C.bg }}>
              <div className="text-xs mb-1.5" style={{ color: C.mid }}>新密码（请立即保存）</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-sm px-2 py-1.5 rounded bg-white border font-mono"
                  style={{ borderColor: C.border, color: C.ink }}>{pwdResult}</code>
                <Button size="sm" variant="outline" className="h-8"
                  onClick={() => {
                    navigator.clipboard?.writeText(pwdResult);
                    setCopied(true);
                    toast.success("已复制到剪贴板");
                  }}>
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <div className="text-xs mb-1" style={{ color: C.mid }}>新密码（选填）</div>
              <Input type="text" value={pwdInput} onChange={(e) => setPwdInput(e.target.value)}
                placeholder="留空自动生成" className="h-8 text-sm" />
              <div className="text-[11px] mt-1.5 leading-relaxed" style={{ color: pwdInput && validatePassword(pwdInput) ? "#B03A2E" : C.light }}>
                {!pwdInput
                  ? '留空则由系统生成随机强密码；自定义需 8-64 位，且必须同时含大小写字母、数字及特殊字符（如 !@#$%^&*）。'
                  : (validatePassword(pwdInput)
                      ? validatePassword(pwdInput)
                      : '✓ 密码强度符合要求（留空则由系统生成随机强密码）')}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => { setPwdUser(null); setPwdResult(""); }}>
              {pwdResult ? "关闭" : "取消"}
            </Button>
            {!pwdResult && (
              <Button size="sm" className="text-white" style={{ background: C.primary }}
                disabled={pwdBusy} onClick={doResetPwd}>
                {pwdBusy && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}确认重置
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={!!delUser} onOpenChange={(o) => !o && setDelUser(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle style={{ color: "#B03A2E" }}>删除用户</DialogTitle>
            <DialogDescription className="text-xs">
              将永久删除 <b>{delUser?.username}</b> 及其全部角色关联，操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setDelUser(null)}>取消</Button>
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
