import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Users, Zap, Wallet, Loader2, ArrowRight, KeyRound, Sparkles,
} from "lucide-react";
import { C } from "@/lib/types";
import {
  getIdentity, fetchWalletBalance, fetchAgentUsage, fetchApiKeys, fetchTenantExtended,
} from "@/lib/api";

/**
 * MyDashboard — 租户管理员（tenant_admin/org_admin）登录后的轻量首页。
 * 与平台方 Dashboard（全平台 KPI）不同：这里只展示「我的」数据。
 * 数据全部复用现有 API 封装，且按本租户 tenant_id 显式过滤，不写 mock。
 */
export default function MyDashboard({ go }: { go: (p: string) => void }) {
  const [loading, setLoading] = useState(true);
  const identity = getIdentity();
  const tenantId = identity?.tenant_id || "";
  // 机构名来自登录响应（后端读 tenant 表），不是登录人姓名；角色按中文展示。
  const userName = identity?.display_name || identity?.username || "管理员";
  const orgName = identity?.tenant_name || "我的机构";
  const roleName = (identity?.roles || []).includes("super_admin") ? "平台超级管理员"
    : (identity?.roles || []).includes("tenant_admin") ? "租户管理员"
    : (identity?.roles || []).includes("org_admin") ? "机构管理员"
    : (identity?.roles || []).includes("admin") ? "管理员" : "管理员";

  const [wallet, setWallet] = useState<{ base: number; addon: number; total: number } | null>(null);
  const [totalCalls, setTotalCalls] = useState(0);
  const [keyCount, setKeyCount] = useState(0);
  const [myPlan, setMyPlan] = useState<{ plan: string; quotaCalls: number; usedCalls: number; userCount: number } | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      // 钱包积分 / 用量 / 密钥：都按本租户 tenant_id 过滤（后端支持显式参数）
      const [w, u, k] = await Promise.all([
        fetchWalletBalance(tenantId),
        fetchAgentUsage(tenantId, 30),
        fetchApiKeys(tenantId),
      ]);
      // 套餐/用户数：tenants-extended 返回全量，前端只取自己那条，不外泄别家。
      // 注意 page_size 后端上限 100，传 200 会 422 导致套餐永远"读取中"。
      const all = await fetchTenantExtended(100);
      const mine = all.find((t) => t.id === tenantId);
      if (!alive) return;
      setWallet(w);
      setTotalCalls(u.totalCalls);
      setKeyCount(k.filter((x) => x.status === "ACTIVE").length);
      if (mine) {
        setMyPlan({
          plan: mine.plan || "—",
          quotaCalls: mine.quotaCalls || 0,
          usedCalls: mine.usedCalls || 0,
          userCount: mine.users || 0,
        });
      }
      setLoading(false);
    })();
    return () => { alive = false; };
  }, [tenantId]);

  const quotaPct = myPlan && myPlan.quotaCalls > 0
    ? Math.min(100, Math.round((myPlan.usedCalls / myPlan.quotaCalls) * 100)) : 0;

  const kpis = [
    { label: "我的套餐", value: myPlan?.plan || (loading ? "读取中" : "—"), sub: "套餐决定可用的 Agent 能力", icon: Sparkles },
    { label: "本月调用量", value: totalCalls.toLocaleString("zh-CN"), sub: myPlan && myPlan.quotaCalls > 0 ? `配额 ${myPlan.quotaCalls.toLocaleString("zh-CN")} · 已用 ${quotaPct}%` : "按积分计费", icon: Zap },
    { label: "积分余额", value: wallet ? wallet.total.toLocaleString("zh-CN") : "—", sub: wallet ? `基础 ${wallet.base} · 叠加 ${wallet.addon}` : "钱包数据", icon: Wallet },
    { label: "我的团队", value: String(myPlan?.userCount ?? "—"), sub: `有效密钥 ${keyCount} 把`, icon: Users },
  ];

  return (
    <div className="space-y-5">
      {loading && (
        <div className="flex items-center gap-2 text-[15px]" style={{ color: C.light }}>
          <Loader2 className="w-4 h-4 animate-spin" /> 正在加载我的数据…
        </div>
      )}

      {/* 欢迎条：只讲「你是谁、属于哪家机构」，不展示内部隔离口径 */}
      <div className="rounded-xl p-5 flex items-center justify-between" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div>
          <div className="text-[18px] font-bold" style={{ color: C.primary }}>你好，{userName}</div>
          <div className="text-[13px] mt-1" style={{ color: C.mid }}>{orgName} · {roleName}</div>
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4">
        {kpis.map((k) => (
          <Card key={k.label} className="border" style={{ borderColor: C.border }}>
            <CardContent className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-[14px]" style={{ color: C.light }}>{k.label}</div>
                  <div className="text-[25px] font-bold mt-1 tracking-tight" style={{ color: C.primary }}>{k.value}</div>
                </div>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: C.soft }}>
                  <k.icon className="w-5 h-5" style={{ color: C.primary }} />
                </div>
              </div>
              <div className="mt-2 text-[13px]" style={{ color: C.mid }}>{k.sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 我的用量配额 */}
        <Card className="col-span-2 border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-[16px]" style={{ color: C.primary }}>本月用量配额</CardTitle>
              <Button variant="outline" size="sm" onClick={() => go("myusage")} className="text-[13px]">
                用量明细 <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {myPlan && myPlan.quotaCalls > 0 ? (
              <>
                <div className="flex justify-between text-[13px] mb-2" style={{ color: C.mid }}>
                  <span>已用 {myPlan.usedCalls.toLocaleString("zh-CN")} 次</span>
                  <span>共 {myPlan.quotaCalls.toLocaleString("zh-CN")} 次</span>
                </div>
                <Progress value={quotaPct} />
                <div className="text-[12px] mt-2" style={{ color: C.light }}>
                  本月次数已用 {quotaPct}%，需要更多次数可联系平台方调整套餐。
                </div>
              </>
            ) : (
              <div className="text-[14px] py-4 text-center" style={{ color: C.light }}>
                当前套餐按实际用量结算，本月没有调用次数上限
              </div>
            )}
            <div className="text-[13px] mt-4 pt-3 border-t" style={{ borderColor: C.border, color: C.mid }}>
              想看每次调用的时间、接口和消耗，点右上角「用量明细」。
            </div>
          </CardContent>
        </Card>

        {/* 我的密钥快捷入口 */}
        <Card className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2"><CardTitle className="text-[16px]" style={{ color: C.primary }}>系统对接</CardTitle></CardHeader>
          <CardContent>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ background: C.soft }}>
                <KeyRound className="w-5 h-5" style={{ color: C.primary }} />
              </div>
              <div>
                <div className="text-[22px] font-bold" style={{ color: C.primary }}>{keyCount}</div>
                <div className="text-[12px]" style={{ color: C.light }}>把有效密钥</div>
              </div>
            </div>
            <div className="text-[13px] mb-3" style={{ color: C.mid }}>你的服务器用密钥 + HMAC 签名调用 AI 能力。</div>
            <Button variant="outline" size="sm" onClick={() => go("mykeys")} className="w-full text-[13px]" style={{ borderColor: C.primary, color: C.primary }}>
              管理我的密钥
            </Button>
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
