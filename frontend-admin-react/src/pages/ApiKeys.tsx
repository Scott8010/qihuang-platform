import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Plus, KeyRound, Copy, RefreshCw, Ban, Loader2, FileDown } from "lucide-react";
import { C, keyStatus } from "@/lib/types";
import type { ApiKey, Tenant } from "@/lib/types";
import { fetchApiKeys, fetchTenants, createApiKey, rotateApiKey, revokeApiKey } from "@/lib/api";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";

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
      <span className="text-[13px] w-8 text-right shrink-0" style={{ color: pct >= 100 ? "#B03A2E" : C.mid }}>{pct}%</span>
    </div>
  );
}

export default function ApiKeys() {
  const [list, setList] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState<string>('');

  // 签发
  const [issueOpen, setIssueOpen] = useState(false);
  const [tenantInput, setTenantInput] = useState('');
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<{ app_key: string; app_secret: string } | null>(null);
  // 租户下拉（修复 #593：从下拉选 tenant_id，避免手填 uuid 出错导致「假成功」）
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantsLoading, setTenantsLoading] = useState(false);
  // 轮换 / 吊销 二次确认
  const [confirm, setConfirm] = useState<{ type: 'rotate' | 'revoke'; key?: ApiKey } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  const reload = () => { fetchApiKeys().then(setList); };

  useEffect(() => {
    fetchApiKeys()
      .then((d) => setList(d))
      .finally(() => setLoading(false));
  }, []);

  // 打开签发弹窗时加载租户列表（每次打开都刷新，确保新开的客户立即可选）
  useEffect(() => {
    if (issueOpen) {
      setTenantsLoading(true);
      fetchTenants()
        .then((ts) => setTenants(ts))
        .finally(() => setTenantsLoading(false));
    }
  }, [issueOpen]);

  const copy = (v: string, label: string) => {
    navigator.clipboard?.writeText(v);
    setCopied(v);
    setTimeout(() => setCopied(""), 1500);
    if (label === 'app_secret') {
      toast.success('SK 已复制 · 请妥善保存到客户 .env，关闭后不再显示', {
        duration: 4000,
        description: '建议走安全通道交付（加密文件 / 线下），不要发到聊天框',
      });
    } else {
      toast.success(`${label} 已复制`);
    }
  };

  async function doIssue() {
    if (!tenantInput.trim()) { toast.error('请填写租户ID'); return; }
    setIssuing(true);
    const r = await createApiKey(tenantInput.trim());
    setIssuing(false);
    if (r.ok) {
      setIssued({ app_key: r.data?.app_key || '', app_secret: r.data?.app_secret || '' });
      toast.success('API 密钥已签发');
      reload();
    } else {
      toast.error(r.msg || '签发失败');
    }
  }

  async function doRotate() {
    if (!confirm?.key) return;
    const kid = confirm.key.id || confirm.key.appKey;
    setConfirmBusy(true);
    const r = await rotateApiKey(kid);
    setConfirmBusy(false);
    if (r.ok) {
      toast.success('密钥已轮换，旧密钥 72 小时内仍有效');
      setConfirm(null);
      reload();
    } else {
      toast.error(r.msg || '轮换失败');
    }
  }

  async function doRevoke() {
    if (!confirm?.key) return;
    const kid = confirm.key.id || confirm.key.appKey;
    setConfirmBusy(true);
    const r = await revokeApiKey(kid);
    setConfirmBusy(false);
    if (r.ok) {
      toast.success('密钥已吊销');
      setConfirm(null);
      reload();
    } else {
      toast.error(r.msg || '吊销失败');
    }
  }

  return (
    <div className="space-y-4">
      {/* 顶部 */}
      <div className="flex items-center justify-between">
        <div className="text-[14px]" style={{ color: C.mid }}>
          API Key 绑定租户与配额，签名验签（HMAC-SHA256 + 时间窗 ±5min + nonce 防重放）在网关完成；轮换提供 72 小时新旧并行期。
        </div>
        <Button size="sm" style={{ background: C.primary }}
          onClick={() => { setIssued(null); setTenantInput(''); setIssueOpen(true); }}>
          <Plus className="w-4 h-4 mr-1" /> 签发新密钥
        </Button>
      </div>

      {/* 列表 */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-0">
          <table className="w-full text-[15px]">
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
                    <div className="text-[15px]">暂无 API 密钥</div>
                    <div className="text-[13px] mt-1">点击右上角「签发新密钥」为租户创建第一个 Key</div>
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
                        <span className="font-mono text-[14px]" style={{ color: C.ink }}>{maskKey(k.appKey)}</span>
                        <button className="hover:opacity-70" onClick={() => copy(k.appKey, 'app_key')} title="复制完整 Key">
                          <Copy className="w-3.5 h-3.5" style={{ color: copied === k.appKey ? C.primary : C.light }} />
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.tenant || "—"}</td>
                    <td className="px-3 py-3.5">
                      <span className="text-[13px] px-2 py-0.5 rounded" style={ps}>{k.purpose}</span>
                    </td>
                    <td className="px-3 py-3.5" style={{ color: C.mid }}>{k.qps || "—"}</td>
                    <td className="px-3 py-3.5">
                      {hasQuota ? (
                        <>
                          <div className="flex justify-between text-[13px] mb-1" style={{ color: pct >= 100 ? "#B03A2E" : C.mid }}>
                            <span>{k.used.toLocaleString()} / {(k.quota as number).toLocaleString()}</span>
                          </div>
                          <ProgressBar pct={pct} />
                        </>
                      ) : (
                        <span className="text-[14px]" style={{ color: C.mid }}>
                          {k.used.toLocaleString()} / <span style={{ color: C.light }}>不限</span>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="text-[13px] px-2 py-0.5 rounded" style={{ color: st.color, background: st.background }}>
                        {st.label}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button className='flex items-center gap-1 text-[14px] hover:opacity-70' style={{ color: C.mid }}
                          onClick={() => setConfirm({ type: 'rotate', key: k })}>
                          <RefreshCw className='w-3.5 h-3.5' /> 轮换
                        </button>
                        <button className='flex items-center gap-1 text-[14px] hover:opacity-70' style={{ color: '#B03A2E' }}
                          onClick={() => setConfirm({ type: 'revoke', key: k })}>
                          <Ban className='w-3.5 h-3.5' /> 吊销
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

      <div className="text-[13px]" style={{ color: C.light }}>
        轮换说明：新 Key 签发后旧 Key 进入 72h 并行期（状态"轮换中"），到期自动失效；吊销即时生效并记录审计日志。
      </div>

      {/* 签发新密钥 */}
      <Dialog open={issueOpen} onOpenChange={(o) => { if (!o) { setIssueOpen(false); setIssued(null); setTenantInput(''); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>签发新密钥</DialogTitle>
            <DialogDescription>为指定租户创建一对 API Key（app_key + app_secret），请妥善保存 secret。</DialogDescription>
          </DialogHeader>
          {issued ? (
            <div className='space-y-3'>
              <div className='text-[14px]' style={{ color: C.mid }}>密钥已签发，secret 仅展示一次：</div>
              <div className='rounded p-3 bg-[#F8FAF9] text-[14px] font-mono break-all'>
                <div>app_key: {issued.app_key}</div>
                <div>app_secret: {issued.app_secret}</div>
              </div>
              <div className='rounded p-2 text-[13px]' style={{ background: '#FFF6E6', border: '1px solid #F0DDA8', color: '#6B4900' }}>
                <b>⚠️ 妥善保管</b>：SK 关闭此弹窗后<b>永远不可再查</b>，丢失需走运营方轮换流程（旧 SK 72h 内仍可并行使用）。
              </div>
              <div className='flex gap-2'>
                <Button size='sm' variant='outline' onClick={() => copy(issued.app_secret, 'app_secret')}>
                  <Copy className='w-3.5 h-3.5 mr-1' /> 复制 secret
                </Button>
                <Button size='sm' variant='outline' onClick={() => copy(issued.app_key, 'app_key')}>
                  <Copy className='w-3.5 h-3.5 mr-1' /> 复制 app_key
                </Button>
                <a
                  href={`${window.location.origin}/admin/8602-客户接入手册-v1.0.html`}
                  download="8602-客户接入手册-v1.0.html"
                  target="_blank"
                  rel="noopener"
                  className='inline-flex items-center gap-1 rounded-md border px-3 h-8 text-[14px] hover:bg-[#F8FAF9]'
                  style={{ borderColor: C.border, color: C.primary }}
                  title='下载后一并交付给客户'
                >
                  <FileDown className='w-3.5 h-3.5' /> 下载接入手册 v1.0
                </a>
              </div>
            </div>
          ) : (
            <div className='space-y-2'>
              <div className='text-[14px]' style={{ color: C.mid }}>租户 *（从下拉选择，避免手填 uuid 出错）</div>
              <Select value={tenantInput} onValueChange={(v) => setTenantInput(v)}>
                <SelectTrigger className='h-8 text-sm w-full'>
                  <SelectValue placeholder={tenantsLoading ? '加载租户中…' : '选择租户'} />
                </SelectTrigger>
                <SelectContent>
                  {tenants.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.name || "—"}（{t.code || "—"}）
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className='text-[13px]' style={{ color: C.light }}>
                已选 tenant_id：{tenantInput || '—'}；套餐默认 standard，可在开户时配置。
              </div>
            </div>
          )}
          <DialogFooter>
            {issued ? (
              <Button size='sm' style={{ background: C.primary }} onClick={() => { setIssueOpen(false); setIssued(null); setTenantInput(''); }}>完成</Button>
            ) : (
              <>
                <Button size='sm' variant='outline' onClick={() => { setIssueOpen(false); setTenantInput(''); }}>取消</Button>
                <Button size='sm' style={{ background: C.primary }} disabled={issuing} onClick={doIssue}>
                  {issuing && <Loader2 className='w-3.5 h-3.5 mr-1 animate-spin' />}确认签发
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 轮换 / 吊销 二次确认 */}
      <Dialog open={!!confirm} onOpenChange={(o) => { if (!o) setConfirm(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirm?.type === 'revoke' ? '吊销密钥' : '轮换密钥'}</DialogTitle>
            <DialogDescription>
              {confirm?.type === 'revoke'
                ? `确认吊销密钥 ${maskKey(confirm.key?.appKey || '')}？吊销后即时失效且不可恢复。`
                : `确认轮换密钥 ${maskKey(confirm?.key?.appKey || '')}？旧密钥 72 小时内仍有效。`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button size='sm' variant='outline' onClick={() => setConfirm(null)}>取消</Button>
            <Button size='sm'
              style={{ background: confirm?.type === 'revoke' ? '#B03A2E' : C.primary }}
              disabled={confirmBusy}
              onClick={confirm?.type === 'revoke' ? doRevoke : doRotate}>
              {confirmBusy && <Loader2 className='w-3.5 h-3.5 mr-1 animate-spin' />}
              {confirm?.type === 'revoke' ? '确认吊销' : '确认轮换'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
