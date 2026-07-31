import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { ShieldCheck, Save, UserPlus, Search, CheckCircle2 } from "lucide-react";
import { C, roleTpls, sceneMap } from "@/lib/mock";

const assignable = [
  { id: "U-90001", name: "林晚晴", org: "颐森汇·静安旗舰馆", current: "健康顾问" },
  { id: "U-90003", name: "苏念", org: "颐森汇·线上商城", current: "C端用户" },
  { id: "U-91001", name: "沈知微", org: "云杉中医馆·徐汇总院", current: "执业医师" },
  { id: "U-91004", name: "钱望舒", org: "云杉中医馆·虹桥分院", current: "未分配" },
  { id: "U-92001", name: "孟扶摇", org: "杏林在线·执业医师班", current: "未分配" },
];

const permGroups = [
  { title: "菜单权限", type: "MENU", items: ["辅助辨证", "处方审查", "医案管理", "报告中心", "体质辨识", "调理方案", "健康档案", "穴位指导（3D）", "经典学习", "AI陪练", "题库管理", "学情看板", "账号管理", "用量报表"] },
  { title: "API 权限", type: "API", items: ["med:diagnose", "med:rx:review", "med:case:write", "med:report", "health:assess", "health:plan", "health:tongue", "health:archive", "edu:classic", "edu:coach", "edu:exam:write", "kg:review"] },
  { title: "数据权限范围", type: "DATA", items: ["仅本人 SELF", "本机构 ORG", "本租户 TENANT"] },
];

export default function Roles() {
  const [sel, setSel] = useState(roleTpls[4]);
  const [checked, setChecked] = useState<Set<string>>(new Set(["体质辨识", "调理方案", "健康档案", "穴位指导（3D）", "health:assess", "health:plan", "health:archive", "仅本人 SELF"]));
  const [assignOpen, setAssignOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [kw, setKw] = useState("");
  const [saved, setSaved] = useState(false);

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

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4 items-start">
      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[15px]" style={{ color: C.primary }}>角色模板（按场景）</CardTitle>
        </CardHeader>
        <CardContent className="p-2 space-y-1">
          {roleTpls.map((r) => (
            <button
              key={r.code}
              onClick={() => setSel(r)}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors"
              style={{ background: sel.code === r.code ? C.soft : "transparent" }}
            >
              <ShieldCheck className="w-4 h-4 shrink-0" style={{ color: sel.code === r.code ? C.primary : C.light }} />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium truncate" style={{ color: sel.code === r.code ? C.primary : C.ink }}>{r.name}</div>
                <div className="text-[11px] font-mono" style={{ color: C.light }}>{r.code}</div>
              </div>
              {r.scene !== "平台" && (
                <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ color: sceneMap[r.scene].color, background: sceneMap[r.scene].bg }}>
                  {sceneMap[r.scene].label}
                </span>
              )}
            </button>
          ))}
        </CardContent>
      </Card>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-[15px]" style={{ color: C.primary }}>
                {sel.name} <span className="font-mono text-[12px] font-normal" style={{ color: C.light }}>{sel.code}</span>
              </CardTitle>
              <div className="text-[12px] mt-1" style={{ color: C.mid }}>
                数据范围：{sel.scope} · 覆盖用户 {sel.users.toLocaleString()} 人 · 系统模板（租户可微调，不可越场景上限）
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
          {permGroups.map((g) => (
            <div key={g.type}>
              <div className="text-[13px] font-medium mb-2 flex items-center gap-2" style={{ color: C.primary }}>
                {g.title}
                <span className="text-[11px] font-normal" style={{ color: C.light }}>{g.type}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {g.items.map((item) => {
                  const on = checked.has(item);
                  const is3d = item.includes("3D") || item.includes("module");
                  return (
                    <button
                      key={item}
                      onClick={() => toggle(item)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[12px] transition-colors"
                      style={{
                        borderColor: on ? C.primary : C.border,
                        background: on ? C.soft : "#fff",
                        color: on ? C.primary : C.mid,
                      }}
                    >
                      <Checkbox checked={on} className="pointer-events-none w-3.5 h-3.5" />
                      {item}
                      {is3d && <Badge variant="outline" className="text-[10px] px-1 py-0 border-amber-300" style={{ color: C.gold }}>增值</Badge>}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="rounded-lg p-3 text-[12px] leading-relaxed" style={{ background: C.bg, color: C.mid }}>
            硬性规则：场景越权不可配置（大健康角色无法被授予 med:rx:review）；权限变更全程记录审计日志（操作人、对象、前后值）。
            当前已授予 API：{sel.apis.join("、")}
          </div>
        </CardContent>
      </Card>

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle style={{ color: C.primary }}>为「{sel.name}」分配用户</DialogTitle>
          </DialogHeader>
          <div className="py-2 space-y-3">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
              <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索姓名 / 机构" className="pl-9 text-[13px]" style={{ borderColor: C.border }} />
            </div>
            <div className="max-h-64 overflow-y-auto space-y-1">
              {shownUsers.map((u) => {
                const on = picked.has(u.id);
                const disabled = u.current === sel.name;
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
