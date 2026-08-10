import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus, KeyRound, Copy, RefreshCw, Ban, Loader2 } from "lucide-react";
import { C, keyStatus } from "@/lib/types";
import type { ApiKey } from "@/lib/types";
import { fetchApiKeys } from "@/lib/api";

/* ═══════════════════════════════════════════
   API 密钥管理 — 真实接口 GET /admin/v1/api-keys/
   后端无配额字段时显示「不限」，不假造数值
   ═══════════════════════════════════════════ */

function maskKey(k: string) {
  if (!k) return "—";
  if (k.length <= 12) return k;
  return `${k.slice(0, 8)}****${k.slice(-4)}`;
}

function purposeStyle(p: string) {
  const up = (p || "").toUpperCase();
  if (up === "TEST" || up === "DEV") return { color: "#888", background: "#F5F5F5" };
  return { color: "#2E5A4C", background: "#EAF2EE" };
}

function statusStyle(s: string) {
  const up = (s || "ACTIVE").toUpperCase();
  if (up === "REVOKED") return { label: "已吊销", color: "#B03A2E", background: "#FDECEA" };
  if (up === "EXPIRED") return { label: "已过期", color: "#888", background: "#F5F5F5" };
  if (up === "ROTATING") return { label: "轮换中", color: "#8A6A1F", background: "#FBF4E4" };
  return { label: keyStatus[up]?.label || "正常", color: "#2E5A4C", background: "#EAF2EE" };
}

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
  const [list, setList] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState<string>("");

  useEffect(() => {
    fetchApiKeys()
      .then((d) => setList(d))
      .finally(() => setLoading(false));
  }, []);

  const copy = (v: string) => {
    navigator.clipboard?.writeText(v);
    setCopied(v);
    setTimeout(() => setCopied(""), 1500);
  };

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
              {loading && (
                <tr>
                  <td colSpan={7} className="px-5 py-10 text-center" style={{ color: C.light }}>
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> 加载中…
                  </td>
                </tr>
              )}

              {!loading && list.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center" style={{ color: C.light }}>
                    <KeyRound className="w-8 h-8 mx-auto mb-2 opacity-40" />
                    <div className="text-[13px]">暂无 API 密钥</div>
                    <div className="text-[11px] mt-1">点击右上角「签发新密钥」为租户创建第一个 Key</div>
                  </td>
                </tr>
              )}

              {!loading && list.map((k) => {
                const st = statusStyle(k.status);
                const ps = purposeStyle(k.purpose);
                const hasQuota = k.quota !== null && k.quota > 0;
                const pct = hasQuota ? Math.min(100, Math.round((k.used / (k.quota as number)) * 100)) : 0;
                return (
                  <tr key={k.id || k.appKey} className="border-b last:border-0 hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <KeyRound className="w-4 h-4" style={{ color: C.light }} />
                        <span className="font-mono text-[12px]" style={{ color: C.ink }}>{maskKey(k.appKey)}</span>
                        <button className="hover:opacity-70" onClick={() => copy(k.appKey)} title="复制完整 Key">
                          <Copy className="w-3.5 h-3.5" style={{ color: copied === k.appKey ? C.primary : C.light }} />
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.tenant || "—"}</td>
                    <td className="px-3 py-3.5">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={ps}>{k.purpose}</span>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.qps || "—"}</td>
                    <td className="px-3 py-3.5">
                      {hasQuota ? (
                        <>
                          <div className="flex justify-between text-[11px] mb-1" style={{ color: pct >= 100 ? "#B03A2E" : C.mid }}>
                            <span>{k.used.toLocaleString()} / {(k.quota as number).toLocaleString()}</span>
                          </div>
                          <ProgressBar pct={pct} />
                        </>
                      ) : (
                        <span className="text-[12px]" style={{ color: C.mid }}>
                          {k.used.toLocaleString()} / <span style={{ color: C.light }}>不限</span>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="text-[11px] px-2 py-0.5 rounded" style={{ color: st.color, background: st.background }}>
                        {st.label}
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
