import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus, KeyRound, Copy, RefreshCw, Ban } from "lucide-react";
import { C } from "@/lib/types";

/* ═══════════════════════════════════════════
   API 密钥管理 — 按 KIMI 截图设计
   ═══════════════════════════════════════════ */

interface KeyRow {
  keyId: string; keyMasked: string; tenant: string;
  purpose: string; purposeBg: string; purposeColor: string;
  qps: number; used: number; quota: number;
  status: string; statusColor: string; statusBg: string;
}

const KEYS: KeyRow[] = [
  {
    keyId: "qh_9f2k****8d1x", keyMasked: "qh_9f2k****8d1x", tenant: "颐森汇健康集团",
    purpose: "PROD", purposeBg: "#EAF2EE", purposeColor: "#2E5A4C",
    qps: 50, used: 386200, quota: 500000, status: "正常", statusColor: "#2E5A4C", statusBg: "#EAF2EE",
  },
  {
    keyId: "qh_test****3c7a", keyMasked: "qh_test****3c7a", tenant: "颐森汇健康集团",
    purpose: "TEST", purposeBg: "#F5F5F5", purposeColor: "#888",
    qps: 5, used: 1240, quota: 10000, status: "正常", statusColor: "#2E5A4C", statusBg: "#EAF2EE",
  },
  {
    keyId: "qh_7h4m****2f9e", keyMasked: "qh_7h4m****2f9e", tenant: "沪上云杉中医馆",
    purpose: "PROD", purposeBg: "#EAF2EE", purposeColor: "#2E5A4C",
    qps: 10, used: 42100, quota: 50000, status: "正常", statusColor: "#2E5A4C", statusBg: "#EAF2EE",
  },
  {
    keyId: "qh_3j8p****6k2b", keyMasked: "qh_3j8p****6k2b", tenant: "杏林在线教育学院",
    purpose: "PROD", purposeBg: "#EAF2EE", purposeColor: "#2E5A4C",
    qps: 50, used: 610400, quota: 500000, status: "轮换中", statusColor: "#2E5A4C", statusBg: "#EAF2EE",
  },
  {
    keyId: "qh_new5****9q4w", keyMasked: "qh_new5****9q4w", tenant: "杏林在线教育学院",
    purpose: "PROD", purposeBg: "#EAF2EE", purposeColor: "#2E5A4C",
    qps: 50, used: 0, quota: 500000, status: "正常", statusColor: "#2E5A4C", statusBg: "#EAF2EE",
  },
  {
    keyId: "qh_5tky****128c", keyMasked: "qh_5tky****128c", tenant: "天津颐和堂大药房",
    purpose: "PROD", purposeBg: "#EAF2EE", purposeColor: "#2E5A4C",
    qps: 10, used: 33800, quota: 50000, status: "已吊销", statusColor: "#B03A2E", statusBg: "#FDECEA",
  },
];

function ProgressBar({ pct }: { pct: number }) {
  const color = pct >= 100 ? "#B03A2E" : pct >= 80 ? "#8A6A1F" : "#2E5A4C";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "#E3ECE8" }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
      </div>
      <span className="text-[11px] w-8 text-right shrink-0" style={{ color: pct >= 100 ? "#B03A2E" : C.mid }}>{pct}%</span>
    </div>
  );
}

export default function ApiKeys() {
  const [list] = useState<KeyRow[]>(KEYS);

  return (
    <div className="space-y-4">
      {/* 顶部 */}
      <div className="flex items-center justify-between">
        <div className="text-[12px]" style={{ color: C.mid }}>
          API Key 绑定租户与配额，签名验签（HMAC-SHA256 + 时间窗 ±5min + nonce 防重放）在网关完成；轮换提供 72 小时新旧并行期。
        </div>
        <Button size="sm" style={{ background: C.primary }}>
          <Plus className="w-4 h-4 mr-1" /> 签发新密钥
        </Button>
      </div>

      {/* 列表 */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-0">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b text-left" style={{ borderColor: C.border, color: C.light }}>
                <th className="px-5 py-3 font-medium">API Key</th>
                <th className="px-3 py-3 font-medium">所属租户</th>
                <th className="px-3 py-3 font-medium">用途</th>
                <th className="px-3 py-3 font-medium">QPS</th>
                <th className="px-3 py-3 font-medium w-[200px]">月用量 / 配额</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-5 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((k) => {
                const pct = Math.min(100, Math.round((k.used / k.quota) * 100));
                return (
                  <tr key={k.keyId} className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <KeyRound className="w-4 h-4" style={{ color: C.light }} />
                        <span className="font-mono text-[12px]" style={{ color: C.ink }}>{k.keyMasked}</span>
                        <button className="hover:opacity-70"><Copy className="w-3.5 h-3.5" style={{ color: C.light }} /></button>
                      </div>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.tenant}</td>
                    <td className="px-3 py-3.5">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={{ color: k.purposeColor, background: k.purposeBg }}>
                        {k.purpose}
                      </span>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.qps}</td>
                    <td className="px-3 py-3.5">
                      <div className="flex justify-between text-[11px] mb-1" style={{ color: pct >= 100 ? "#B03A2E" : C.mid }}>
                        <span>{k.used.toLocaleString()} / {k.quota.toLocaleString()}</span>
                      </div>
                      <ProgressBar pct={pct} />
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={{ color: k.statusColor, background: k.statusBg }}>
                        {k.status}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button className="flex items-center gap-1 text-[12px] hover:opacity-70" style={{ color: C.mid }}>
                          <RefreshCw className="w-3.5 h-3.5" /> 轮换
                        </button>
                        <button className="flex items-center gap-1 text-[12px] hover:opacity-70" style={{ color: "#B03A2E" }}>
                          <Ban className="w-3.5 h-3.5" /> 吊销
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <div className="text-[11px]" style={{ color: C.light }}>
        轮换说明：新 Key 签发后旧 Key 进入 72h 并行期（状态"轮换中"），到期自动失效；吊销即时生效并记录审计日志。
      </div>
    </div>
  );
}
