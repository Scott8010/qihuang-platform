import { useState, useEffect, useRef } from "react";
import {
  LayoutDashboard, Building2, ShieldCheck, KeyRound, BarChart3,
  BookOpenCheck, Activity, Search, Bell, Sprout, ChevronDown, LogOut,
  Users as UsersIcon, Eye, EyeOff, Lock, Bot, CreditCard, Boxes,
  ChevronRight, ChevronLeft, Home, FileText, HelpCircle, Ticket, ScrollText,
  Gauge, Headset,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { C } from "@/lib/types";
import { login, logout, getToken, changePassword, getIdentity, fetchMyTickets, fetchMyBillingOverview } from "@/lib/api";
import type { BillingOverview } from "@/lib/api";
import Dashboard from "@/pages/Dashboard";
import Tenants from "@/pages/Tenants";
import Roles from "@/pages/Roles";
import Users from "@/pages/Users";
import ApiKeys from "@/pages/ApiKeys";
import Billing from "@/pages/Billing";
import Content from "@/pages/Content";
import Monitor from "@/pages/Monitor";
import AgentCenter from "@/pages/AgentCenter";
import PlanUpgrade from "@/pages/PlanUpgrade";
import CapabilityCenter from "@/pages/CapabilityCenter";
import Ledger from "@/pages/Ledger";
import MyDashboard from "@/pages/MyDashboard";
import MyKeys from "@/pages/MyKeys";
import MyUsage from "@/pages/MyUsage";
import MyTickets from "@/pages/MyTickets";
import MyLogs from "@/pages/MyLogs";
import MyBilling from "@/pages/MyBilling";
import MyHelp from "@/pages/MyHelp";
import MyContact from "@/pages/MyContact";
import MyAgents from "@/pages/MyAgents";
import PlatformTickets from "@/pages/PlatformTickets";

type NavChild = { id: string; label: string; desc?: string };
type NavItem =
  | { id: string; label: string; icon: LucideIcon; desc?: string }
  | { id: string; label: string; icon: LucideIcon; children: NavChild[] };

/** 平台方（super_admin）全量菜单 */
const adminNav: NavItem[] = [
  { id: "dashboard", label: "运营总览", icon: LayoutDashboard },
  { id: "agents", label: "Agent 中台", icon: Bot },
  { id: "tenants", label: "租户管理", icon: Building2 },
  { id: "users", label: "用户管理", icon: UsersIcon },
  { id: "roles", label: "权限管理", icon: ShieldCheck },
  { id: "keys", label: "密钥配额", icon: KeyRound },
  {
    id: "billing-group",
    label: "结算中心",
    icon: BarChart3,
    children: [
      { id: "billing", label: "结算概览" },
      { id: "ledger", label: "用量核算", desc: "按 agent / 场景拆分" },
    ],
  },
  { id: "capability", label: "能力中心", icon: Boxes },
  { id: "content", label: "内容管控", icon: BookOpenCheck },
  { id: "tickets", label: "工单管理", icon: Ticket },
  { id: "monitor", label: "监控运维", icon: Activity },
  { id: "planupgrade", label: "套餐升级", icon: CreditCard },
];

/** 租户管理员（tenant_admin/org_admin）精简菜单：只看与自己相关的 */
const tenantNav: NavItem[] = [
  { id: "myhome", label: "数据汇总", icon: Home },
  { id: "mybilling", label: "账单与配额", icon: CreditCard },
  { id: "mykeys", label: "我的密钥", icon: KeyRound },
  { id: "myagents", label: "我的能力", icon: Bot },
  { id: "myusage", label: "使用情况", icon: FileText },
  { id: "mytickets", label: "工单中心", icon: Ticket },
  { id: "mylogs", label: "使用日志", icon: ScrollText },
  { id: "mysupport", label: "联系客服", icon: Headset },
  { id: "myhelp", label: "平台使用说明", icon: HelpCircle },
];

/** 机构端分组菜单（参考 tenant-portal 设计稿布局）：总览 / 资源 / 支持。
 *  仅用于侧边栏渲染分组；权限判定仍走扁平 tenantNav，避免破坏 go()/history 逻辑。 */
const tenantGroups: { title: string; items: { id: string; label: string; icon: LucideIcon; badge?: "tickets" }[] }[] = [
  { title: "总览", items: [{ id: "myhome", label: "数据汇总", icon: LayoutDashboard }] },
  { title: "资源", items: [
    { id: "mybilling", label: "账单与配额", icon: CreditCard },
    { id: "myusage", label: "使用情况", icon: Gauge },
    { id: "mykeys", label: "我的密钥", icon: KeyRound },
    { id: "myagents", label: "我的能力", icon: Bot },
    { id: "mylogs", label: "使用日志", icon: ScrollText },
  ] },
  { title: "支持", items: [
    { id: "mytickets", label: "工单中心", icon: Ticket, badge: "tickets" },
    { id: "mysupport", label: "联系客服", icon: Headset },
    { id: "myhelp", label: "平台使用说明", icon: HelpCircle },
  ] },
];

/** 机构端页面显示名（设计稿口径），与分组菜单保持一致 */
const tenantDisplayLabel: Record<string, string> = {
  myhome: "数据汇总", mybilling: "账单与配额", myusage: "使用情况", mykeys: "我的密钥",
  myagents: "我的能力",
  mylogs: "使用日志", mytickets: "工单中心",
  mysupport: "联系客服", myhelp: "平台使用说明",
};

/** 是否平台超管：只有 super_admin 看全量菜单，其余管理员看租户精简视图 */
function isPlatformAdmin(identity: { roles?: string[] } | null): boolean {
  return !!identity?.roles?.includes("super_admin");
}

/* ---- 浏览器历史接管：hash 路由 + 后退拦截 ----
 * 平台是纯 state 切页，URL 不变时浏览器历史只有一条 /admin/，
 * 用户一按后退就退到进平台之前的页面（看起来像"退出平台"）。
 * 这里给每个页面配 #/xxx hash 并写入历史，后退变成平台内翻页；
 * 退到平台外（hash 丢失）时在 popstate 里拦回，避免误退出。 */
const hashOf = (page: string) => `#/${page}`;
const pageFromLocation = () => {
  const h = window.location.hash || "";
  return h.startsWith("#/") ? h.slice(2) : "";
};
const idsOfNav = (nav: NavItem[]) =>
  nav.flatMap((n) => ("children" in n ? [n, ...n.children] : [n])).map((n) => n.id);

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState("dashboard");
  const [navDepth, setNavDepth] = useState(0);
  // 让事件回调拿到最新的菜单上下文（避免用过期闭包）
  const navRef = useRef({ allowed: [] as string[], defaultPage: "dashboard", page: "dashboard", authed: false });
  // 当前平台内历史序号（写入 history.state，前进/后退都能据此还原按钮状态）
  const histIdxRef = useRef(0);
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [showPass, setShowPass] = useState(false);
  // 机构端工单角标（未处理数）：仅机构管理员视图用，超管端不展示
  const [openTickets, setOpenTickets] = useState(0);
  // 机构端左侧底部套餐状态卡：真实账单总览（收窄接口，跨租户拿不到）
  const [billingOverview, setBillingOverview] = useState<BillingOverview | null>(null);
  const [billingLoaded, setBillingLoaded] = useState(false);

  // 修改密码弹窗状态
  const [menuOpen, setMenuOpen] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ "billing-group": true });
  const [showPwdModal, setShowPwdModal] = useState(false);
  const [cpOld, setCpOld] = useState("");
  const [cpNew, setCpNew] = useState("");
  const [cpConfirm, setCpConfirm] = useState("");
  const [cpShowNew, setCpShowNew] = useState(false);
  const [cpErr, setCpErr] = useState("");
  const [cpOk, setCpOk] = useState("");
  const [cpBusy, setCpBusy] = useState(false);

  useEffect(() => {
    const id = getIdentity();
    const allowed = idsOfNav(isPlatformAdmin(id) ? adminNav : tenantNav);
    const defaultPage = isPlatformAdmin(id) ? "dashboard" : "myhome";
    const hasToken = !!getToken();
    navRef.current = { allowed, defaultPage, page: defaultPage, authed: hasToken };

    if (hasToken) {
      setAuthed(true);
      // 从 hash 恢复上次所在页；非法/越权页兜底到默认页
      const fromHash = pageFromLocation();
      const target = allowed.includes(fromHash) ? fromHash : defaultPage;
      setPage(target);
      navRef.current.page = target;
      // 刷新时沿用历史里已有的序号（没有则回到 0），保证返回按钮状态正确
      const prevState = window.history.state as { qhIdx?: number } | null;
      const idx = prevState && typeof prevState.qhIdx === "number" ? prevState.qhIdx : 0;
      histIdxRef.current = idx;
      setNavDepth(idx);
      window.history.replaceState({ qhPage: target, qhIdx: idx }, "", hashOf(target));
      // （机构端私有数据改由下方 [authed] effect 统一拉取，登录后与刷新都覆盖）
    }
    setChecking(false);

    // 浏览器后退/前进：从 hash 解析目标页，合法则切页；退到平台外则拦回
    const onPop = (ev: PopStateEvent) => {
      if (!navRef.current.authed) return; // 登录页的后退交给浏览器默认行为
      const { allowed: allow, page: cur } = navRef.current;
      const fromHash = pageFromLocation();
      if (fromHash && allow.includes(fromHash)) {
        navRef.current.page = fromHash;
        setPage(fromHash);
        // 用 state 里的序号还原深度（前进后退都准），无 state 则按位移估算
        const st = ev.state as { qhIdx?: number } | null;
        if (st && typeof st.qhIdx === "number") {
          histIdxRef.current = st.qhIdx;
          setNavDepth(st.qhIdx);
        } else {
          histIdxRef.current = Math.max(0, histIdxRef.current - 1);
          setNavDepth(histIdxRef.current);
        }
      } else {
        // 后退把 hash 退没了（试图退出平台）→ 用 replace 拉回当前页，不产生新历史
        try {
          window.history.replaceState({ qhPage: cur, qhIdx: histIdxRef.current }, "", hashOf(cur));
        } catch {
          // 跨域历史条目不允许改 URL：忽略，浏览器会按默认行为处理
        }
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  /** 机构端私有数据：登录成功后与刷新恢复都拉一次（超管端不拉）。
   *  工单角标 + 左侧套餐状态卡都走 my/ 收窄接口，后端按 token 租户钉死，跨租户拿不到。 */
  useEffect(() => {
    if (!authed || isPlatformAdmin(getIdentity())) return;
    let alive = true;
    fetchMyTickets(undefined, 1, 100).then((r) => {
      if (alive) setOpenTickets(r.items.filter((t) => !["resolved", "closed"].includes(t.status)).length);
    }).catch(() => { /* 角标拉不到不影响主流程 */ });
    fetchMyBillingOverview().then((b) => {
      if (alive) setBillingOverview(b);
    }).catch(() => { /* 接口异常不造假，卡片走占位文案 */ }).finally(() => {
      if (alive) setBillingLoaded(true);
    });
    return () => { alive = false; };
  }, [authed]);

  /** 平台内跳页：写入历史 + 同步 state（所有菜单/按钮都走这里） */
  const go = (next: string) => {
    const { allowed, defaultPage } = navRef.current;
    const target = allowed.includes(next) ? next : defaultPage;
    const cur = navRef.current.page;
    if (target === cur) return; // 同页不重复入栈
    window.history.pushState({ qhPage: target, qhIdx: histIdxRef.current + 1 }, "", hashOf(target));
    histIdxRef.current += 1;
    navRef.current.page = target;
    setPage(target);
    setNavDepth(histIdxRef.current);
  };

  const doLogin = async () => {
    setLoginErr("");
    if (!loginUser.trim()) { setLoginErr("请输入管理员账号"); return; }
    if (!loginPass) { setLoginErr("请输入密码"); return; } // 密码必填：后端 password 为必填字段，不传会 422
    const ok = await login(loginUser, loginPass);
    if (ok) {
      const id = getIdentity();
      const allowed = idsOfNav(isPlatformAdmin(id) ? adminNav : tenantNav);
      const defaultPage = isPlatformAdmin(id) ? "dashboard" : "myhome";
      setAuthed(true);
      navRef.current = { allowed, defaultPage, page: defaultPage, authed: true };
      setPage(defaultPage);
      setNavDepth(0);
      histIdxRef.current = 0;
      // 登录成功：push 出平台第一页，把裸 /admin/ 留作"哨兵"历史。
      // 这样即使在平台首页按后退，也只是退到哨兵（hash 丢失）→ 被 onPop 拦回，不会退出平台。
      window.history.pushState({ qhPage: defaultPage, qhIdx: 0 }, "", hashOf(defaultPage));
    } else { setLoginErr("登录失败，请检查账号或密码"); }
  };

  const doLogout = () => {
    logout();
    setAuthed(false);
    setPage("dashboard");
    setNavDepth(0);
    setMenuOpen(false);
    navRef.current.authed = false;
    // 退出后清掉 hash，回到干净的登录页
    window.history.replaceState({}, "", window.location.pathname);
  };

  const onForgot = () => {
    // P1 手机+短信找回暂缓，当前仅支持管理员后台重置
    setLoginErr("暂未开通短信找回，请联系系统管理员为您重置密码");
  };

  const submitChangePwd = async () => {
    setCpErr(""); setCpOk("");
    if (!cpOld || !cpNew) { setCpErr("请填写原密码与新密码"); return; }
    if (cpNew.length < 8) { setCpErr("新密码至少 8 位"); return; }
    if (cpNew !== cpConfirm) { setCpErr("两次输入的新密码不一致"); return; }
    setCpBusy(true);
    const r = await changePassword(cpOld, cpNew);
    setCpBusy(false);
    if (r.ok) {
      setCpOk("密码修改成功，请使用新密码重新登录");
      setCpOld(""); setCpNew(""); setCpConfirm("");
      // 改密后当前 token 仍有效但建议重登，1.2s 后自动退出
      setTimeout(() => { setShowPwdModal(false); setMenuOpen(false); doLogout(); }, 1200);
    } else {
      setCpErr(r.msg || "修改失败，请重试");
    }
  };

  // 登录页
  if (checking) return <div className="flex h-screen items-center justify-center" style={{ background: C.bg }}><span style={{ color: C.light }}>加载中...</span></div>;
  if (!authed) {
    return (
      <div className="flex h-screen items-center justify-center" style={{ background: C.bg }}>
        <div className="bg-white rounded-2xl shadow-lg p-10 w-[400px]" style={{ border: `1px solid ${C.border}` }}>
          <div className="flex items-center gap-3 mb-8 justify-center">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: C.primary }}>
              <Sprout className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="font-bold text-[20px] tracking-wide" style={{ color: C.primary }}>岐黄智脑</div>
              <div className="text-[14px]" style={{ color: C.light }}>运营控制台 · V1.2</div>
            </div>
          </div>
          <div className="space-y-4">
            <input
              value={loginUser} onChange={(e) => setLoginUser(e.target.value)}
              placeholder="管理员账号" autoFocus
              onKeyDown={(e) => e.key === "Enter" && doLogin()}
              className="w-full px-4 py-3 rounded-lg border text-[16px] outline-none"
              style={{ borderColor: C.border }}
            />
            <div className="relative">
              <input
                type={showPass ? "text" : "password"} value={loginPass}
                onChange={(e) => setLoginPass(e.target.value)}
                placeholder="请输入密码"
                onKeyDown={(e) => e.key === "Enter" && doLogin()}
                className="w-full px-4 py-3 pr-11 rounded-lg border text-[16px] outline-none"
                style={{ borderColor: C.border }}
              />
              <button
                type="button" onClick={() => setShowPass((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-gray-50"
                aria-label={showPass ? "隐藏密码" : "显示密码"}
              >
                {showPass ? <EyeOff className="w-4 h-4" style={{ color: C.light }} /> : <Eye className="w-4 h-4" style={{ color: C.light }} />}
              </button>
            </div>
            <div className="flex justify-end -mt-1">
              <button type="button" onClick={onForgot} className="text-[14px] hover:underline" style={{ color: C.light }}>
                忘记密码？
              </button>
            </div>
            {loginErr && <div className="text-[15px] text-red-600">{loginErr}</div>}
            <button
              onClick={doLogin}
              className="w-full py-3 rounded-lg text-white font-medium text-[16px]"
              style={{ background: C.primary }}
            >登录控制台</button>
          </div>
        </div>
      </div>
    );
  }

  const identity = getIdentity();
  const platformAdmin = isPlatformAdmin(identity);
  // 一套平台两套菜单：超管全量，租户只看精简视图
  const nav = platformAdmin ? adminNav : tenantNav;
  const navIds = nav.flatMap((n) => ("children" in n ? [n, ...n.children] : [n])).map((n) => n.id);
  // 越权兜底：若当前页不在本角色菜单里（如手改 state/旧缓存），强制回默认页
  const defaultPage = platformAdmin ? "dashboard" : "myhome";
  const effectivePage = navIds.includes(page) ? page : defaultPage;
  const current = nav.flatMap((n) => ("children" in n ? [n, ...n.children] : [n])).find((n) => n.id === effectivePage) || nav[0];

  // 左侧底部套餐状态卡：全部来自 my/billing-overview 真值，取不到就走占位，绝不造假数
  const plan = billingOverview?.plan;
  const expireDays = (() => {
    if (!plan?.expires) return null;
    const end = new Date(plan.expires.includes("T") ? plan.expires : plan.expires + "T00:00:00").getTime();
    if (Number.isNaN(end)) return null;
    return Math.ceil((end - Date.now()) / 86400000);
  })();
  const quotaPct = plan && plan.quota_calls > 0
    ? Math.min(100, Math.round((plan.used_calls / plan.quota_calls) * 100)) : 0;
  const planName = plan?.name ? (plan.name.includes("套餐") ? plan.name : `${plan.name}套餐`) : "当前套餐";
  const expireBadge = expireDays === null ? null
    : expireDays < 0 ? { text: `已到期 ${Math.abs(expireDays)} 天`, bg: "#FDECEA", fg: "#B03A2E" }
    : expireDays === 0 ? { text: "今天到期", bg: "#FDECEA", fg: "#B03A2E" }
    : expireDays <= 30 ? { text: `${expireDays} 天后到期`, bg: "#FDECEA", fg: "#B03A2E" }
    : { text: `${expireDays} 天后到期`, bg: "#FBF0D9", fg: C.gold };

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: C.bg, color: C.ink }}>
      {/* 侧边栏 */}
      <aside className="w-[232px] shrink-0 bg-white border-r flex flex-col" style={{ borderColor: C.border }}>
        <div className="flex items-center gap-3 px-5 h-16 border-b" style={{ borderColor: C.border }}>
          <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: C.primary }}>
            <Sprout className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="font-bold text-[17px] tracking-wide" style={{ color: C.primary }}>岐黄智脑</div>
            <div className="text-[13px]" style={{ color: C.light }}>{platformAdmin ? "运营控制台 · V1.2" : "机构工作台 · V1.2"}</div>
          </div>
        </div>

        {/* 机构端：设计稿风格的分组菜单（总览/资源/支持）+ 工单角标 */}
        {!platformAdmin ? (
          <nav className="flex-1 px-3 py-4 space-y-6 overflow-y-auto">
            {tenantGroups.map((g) => (
              <div key={g.title}>
                <div className="px-2.5 mb-1.5 text-[12px] font-medium tracking-widest" style={{ color: C.light }}>{g.title}</div>
                <ul className="space-y-0.5">
                  {g.items.map((item) => {
                    const active = effectivePage === item.id;
                    const showBadge = item.badge === "tickets" && openTickets > 0;
                    return (
                      <li key={item.id}>
                        <button
                          onClick={() => go(item.id)}
                          className="w-full flex items-center gap-2.5 px-2.5 py-2.5 rounded-lg text-[15px] transition-colors"
                          style={{ background: active ? C.primary : "transparent", color: active ? "#fff" : C.mid, fontWeight: active ? 600 : 400 }}
                        >
                          <item.icon className="w-[18px] h-[18px] shrink-0" style={{ color: active ? "#fff" : C.light }} />
                          <span className="flex-1 text-left">{item.label}</span>
                          {showBadge && (
                            <span className="min-w-5 rounded-full px-1.5 py-0.5 text-center text-[11px] leading-none tabular"
                              style={{ background: active ? "rgba(255,255,255,0.2)" : "#B03A2E", color: "#fff" }}>
                              {openTickets}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        ) : (
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <div className="px-3 pt-2 pb-1 text-[13px] font-medium" style={{ color: C.light }}>运营管理</div>
          {nav.map((n) => {
            if ("children" in n) {
              const open = !!expanded[n.id];
              const childActive = n.children.some((c) => c.id === effectivePage);
              return (
                <div key={n.id} className="space-y-0.5">
                  <button
                    onClick={() => setExpanded((prev) => ({ ...prev, [n.id]: !prev[n.id] }))}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[16px] transition-colors"
                    style={{
                      background: childActive ? C.soft : "transparent",
                      color: childActive ? C.primary : C.mid,
                      fontWeight: childActive ? 600 : 400,
                    }}
                  >
                    <n.icon className="w-[18px] h-[18px]" style={{ color: childActive ? C.primary : C.light }} />
                    <span className="flex-1 text-left">{n.label}</span>
                    <ChevronRight
                      className="w-4 h-4 transition-transform"
                      style={{ color: C.light, transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
                    />
                  </button>
                  {open && (
                    <div className="pl-9 space-y-0.5">
                      {n.children.map((c) => {
                        const cActive = effectivePage === c.id;
                        return (
                          <button
                            key={c.id}
                            onClick={() => go(c.id)}
                            className="w-full text-left px-3 py-2 rounded-lg text-[15px] transition-colors"
                            style={{
                              background: cActive ? C.soft : "transparent",
                              color: cActive ? C.primary : C.mid,
                              fontWeight: cActive ? 600 : 400,
                            }}
                          >
                            <span className="block">{c.label}</span>
                            {c.desc && <span className="block text-[12px] font-normal leading-tight" style={{ color: C.light }}>{c.desc}</span>}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            }
            const active = effectivePage === n.id;
            return (
              <button
                key={n.id}
                onClick={() => go(n.id)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[16px] transition-colors"
                style={{
                  background: active ? C.soft : "transparent",
                  color: active ? C.primary : C.mid,
                  fontWeight: active ? 600 : 400,
                }}
              >
                <n.icon className="w-[18px] h-[18px]" style={{ color: active ? C.primary : C.light }} />
                <span className="flex-1 text-left">
                  <span className="block">{n.label}</span>
                  {n.desc && <span className="block text-[12px] font-normal leading-tight" style={{ color: C.light }}>{n.desc}</span>}
                </span>
              </button>
            );
          })}
        </nav>
        )}
        <div className="p-4 border-t" style={{ borderColor: C.border }}>
          {/* 机构端：底部套餐状态卡——套餐名 + 到期徽章 + 配额进度条，同源 my/billing-overview 真值 */}
          {!platformAdmin ? (
            <button
              onClick={() => go("mybilling")}
              className="w-full text-left rounded-xl p-3.5 mb-2 hover:opacity-90 transition-opacity"
              style={{ background: C.soft, border: `1px solid ${C.border}` }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] truncate" style={{ color: C.light }}>
                  {identity?.tenant_name || "我的机构"}
                </span>
                <span className="px-1.5 py-0.5 rounded text-[11px] shrink-0" style={{ background: "#fff", color: C.mid }}>机构版</span>
              </div>
              {billingLoaded && plan ? (
                <>
                  <div className="flex items-center justify-between gap-2 mt-2">
                    <span className="text-[15px] font-semibold truncate" style={{ color: C.primary }}>{planName}</span>
                    {expireBadge && (
                      <span className="px-2 py-0.5 rounded text-[11px] font-medium shrink-0"
                        style={{ background: expireBadge.bg, color: expireBadge.fg }}>
                        {expireBadge.text}
                      </span>
                    )}
                  </div>
                  <div className="mt-2.5 h-1.5 rounded-full overflow-hidden" style={{ background: "#D9E6DF" }}>
                    <div className="h-full rounded-full" style={{ width: `${quotaPct}%`, background: C.primary }} />
                  </div>
                  <p className="mt-2 text-[12px] leading-relaxed" style={{ color: C.mid }}>
                    已用资源配额 {quotaPct}%，续费或升级请联系客户经理
                  </p>
                </>
              ) : (
                <p className="mt-2 text-[12px] leading-relaxed" style={{ color: C.mid }}>
                  {billingLoaded ? "套餐信息暂不可用，点此查看配额明细。" : "套餐信息读取中..."}
                </p>
              )}
            </button>
          ) : null}
          <div className="flex items-center gap-2 mb-1 text-[14px]" style={{ color: C.light }}>
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
            <span style={{ color: C.mid }}>平台运行正常</span>
          </div>
          <button onClick={doLogout} className="flex items-center gap-1 mt-1 text-[14px]" style={{ color: C.light }}>
            <LogOut className="w-3 h-3" /> 退出登录
          </button>
        </div>
      </aside>

      {/* 主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white border-b flex items-center gap-4 px-6 shrink-0" style={{ borderColor: C.border }}>
          {/* 平台内返回：仅在有上级页面时显示，点了等同于浏览器后退但不会退出平台 */}
          {navDepth > 0 && (
            <button
              onClick={() => window.history.back()}
              title="返回上一页"
              className="flex items-center gap-1 px-2 py-1.5 rounded-lg hover:bg-gray-50 text-[14px]"
              style={{ color: C.mid }}
            >
              <ChevronLeft className="w-[18px] h-[18px]" style={{ color: C.primary }} /> 返回
            </button>
          )}
          {platformAdmin ? (
            <h1 className="text-[19px] font-semibold" style={{ color: C.primary }}>{current.label}</h1>
          ) : (
            <h1 className="text-[18px] font-semibold leading-tight" style={{ color: C.primary }}>{tenantDisplayLabel[effectivePage] || current.label}</h1>
          )}
          <div className="flex-1" />
          {!platformAdmin && (
            <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium"
              style={{ background: C.soft, color: C.primary, border: `1px solid ${C.border}` }}>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" /> 生产环境
            </span>
          )}
          {platformAdmin && (
            <>
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
                <input
                  placeholder="搜索租户 / 用户 / 密钥"
                  className="pl-9 pr-4 py-2 text-[15px] rounded-lg border outline-none w-64"
                  style={{ borderColor: C.border, background: C.bg }}
                />
              </div>
              <button className="relative p-2 rounded-lg hover:bg-gray-50">
                <Bell className="w-5 h-5" style={{ color: C.mid }} />
              </button>
            </>
          )}
          <div className="relative">
            <button
              className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg hover:bg-gray-50"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[15px] font-medium" style={{ background: C.primary }}>管</div>
              <span className="text-[15px]" style={{ color: C.mid }}>{identity?.display_name || identity?.username || "管理员"}</span>
              <ChevronDown className="w-4 h-4" style={{ color: C.light }} />
            </button>
            {menuOpen && (
              <div
                className="absolute right-0 mt-2 w-60 bg-white rounded-xl shadow-lg border py-1 z-40"
                style={{ borderColor: C.border }}
                onMouseLeave={() => setMenuOpen(false)}
              >
                {/* 我的账号：一眼看清登录人、所属机构、管理角色 */}
                <div className="px-4 py-3 border-b" style={{ borderColor: C.border }}>
                  <div className="text-[15px] font-medium" style={{ color: C.ink }}>
                    {identity?.display_name || identity?.username || "管理员"}
                  </div>
                  <div className="text-[12px] mt-1" style={{ color: C.mid }}>
                    {identity?.tenant_name || "—"}
                  </div>
                  <div className="text-[12px]" style={{ color: C.light }}>
                    {platformAdmin ? "平台超级管理员"
                      : (identity?.roles || []).includes("tenant_admin") ? "租户管理员"
                      : (identity?.roles || []).includes("org_admin") ? "机构管理员" : "管理员"}
                  </div>
                </div>
                <button
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-[15px] text-left hover:bg-gray-50"
                  style={{ color: C.mid }}
                  onClick={() => { setMenuOpen(false); setCpErr(""); setCpOk(""); setCpOld(""); setCpNew(""); setCpConfirm(""); setShowPwdModal(true); }}
                >
                  <Lock className="w-4 h-4" style={{ color: C.light }} /> 修改密码
                </button>
                <button
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-[15px] text-left hover:bg-gray-50"
                  style={{ color: C.mid }}
                  onClick={doLogout}
                >
                  <LogOut className="w-4 h-4" style={{ color: C.light }} /> 退出登录
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          {/* 租户精简视图（仅非超管可见，数据按 tenant_id 过滤） */}
          {!platformAdmin && effectivePage === "myhome" && <MyDashboard go={go} />}
          {!platformAdmin && effectivePage === "mybilling" && <MyBilling />}
          {!platformAdmin && effectivePage === "mykeys" && <MyKeys />}
          {!platformAdmin && effectivePage === "myagents" && <MyAgents />}
          {!platformAdmin && effectivePage === "myusage" && <MyUsage />}
          {!platformAdmin && effectivePage === "mytickets" && <MyTickets />}
          {!platformAdmin && effectivePage === "mylogs" && <MyLogs />}
          {!platformAdmin && effectivePage === "mysupport" && <MyContact go={go} />}
          {!platformAdmin && effectivePage === "myhelp" && <MyHelp />}

          {/* 平台方全量视图（仅 super_admin） */}
          {platformAdmin && effectivePage === "dashboard" && <Dashboard go={go} />}
          {platformAdmin && effectivePage === "agents" && <AgentCenter />}
          {platformAdmin && effectivePage === "tenants" && <Tenants go={go} />}
          {platformAdmin && effectivePage === "users" && <Users />}
          {platformAdmin && effectivePage === "roles" && <Roles />}
          {platformAdmin && effectivePage === "keys" && <ApiKeys />}
          {platformAdmin && effectivePage === "billing" && <Billing />}
          {platformAdmin && effectivePage === "capability" && <CapabilityCenter />}
          {platformAdmin && effectivePage === "content" && <Content />}
          {platformAdmin && effectivePage === "tickets" && <PlatformTickets />}
          {platformAdmin && effectivePage === "monitor" && <Monitor />}
          {platformAdmin && effectivePage === "planupgrade" && <PlanUpgrade />}
          {platformAdmin && effectivePage === "ledger" && <Ledger />}
        </main>
      </div>

      {/* 修改密码弹窗 */}
      {showPwdModal && (
        <div
          className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
          onClick={() => { setShowPwdModal(false); setMenuOpen(false); }}
        >
          <div
            className="bg-white rounded-2xl shadow-xl p-8 w-[420px]"
            style={{ border: `1px solid ${C.border}` }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-1">
              <Lock className="w-5 h-5" style={{ color: C.primary }} />
              <div className="font-bold text-[18px]" style={{ color: C.primary }}>修改密码</div>
            </div>
            <div className="text-[14px] mb-5" style={{ color: C.light }}>
              需验证原密码；修改成功后其他设备将重新登录
            </div>
            <div className="space-y-3">
              <input
                type="password" placeholder="原密码" value={cpOld}
                onChange={(e) => setCpOld(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[16px] outline-none"
                style={{ borderColor: C.border }}
              />
              <input
                type={cpShowNew ? "text" : "password"} placeholder="新密码（8-64位，含大小写+数字+特殊字符）"
                value={cpNew} onChange={(e) => setCpNew(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[16px] outline-none"
                style={{ borderColor: C.border }}
              />
              <input
                type={cpShowNew ? "text" : "password"} placeholder="确认新密码"
                value={cpConfirm} onChange={(e) => setCpConfirm(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[16px] outline-none"
                style={{ borderColor: C.border }}
              />
              <button
                type="button" onClick={() => setCpShowNew((v) => !v)}
                className="text-[14px] hover:underline -mt-1" style={{ color: C.light }}
              >
                {cpShowNew ? "隐藏密码" : "显示密码"}
              </button>
              {cpErr && <div className="text-[15px] text-red-600">{cpErr}</div>}
              {cpOk && <div className="text-[15px] text-emerald-600">{cpOk}</div>}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={submitChangePwd} disabled={cpBusy}
                  className="flex-1 py-2.5 rounded-lg text-white text-[16px] font-medium disabled:opacity-60"
                  style={{ background: C.primary }}
                >
                  {cpBusy ? "提交中..." : "确认修改"}
                </button>
                <button
                  onClick={() => { setShowPwdModal(false); setMenuOpen(false); }}
                  className="flex-1 py-2.5 rounded-lg border text-[16px]"
                  style={{ borderColor: C.border, color: C.mid }}
                >取消</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
