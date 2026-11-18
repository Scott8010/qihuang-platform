import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
  const orgName = identity?.display_name || identity?.username || "我的机构";

  const [wallet, setWallet] = useState<{ base: number; addon: number; total: number } | null>(null);
  const [usage, setUsage] = useState<{ totalCalls: number; usage: { agent_key: string; name: string; calls: number }[] }>({ totalCalls: 0, usage: [] });
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
      setUsage({ totalCalls: u.totalCalls, usage: u.usage });
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
    { label: "本月调用量", value: usage.totalCalls.toLocaleString("zh-CN"), sub: myPlan && myPlan.quotaCalls > 0 ? `配额 ${myPlan.quotaCalls.toLocaleString("zh-CN")} · 已用 ${quotaPct}%` : "按积分计费", icon: Zap },
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

      {/* 欢迎条 */}
      <div className="rounded-xl p-5 flex items-center justify-between" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div>
          <div className="text-[18px] font-bold" style={{ color: C.primary }}>你好，{orgName}</div>
          <div className="text-[13px] mt-1" style={{ color: C.mid }}>这是与你机构相关的数据——其他租户的信息你看不到。</div>
        </div>
        <Badge style={{ background: C.primary, color: "#fff" }}>客户视角</Badge>
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
                <div className="text-[12px] mt-2" style={{ color: C.light }}>配额为本月调用上限，用尽返回 2001 QUOTA_EXCEEDED</div>
              </>
            ) : (
              <div className="text-[14px] py-6 text-center" style={{ color: C.light }}>
                当前套餐按积分计费，无按月调用上限
              </div>
            )}

            {/* 我的 Agent 用量 TOP */}
            <div className="mt-5">
              <div className="text-[14px] font-medium mb-2" style={{ color: C.primary }}>近 30 天各能力调用</div>
              {usage.usage.length === 0 ? (
                <div className="text-[13px]" style={{ color: C.light }}>暂无调用数据</div>
              ) : (
                <div className="space-y-2">
                  {usage.usage.slice(0, 6).map((a) => (
                    <div key={a.agent_key} className="flex items-center justify-between text-[13px]">
                      <span style={{ color: C.mid }}>{a.name || a.agent_key}</span>
                      <span className="font-medium" style={{ color: C.ink }}>{a.calls.toLocaleString("zh-CN")} 次</span>
                    </div>
                  ))}
                </div>
              )}
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

      <div className="rounded-lg p-3 text-[12px]" style={{ background: "#FBF4E4", border: "1px solid #ecd9a8", color: C.gold }}>
        💡 本页只展示本机构数据。需要更多能力或调整套餐，请联系平台方为你的租户配置授权（addon）。
      </div>
    </div>
  );
}
