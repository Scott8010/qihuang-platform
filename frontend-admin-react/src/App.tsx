import { useState, useEffect } from "react";
import {
  LayoutDashboard, Building2, ShieldCheck, KeyRound, BarChart3,
  BookOpenCheck, Activity, Search, Bell, Sprout, ChevronDown, LogOut,
  Users as UsersIcon, Eye, EyeOff, Lock,
} from "lucide-react";
import { C } from "@/lib/types";
import { login, logout, getToken, changePassword, getIdentity } from "@/lib/api";
import Dashboard from "@/pages/Dashboard";
import Tenants from "@/pages/Tenants";
import Roles from "@/pages/Roles";
import Users from "@/pages/Users";
import ApiKeys from "@/pages/ApiKeys";
import Billing from "@/pages/Billing";
import Content from "@/pages/Content";
import Monitor from "@/pages/Monitor";

const nav = [
  { id: "dashboard", label: "工作台", icon: LayoutDashboard },
  { id: "tenants", label: "租户管理", icon: Building2 },
  { id: "users", label: "用户管理", icon: UsersIcon },
  { id: "roles", label: "权限管理", icon: ShieldCheck },
  { id: "keys", label: "密钥配额", icon: KeyRound },
  { id: "billing", label: "计量计费", icon: BarChart3 },
  { id: "content", label: "内容管控", icon: BookOpenCheck },
  { id: "monitor", label: "监控运维", icon: Activity },
];

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState("dashboard");
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [showPass, setShowPass] = useState(false);

  // 修改密码弹窗状态
  const [menuOpen, setMenuOpen] = useState(false);
  const [showPwdModal, setShowPwdModal] = useState(false);
  const [cpOld, setCpOld] = useState("");
  const [cpNew, setCpNew] = useState("");
  const [cpConfirm, setCpConfirm] = useState("");
  const [cpShowNew, setCpShowNew] = useState(false);
  const [cpErr, setCpErr] = useState("");
  const [cpOk, setCpOk] = useState("");
  const [cpBusy, setCpBusy] = useState(false);

  useEffect(() => {
    if (getToken()) setAuthed(true);
    setChecking(false);
  }, []);

  const doLogin = async () => {
    setLoginErr("");
    const ok = await login(loginUser, loginPass || undefined);
    if (ok) { setAuthed(true); } else { setLoginErr("登录失败，请检查账号或密码"); }
  };

  const doLogout = () => {
    logout();
    setAuthed(false);
    setPage("dashboard");
    setMenuOpen(false);
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
              <div className="font-bold text-[18px] tracking-wide" style={{ color: C.primary }}>岐黄智脑</div>
              <div className="text-[12px]" style={{ color: C.light }}>运营控制台 · V1.2</div>
            </div>
          </div>
          <div className="space-y-4">
            <input
              value={loginUser} onChange={(e) => setLoginUser(e.target.value)}
              placeholder="管理员账号" autoFocus
              onKeyDown={(e) => e.key === "Enter" && doLogin()}
              className="w-full px-4 py-3 rounded-lg border text-[14px] outline-none"
              style={{ borderColor: C.border }}
            />
            <div className="relative">
              <input
                type={showPass ? "text" : "password"} value={loginPass}
                onChange={(e) => setLoginPass(e.target.value)}
                placeholder="密码（可选）"
                onKeyDown={(e) => e.key === "Enter" && doLogin()}
                className="w-full px-4 py-3 pr-11 rounded-lg border text-[14px] outline-none"
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
              <button type="button" onClick={onForgot} className="text-[12px] hover:underline" style={{ color: C.light }}>
                忘记密码？
              </button>
            </div>
            {loginErr && <div className="text-[13px] text-red-600">{loginErr}</div>}
            <button
              onClick={doLogin}
              className="w-full py-3 rounded-lg text-white font-medium text-[14px]"
              style={{ background: C.primary }}
            >登录控制台</button>
          </div>
        </div>
      </div>
    );
  }

  const identity = getIdentity();
  const current = nav.find((n) => n.id === page)!;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: C.bg, color: C.ink }}>
      {/* 侧边栏 */}
      <aside className="w-[232px] shrink-0 bg-white border-r flex flex-col" style={{ borderColor: C.border }}>
        <div className="flex items-center gap-3 px-5 h-16 border-b" style={{ borderColor: C.border }}>
          <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: C.primary }}>
            <Sprout className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="font-bold text-[15px] tracking-wide" style={{ color: C.primary }}>岐黄智脑</div>
            <div className="text-[11px]" style={{ color: C.light }}>运营控制台 · V1.2</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <div className="px-3 pt-2 pb-1 text-[11px] font-medium" style={{ color: C.light }}>运营管理</div>
          {nav.map((n) => {
            const active = page === n.id;
            return (
              <button
                key={n.id}
                onClick={() => setPage(n.id)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[14px] transition-colors"
                style={{
                  background: active ? C.soft : "transparent",
                  color: active ? C.primary : C.mid,
                  fontWeight: active ? 600 : 400,
                }}
              >
                <n.icon className="w-[18px] h-[18px]" style={{ color: active ? C.primary : C.light }} />
                <span className="flex-1 text-left">{n.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="p-4 border-t text-[12px] leading-relaxed" style={{ borderColor: C.border, color: C.light }}>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
            <span style={{ color: C.mid }}>平台运行正常</span>
          </div>
          <button onClick={doLogout} className="flex items-center gap-1 mt-1" style={{ color: C.light }}>
            <LogOut className="w-3 h-3" /> 退出登录
          </button>
        </div>
      </aside>

      {/* 主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white border-b flex items-center gap-4 px-6 shrink-0" style={{ borderColor: C.border }}>
          <h1 className="text-[17px] font-semibold" style={{ color: C.primary }}>{current.label}</h1>
          <div className="flex-1" />
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: C.light }} />
            <input
              placeholder="搜索租户 / 用户 / 密钥"
              className="pl-9 pr-4 py-2 text-[13px] rounded-lg border outline-none w-64"
              style={{ borderColor: C.border, background: C.bg }}
            />
          </div>
          <button className="relative p-2 rounded-lg hover:bg-gray-50">
            <Bell className="w-5 h-5" style={{ color: C.mid }} />
          </button>
          <div className="relative">
            <button
              className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg hover:bg-gray-50"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-[13px] font-medium" style={{ background: C.primary }}>管</div>
              <span className="text-[13px]" style={{ color: C.mid }}>{identity?.display_name || identity?.username || "管理员"}</span>
              <ChevronDown className="w-4 h-4" style={{ color: C.light }} />
            </button>
            {menuOpen && (
              <div
                className="absolute right-0 mt-2 w-44 bg-white rounded-xl shadow-lg border py-1 z-40"
                style={{ borderColor: C.border }}
                onMouseLeave={() => setMenuOpen(false)}
              >
                <button
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-left hover:bg-gray-50"
                  style={{ color: C.mid }}
                  onClick={() => { setMenuOpen(false); setCpErr(""); setCpOk(""); setCpOld(""); setCpNew(""); setCpConfirm(""); setShowPwdModal(true); }}
                >
                  <Lock className="w-4 h-4" style={{ color: C.light }} /> 修改密码
                </button>
                <button
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-[13px] text-left hover:bg-gray-50"
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
          {page === "dashboard" && <Dashboard go={setPage} />}
          {page === "tenants" && <Tenants />}
          {page === "users" && <Users />}
          {page === "roles" && <Roles />}
          {page === "keys" && <ApiKeys />}
          {page === "billing" && <Billing />}
          {page === "content" && <Content />}
          {page === "monitor" && <Monitor />}
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
              <div className="font-bold text-[16px]" style={{ color: C.primary }}>修改密码</div>
            </div>
            <div className="text-[12px] mb-5" style={{ color: C.light }}>
              需验证原密码；修改成功后其他设备将重新登录
            </div>
            <div className="space-y-3">
              <input
                type="password" placeholder="原密码" value={cpOld}
                onChange={(e) => setCpOld(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[14px] outline-none"
                style={{ borderColor: C.border }}
              />
              <input
                type={cpShowNew ? "text" : "password"} placeholder="新密码（8-64位，含大小写+数字+特殊字符）"
                value={cpNew} onChange={(e) => setCpNew(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[14px] outline-none"
                style={{ borderColor: C.border }}
              />
              <input
                type={cpShowNew ? "text" : "password"} placeholder="确认新密码"
                value={cpConfirm} onChange={(e) => setCpConfirm(e.target.value)}
                className="w-full px-4 py-3 rounded-lg border text-[14px] outline-none"
                style={{ borderColor: C.border }}
              />
              <button
                type="button" onClick={() => setCpShowNew((v) => !v)}
                className="text-[12px] hover:underline -mt-1" style={{ color: C.light }}
              >
                {cpShowNew ? "隐藏密码" : "显示密码"}
              </button>
              {cpErr && <div className="text-[13px] text-red-600">{cpErr}</div>}
              {cpOk && <div className="text-[13px] text-emerald-600">{cpOk}</div>}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={submitChangePwd} disabled={cpBusy}
                  className="flex-1 py-2.5 rounded-lg text-white text-[14px] font-medium disabled:opacity-60"
                  style={{ background: C.primary }}
                >
                  {cpBusy ? "提交中..." : "确认修改"}
                </button>
                <button
                  onClick={() => { setShowPwdModal(false); setMenuOpen(false); }}
                  className="flex-1 py-2.5 rounded-lg border text-[14px]"
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
