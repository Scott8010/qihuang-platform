import { useState, useEffect, useMemo, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  ShieldCheck, Save, UserPlus, Search, Loader2, Plus, Trash2, RotateCcw, AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { C, permSceneMap, permGroupMap } from "@/lib/types";
import {
  fetchRoles, fetchPermissions, fetchUsers,
  updateRolePermissions, createRole, deleteRole, assignRole, revokeRole,
} from "@/lib/api";
import type { RoleTpl, PermissionItem, PlatformUser } from "@/lib/types";

/** 权限按 code 前缀分组：admin / core / health / edu / module */
function groupOf(code: string) {
  return code.split(":")[0] || "other";
}

export default function Roles() {
  const [roles, setRoles] = useState<RoleTpl[]>([]);
  const [perms, setPerms] = useState<PermissionItem[]>([]);
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [selId, setSelId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBusy, setAssignBusy] = useState("");
  const [kw, setKw] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [newRole, setNewRole] = useState({ name: "", display_name: "", description: "" });
  const [newPerms, setNewPerms] = useState<Set<string>>(new Set());
  const [delOpen, setDelOpen] = useState(false);

  const sel = useMemo(() => roles.find((r) => r.id === selId) || null, [roles, selId]);

  const loadAll = useCallback(async (keepId?: string) => {
    const [rs, ps, us] = await Promise.all([fetchRoles(), fetchPermissions(), fetchUsers()]);
    setRoles(rs);
    setPerms(ps);
    setUsers(us);
    const target = (keepId && rs.find((r) => r.id === keepId)) || rs[0] || null;
    if (target) {
      setSelId(target.id);
      setChecked(new Set(target.permissions.map((p) => p.code)));
    } else {
      setSelId("");
      setChecked(new Set());
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const pickRole = (r: RoleTpl) => {
    setSelId(r.id);
    setChecked(new Set(r.permissions.map((p) => p.code)));
  };

  const toggle = (code: string) => {
    const s = new Set(checked);
    if (s.has(code)) s.delete(code); else s.add(code);
    setChecked(s);
  };

  // 当前勾选 vs 后端已存，判断是否有未保存改动
  const dirty = useMemo(() => {
    if (!sel) return false;
    const orig = new Set(sel.permissions.map((p) => p.code));
    if (orig.size !== checked.size) return true;
    for (const c of checked) if (!orig.has(c)) return true;
    return false;
  }, [sel, checked]);

  const resetChecked = () => {
    if (sel) setChecked(new Set(sel.permissions.map((p) => p.code)));
  };

  const saveTpl = async () => {
    if (!sel) return;
    setSaving(true);
    const res = await updateRolePermissions(sel.id, Array.from(checked));
    setSaving(false);
    if (res.ok) {
      toast.success(`「${sel.name}」权限已保存`, {
        description: `当前授予 ${res.data?.perm_count ?? checked.size} 项权限，变更已写入审计日志`,
      });
      await loadAll(sel.id);
    } else {
      toast.error("保存失败", { description: res.msg });
    }
  };

  const doCreateRole = async () => {
    const name = newRole.name.trim();
    if (!name) { toast.error("角色标识不能为空"); return; }
    if (!/^[a-z][a-z0-9_]*$/.test(name)) {
      toast.error("角色标识格式不合法", { description: "只能用小写字母、数字和下划线，且以字母开头" });
      return;
    }
    setSaving(true);
    const res = await createRole({
      name,
      display_name: newRole.display_name.trim() || name,
      description: newRole.description.trim(),
      perm_codes: Array.from(newPerms),
    });
    setSaving(false);
    if (res.ok) {
      toast.success(`角色「${newRole.display_name.trim() || name}」已创建`);
      setCreateOpen(false);
      setNewRole({ name: "", display_name: "", description: "" });
      setNewPerms(new Set());
      await loadAll(res.data?.id);
    } else {
      toast.error("创建失败", { description: res.msg });
    }
  };

  const doDeleteRole = async () => {
    if (!sel) return;
    setSaving(true);
    const res = await deleteRole(sel.id);
    setSaving(false);
    setDelOpen(false);
    if (res.ok) {
      toast.success(`角色「${sel.name}」已删除`);
      await loadAll();
    } else {
      toast.error("删除失败", { description: res.msg });
    }
  };

  const toggleUserRole = async (u: PlatformUser, has: boolean) => {
    if (!sel) return;
    setAssignBusy(u.id);
    const res = has ? await revokeRole(u.id, sel.code) : await assignRole(u.id, sel.code);
    setAssignBusy("");
    if (res.ok) {
      toast.success(has ? `已移除 ${u.displayName} 的「${sel.name}」` : `已为 ${u.displayName} 分配「${sel.name}」`);
      await loadAll(sel.id);
    } else {
      toast.error("操作失败", { description: res.msg });
    }
  };

  // 全量权限池按分组
  const grouped = useMemo(() => {
    const m: Record<string, PermissionItem[]> = {};
    perms.forEach((p) => { (m[groupOf(p.code)] ||= []).push(p); });
    return Object.entries(m).sort((a, b) => {
      const order = ["admin", "core", "health", "edu", "module"];
      return order.indexOf(a[0]) - order.indexOf(b[0]);
    });
  }, [perms]);

  const shownUsers = users.filter((u) =>
    !kw || u.username.includes(kw) || u.displayName.includes(kw) || (u.phone || "").includes(kw));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-[13px]" style={{ color: C.light }}>
        <Loader2 className="w-5 h-5 mr-2 animate-spin" /> 加载中…
      </div>
    );
  }

  const PermGrid = ({
    value, onToggle,
  }: { value: Set<string>; onToggle: (c: string) => void }) => (
    <div className="space-y-4">
      {grouped.map(([g, list]) => (
        <div key={g}>
          <div className="text-[12px] font-medium mb-2 flex items-center gap-2" style={{ color: C.mid }}>
            {permGroupMap[g] || g}
            <span className="text-[11px] font-normal" style={{ color: C.light }}>
              {list.filter((p) => value.has(p.code)).length}/{list.length}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {list.map((p) => {
              const on = value.has(p.code);
              const sc = permSceneMap[p.scene] || permSceneMap.all;
              return (
                <button
                  key={p.code}
                  onClick={() => onToggle(p.code)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full border text-[12px] transition-colors"
                  style={{
                    borderColor: on ? C.primary : C.border,
                    background: on ? C.soft : "#fff",
                    color: on ? C.primary : C.mid,
                  }}
                >
                  <Checkbox checked={on} className="pointer-events-none w-3.5 h-3.5" />
                  <span>{p.name}</span>
                  <span className="font-mono text-[10px]" style={{ color: C.light }}>{p.code}</span>
                  {p.scene !== "all" && (
                    <span className="text-[10px] px-1.5 rounded"
                      style={{ background: sc.bg, color: sc.color }}>{sc.label}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4 items-start">
      {/* ── 左：角色列表 ── */}
      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-[15px]" style={{ color: C.primary }}>
              角色 <span className="text-[12px] font-normal" style={{ color: C.light }}>{roles.length} 个</span>
            </CardTitle>
            <Button size="sm" variant="outline" style={{ borderColor: C.border, color: C.primary }}
              onClick={() => setCreateOpen(true)}>
              <Plus className="w-3.5 h-3.5 mr-1" /> 新建
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-2 space-y-1">
          {roles.length === 0 && (
            <div className="px-3 py-6 text-center text-[12px]" style={{ color: C.light }}>暂无角色数据</div>
          )}
          {roles.map((r) => {
            const active = r.id === selId;
            const empty = r.permissions.length === 0;
            return (
              <button
                key={r.id}
                onClick={() => pickRole(r)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors"
                style={{ background: active ? C.soft : "transparent" }}
              >
                <ShieldCheck className="w-4 h-4 shrink-0" style={{ color: active ? C.primary : C.light }} />
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium truncate" style={{ color: active ? C.primary : C.ink }}>
                    {r.name}
                  </div>
                  <div className="text-[11px] font-mono truncate" style={{ color: C.light }}>
                    {r.code} · {r.permissions.length} 权限 · {r.users} 人
                  </div>
                </div>
                {empty && <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-500" />}
                {!r.is_system && (
                  <Badge variant="outline" className="text-[10px] shrink-0"
                    style={{ color: C.accent, borderColor: C.accent }}>自定义</Badge>
                )}
              </button>
            );
          })}
        </CardContent>
      </Card>

      {/* ── 右：权限编辑 ── */}
      {sel && (
        <Card className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <CardTitle className="text-[15px]" style={{ color: C.primary }}>
                  {sel.name} <span className="font-mono text-[12px] font-normal" style={{ color: C.light }}>{sel.code}</span>
                </CardTitle>
                <div className="text-[12px] mt-1" style={{ color: C.mid }}>
                  {sel.description || "暂无描述"} · 覆盖用户 {sel.users.toLocaleString()} 人 ·{" "}
                  {sel.is_system ? "系统预置角色（不可删除）" : "自定义角色"}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {dirty && (
                  <span className="text-[12px] px-2 py-1 rounded-md" style={{ background: "#FBF4E4", color: C.gold }}>
                    有未保存改动
                  </span>
                )}
                {dirty && (
                  <Button variant="ghost" size="sm" style={{ color: C.light }} onClick={resetChecked}>
                    <RotateCcw className="w-4 h-4 mr-1" /> 还原
                  </Button>
                )}
                <Button variant="outline" size="sm" style={{ borderColor: C.border, color: C.primary }}
                  onClick={() => { setKw(""); setAssignOpen(true); }}>
                  <UserPlus className="w-4 h-4 mr-1" /> 分配用户
                </Button>
                {!sel.is_system && (
                  <Button variant="outline" size="sm" className="text-red-600"
                    style={{ borderColor: "#F0D0CC" }} onClick={() => setDelOpen(true)}>
                    <Trash2 className="w-4 h-4 mr-1" /> 删除
                  </Button>
                )}
                <Button style={{ background: C.primary }} size="sm" disabled={!dirty || saving} onClick={saveTpl}>
                  {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                  保存权限
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center gap-2 text-[13px] font-medium" style={{ color: C.primary }}>
              权限清单
              <span className="text-[11px] font-normal" style={{ color: C.light }}>
                已勾选 {checked.size} / 全部 {perms.length} 项 —— 勾选结果即最终授权，保存后整体替换
              </span>
            </div>
            <PermGrid value={checked} onToggle={toggle} />
            <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: C.bg, color: C.mid }}>
              保存即整体替换该角色的权限集合（勾掉的会被收回）。super_admin 在后端硬编码为全权限放行，
              即使这里未勾选也拥有全部能力。权限变更全程写入审计日志（操作人、对象、前后值）。
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── 分配用户 ── */}
      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle style={{ color: C.primary }}>为「{sel?.name}」分配用户</DialogTitle>
            <DialogDescription className="text-[12px]">
              点击即时生效：未持有则授予，已持有则移除。
            </DialogDescription>
          </DialogHeader>
          <div className="py-2 space-y-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
              <Input value={kw} onChange={(e) => setKw(e.target.value)}
                placeholder="搜索账号 / 姓名 / 手机号" className="pl-9 text-[13px]" style={{ borderColor: C.border }} />
            </div>
            <div className="max-h-72 overflow-y-auto space-y-1">
              {shownUsers.length === 0 && (
                <div className="py-8 text-center text-[12px]" style={{ color: C.light }}>
                  {users.length === 0 ? "系统内暂无用户，请先到「用户管理」新建" : "没有匹配的用户"}
                </div>
              )}
              {shownUsers.map((u) => {
                const has = u.roles.some((r) => r.name === sel?.code);
                const busy = assignBusy === u.id;
                return (
                  <button
                    key={u.id}
                    disabled={busy}
                    onClick={() => toggleUserRole(u, has)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors"
                    style={{ borderColor: has ? C.primary : C.border, background: has ? C.soft : "#fff" }}
                  >
                    {busy
                      ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: C.primary }} />
                      : <Checkbox checked={has} className="pointer-events-none" />}
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium truncate">
                        {u.displayName}
                        <span className="font-mono text-[11px] font-normal ml-2" style={{ color: C.light }}>{u.username}</span>
                      </div>
                      <div className="text-[11px] truncate" style={{ color: C.light }}>
                        {u.roles.length ? u.roles.map((r) => r.displayName).join(" / ") : "未分配角色"}
                      </div>
                    </div>
                    <span className="text-[11px] shrink-0" style={{ color: has ? C.primary : C.light }}>
                      {has ? "点击移除" : "点击授予"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 新建角色 ── */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[640px]">
          <DialogHeader>
            <DialogTitle style={{ color: C.primary }}>新建自定义角色</DialogTitle>
            <DialogDescription className="text-[12px]">
              自定义角色可随时修改权限或删除；系统预置的 9 个角色不可删除。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[12px] mb-1" style={{ color: C.mid }}>角色标识 *</div>
                <Input value={newRole.name} placeholder="如 clinic_manager"
                  onChange={(e) => setNewRole({ ...newRole, name: e.target.value })}
                  className="text-[13px] font-mono" style={{ borderColor: C.border }} />
                <div className="text-[11px] mt-1" style={{ color: C.light }}>小写字母 / 数字 / 下划线</div>
              </div>
              <div>
                <div className="text-[12px] mb-1" style={{ color: C.mid }}>中文名称</div>
                <Input value={newRole.display_name} placeholder="如 门店经理"
                  onChange={(e) => setNewRole({ ...newRole, display_name: e.target.value })}
                  className="text-[13px]" style={{ borderColor: C.border }} />
              </div>
            </div>
            <div>
              <div className="text-[12px] mb-1" style={{ color: C.mid }}>职责说明</div>
              <Textarea value={newRole.description} rows={2} placeholder="这个角色负责什么"
                onChange={(e) => setNewRole({ ...newRole, description: e.target.value })}
                className="text-[13px]" style={{ borderColor: C.border }} />
            </div>
            <div>
              <div className="text-[12px] mb-2" style={{ color: C.mid }}>
                初始权限（已选 {newPerms.size} 项，创建后仍可调整）
              </div>
              <div className="max-h-56 overflow-y-auto pr-1">
                <PermGrid value={newPerms} onToggle={(c) => {
                  const s = new Set(newPerms);
                  if (s.has(c)) s.delete(c); else s.add(c);
                  setNewPerms(s);
                }} />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button style={{ background: C.primary }} disabled={saving} onClick={doCreateRole}>
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}创建角色
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 删除确认 ── */}
      <Dialog open={delOpen} onOpenChange={setDelOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="text-red-600">删除角色「{sel?.name}」</DialogTitle>
            <DialogDescription className="text-[13px]">
              该角色下的 {sel?.users ?? 0} 名用户将失去这份授权，角色与权限绑定会一并清除。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDelOpen(false)}>取消</Button>
            <Button className="bg-red-600 hover:bg-red-700" disabled={saving} onClick={doDeleteRole}>
              {saving && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
