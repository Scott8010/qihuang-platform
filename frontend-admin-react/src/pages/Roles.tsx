import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { ShieldCheck, Save, UserPlus, Search, CheckCircle2, Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import { fetchRoles } from "@/lib/api";
import type { RoleTpl } from "@/lib/types";

const assignable = [
  { id: "U-90001", name: "林晚晴", org: "颐森汇·静安旗舰馆", current: "健康顾问" },
  { id: "U-90003", name: "苏念", org: "颐森汇·线上商城", current: "C端用户" },
  { id: "U-91001", name: "沈知微", org: "云杉中医馆·徐汇总院", current: "执业医师" },
  { id: "U-91004", name: "钱望舒", org: "云杉中医馆·虹桥分院", current: "未分配" },
  { id: "U-92001", name: "孟扶摇", org: "杏林在线·执业医师班", current: "未分配" },
];

export default function Roles() {
  const [roles, setRoles] = useState<RoleTpl[]>([]);
  const [sel, setSel] = useState<RoleTpl | null>(null);
  const [loading, setLoading] = useState(true);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [kw, setKw] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchRoles().then((data) => {
      setRoles(data);
      if (data.length) {
        setSel(data[0]);
        setChecked(new Set(data[0].permissions.map((p) => p.code)));
      }
      setLoading(false);
    });
  }, []);

  const saveTpl = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const togglePick = (id: string) => {
    const s = new Set(picked);
    if (s.has(id)) { s.delete(id); } else { s.add(id); }
    setPicked(s);
  };

  const doAssign = () => {
    setAssignOpen(false);
    setPicked(new Set());
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const shownUsers = assignable.filter((u) => !kw || u.name.includes(kw) || u.org.includes(kw));

  const toggle = (item: string) => {
    const s = new Set(checked);
    if (s.has(item)) {
      s.delete(item);
    } else {
      s.add(item);
    }
    setChecked(s);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-[13px]" style={{ color: C.light }}>
        <Loader2 className="w-5 h-5 mr-2 animate-spin" /> 加载中…
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4 items-start">
      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[15px]" style={{ color: C.primary }}>角色模板（按场景）</CardTitle>
        </CardHeader>
        <CardContent className="p-2 space-y-1">
          {roles.length === 0 && (
            <div className="px-3 py-6 text-center text-[12px]" style={{ color: C.light }}>暂无角色数据</div>
          )}
          {roles.map((r) => (
            <button
              key={r.id || r.code}
              onClick={() => { setSel(r); setChecked(new Set(r.permissions.map((p) => p.code))); }}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors"
              style={{ background: sel?.code === r.code ? C.soft : "transparent" }}
            >
              <ShieldCheck className="w-4 h-4 shrink-0" style={{ color: sel?.code === r.code ? C.primary : C.light }} />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium truncate" style={{ color: sel?.code === r.code ? C.primary : C.ink }}>{r.name}</div>
                <div className="text-[11px] font-mono" style={{ color: C.light }}>{r.code}</div>
              </div>
              {r.is_system && <Badge variant="outline" className="text-[10px]" style={{ color: C.light }}>系统</Badge>}
            </button>
          ))}
        </CardContent>
      </Card>

      {sel && (
        <Card className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-[15px]" style={{ color: C.primary }}>
                  {sel.name} <span className="font-mono text-[12px] font-normal" style={{ color: C.light }}>{sel.code}</span>
                </CardTitle>
                <div className="text-[12px] mt-1" style={{ color: C.mid }}>
                  {sel.description || "—"} · 覆盖用户 {sel.users.toLocaleString()} 人 {sel.is_system ? "· 系统角色" : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {saved && (
                  <span className="text-[12px] px-2.5 py-1 rounded-md inline-flex items-center gap-1" style={{ background: C.soft, color: C.primary }}>
                    <CheckCircle2 className="w-3.5 h-3.5" /> 已保存并下发，变更已写入审计日志
                  </span>
                )}
                <Button variant="outline" size="sm" style={{ borderColor: C.border, color: C.primary }} onClick={() => setAssignOpen(true)}>
                  <UserPlus className="w-4 h-4 mr-1" /> 分配用户
                </Button>
                <Button style={{ background: C.primary }} size="sm" onClick={saveTpl}>
                  <Save className="w-4 h-4 mr-1" /> 保存模板
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <div className="text-[13px] font-medium mb-2 flex items-center gap-2" style={{ color: C.primary }}>
                已授权权限 <span className="text-[11px] font-normal" style={{ color: C.light }}>{sel.permissions.length} 项</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {sel.permissions.length === 0 && (
                  <span className="text-[12px]" style={{ color: C.light }}>该角色暂未配置权限</span>
                )}
                {sel.permissions.map((p) => {
                  const on = checked.has(p.code);
                  return (
                    <button
                      key={p.code}
                      onClick={() => toggle(p.code)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[12px] transition-colors"
                      style={{
                        borderColor: on ? C.primary : C.border,
                        background: on ? C.soft : "#fff",
                        color: on ? C.primary : C.mid,
                      }}
                    >
                      <Checkbox checked={on} className="pointer-events-none w-3.5 h-3.5" />
                      <span className="font-mono">{p.code}</span>
                      <span className="text-[11px]" style={{ color: C.light }}>{p.name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: C.bg, color: C.mid }}>
              硬性规则：场景越权不可配置（大健康角色无法被授予 med:rx:review）；权限变更全程记录审计日志（操作人、对象、前后值）。
              当前已授予 {sel.permissions.length} 项权限。
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle style={{ color: C.primary }}>为「{sel?.name}」分配用户</DialogTitle>
          </DialogHeader>
          <div className="py-2 space-y-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
              <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索姓名 / 机构" className="pl-9 text-[13px]" style={{ borderColor: C.border }} />
            </div>
            <div className="max-h-64 overflow-y-auto space-y-1">
              {shownUsers.map((u) => {
                const on = picked.has(u.id);
                const disabled = u.current === sel?.name;
                return (
                  <button
                    key={u.id}
                    disabled={disabled}
                    onClick={() => togglePick(u.id)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors"
                    style={{
                      borderColor: on ? C.primary : C.border,
                      background: disabled ? C.bg : on ? C.soft : "#fff",
                      opacity: disabled ? 0.55 : 1,
                    }}
                  >
                    <Checkbox checked={on || disabled} className="pointer-events-none" />
                    <div className="flex-1">
                      <div className="text-[13px] font-medium">{u.name} <span className="font-mono text-[11px] font-normal" style={{ color: C.light }}>{u.id}</span></div>
                      <div className="text-[11px]" style={{ color: C.light }}>{u.org}</div>
                    </div>
                    <span className="text-[11px]" style={{ color: disabled ? C.primary : C.light }}>
                      {disabled ? "已是该角色" : u.current}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="text-[12px]" style={{ color: C.light }}>
              已选 {picked.size} 人 · 分配即时生效并记录审计日志（role.assign）
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignOpen(false)}>取消</Button>
            <Button style={{ background: C.primary }} disabled={picked.size === 0} onClick={doAssign}>
              确认分配（{picked.size}）
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
