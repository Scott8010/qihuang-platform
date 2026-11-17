import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { C } from "@/lib/types";
import { getIdentity, fetchAgentUsage } from "@/lib/api";

/** 租户管理员的「用量账单」：只统计本租户调用（显式 tenant_id），与平台自身成本分列。 */
export default function MyUsage() {
  const identity = getIdentity();
  const tenantId = identity?.tenant_id || "";
  const [data, setData] = useState<{ usage: { agent_key: string; name: string; calls: number; tokens: number; cost_yuan: number }[]; totalCalls: number; totalCostYuan: number } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    fetchAgentUsage(tenantId, 30).then((r) => {
      if (!alive) return;
      setData(r);
      setLoading(false);
    });
    return () => { alive = false; };
  }, [tenantId]);

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px]" style={{ background: "#FBF4E4", border: "1px solid #ecd9a8", color: C.gold }}>
        💰 这里只统计<b>你自己的调用</b>（按积分计费）。平台自身跑 AI 的成本由平台承担，不计入你的账单。
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-12 justify-center text-[14px]" style={{ color: C.light }}><Loader2 className="w-4 h-4 animate-spin" />加载中…</div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "近 30 天调用", value: (data?.totalCalls || 0).toLocaleString("zh-CN"), icon: "⚡" },
              { label: "近 30 天费用", value: `¥${(data?.totalCostYuan || 0).toFixed(2)}`, icon: "🪙" },
              { label: "使用能力数", value: String(data?.usage.length || 0), icon: "🧩" },
            ].map((k) => (
              <Card key={k.label} className="border" style={{ borderColor: C.border }}>
                <CardContent className="p-5 flex items-center justify-between">
                  <div><div className="text-[13px]" style={{ color: C.light }}>{k.label}</div>
                    <div className="text-[24px] font-bold mt-1" style={{ color: C.primary }}>{k.value}</div></div>
                  <div className="text-[24px]">{k.icon}</div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card className="border" style={{ borderColor: C.border }}>
            <CardHeader className="pb-2"><CardTitle className="text-[16px]" style={{ color: C.primary }}>按能力拆分</CardTitle></CardHeader>
            <CardContent>
              {!data || data.usage.length === 0 ? (
                <div className="py-8 text-center text-[14px]" style={{ color: C.light }}>近 30 天暂无调用数据</div>
              ) : (
                <div className="overflow-x-auto"><table className="w-full text-[13px]">
                  <thead><tr className="text-left" style={{ color: C.light }}>
                    {["能力", "调用次数", "Tokens", "费用(元)"].map((h) => <th key={h} className="py-2 pr-4 font-normal whitespace-nowrap">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {data.usage.map((a) => (
                      <tr key={a.agent_key} className="border-t" style={{ borderColor: C.border }}>
                        <td className="py-3 pr-4" style={{ color: C.ink }}>{a.name || a.agent_key}</td>
                        <td className="py-3 pr-4" style={{ color: C.mid }}>{a.calls.toLocaleString("zh-CN")}</td>
                        <td className="py-3 pr-4" style={{ color: C.mid }}>{(a.tokens || 0).toLocaleString("zh-CN")}</td>
                        <td className="py-3 pr-4" style={{ color: C.mid }}>¥{(a.cost_yuan || 0).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
