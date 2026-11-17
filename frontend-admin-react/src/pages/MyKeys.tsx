import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { C } from "@/lib/types";
import { getIdentity, fetchApiKeys, rotateApiKey, revokeApiKey } from "@/lib/api";
import { toast } from "sonner";

/** 租户管理员的「我的密钥」：只列本租户密钥（显式 tenant_id 过滤），不碰全平台列表。 */
export default function MyKeys() {
  const identity = getIdentity();
  const tenantId = identity?.tenant_id || "";
  const [keys, setKeys] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  const load = async () => {
    setLoading(true);
    // fetchApiKeys(tenantId) 后端已按 tenant_id 过滤，拿到的就是本租户密钥
    const list = await fetchApiKeys(tenantId);
    setKeys(list);
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [tenantId]);

  const doRotate = async (id: string) => {
    setBusy(id);
    const r = await rotateApiKey(id);
    setBusy("");
    if (r.ok) { toast.success("密钥已轮换，旧密钥 72h 内仍可用"); load(); }
    else toast.error(r.msg || "轮换失败");
  };
  const doRevoke = async (id: string) => {
    setBusy(id);
    const r = await revokeApiKey(id);
    setBusy("");
    if (r.ok) { toast.success("密钥已吊销"); load(); }
    else toast.error(r.msg || "吊销失败");
  };

  return (
    <div className="space-y-5">
      <div className="rounded-lg p-3 text-[13px]" style={{ background: C.soft, border: `1px solid ${C.border}`, color: C.mid }}>
        🔑 你的服务器用 <b>app_key + HMAC 签名</b>调用 AI 能力。<code style={{ color: C.primary }}>app_secret</code> 仅在签发时显示一次，丢失走轮换，不在页面留存。
      </div>
      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2"><CardTitle className="text-[16px]" style={{ color: C.primary }}>我的 API 密钥</CardTitle></CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center gap-2 py-8 justify-center text-[14px]" style={{ color: C.light }}><Loader2 className="w-4 h-4 animate-spin" />加载中…</div>
          ) : keys.length === 0 ? (
            <div className="py-8 text-center text-[14px]" style={{ color: C.light }}>暂无密钥，请联系平台方签发，或在此新建</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr className="text-left" style={{ color: C.light }}>
                  {["app_key", "用途", "QPS", "状态", "操作"].map((h) => <th key={h} className="py-2 pr-4 font-normal whitespace-nowrap">{h}</th>)}
                </tr></thead>
                <tbody>
                  {keys.map((k) => (
                    <tr key={k.id} className="border-t" style={{ borderColor: C.border }}>
                      <td className="py-3 pr-4 font-mono" style={{ color: C.ink }}>{k.appKey}</td>
                      <td className="py-3 pr-4" style={{ color: C.mid }}>{k.purpose}</td>
                      <td className="py-3 pr-4" style={{ color: C.mid }}>{k.qps || "—"}</td>
                      <td className="py-3 pr-4"><Badge className={k.status === "ACTIVE" ? "" : ""} style={k.status === "ACTIVE" ? { background: C.soft, color: C.primary } : { background: "#FDECEA", color: "#B03A2E" }}>{k.status === "ACTIVE" ? "启用中" : k.status}</Badge></td>
                      <td className="py-3 pr-4 whitespace-nowrap">
                        <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => doRotate(k.id)} title="轮换"><RefreshCw className="w-4 h-4" /></Button>
                        <Button variant="ghost" size="sm" disabled={!!busy} onClick={() => doRevoke(k.id)} title="吊销"><Trash2 className="w-4 h-4" style={{ color: "#B03A2E" }} /></Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
