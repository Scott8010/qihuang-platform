import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BarChart3, Download, Sparkles } from "lucide-react";
import { C } from "@/lib/types";

/* ═══════════════════════════════════════════
   计费与套餐 — 按 KIMI 截图设计
   ═══════════════════════════════════════════ */

interface SceneRow {
  scene: string; calls: number; tokens: number; cost: number;
}

interface PlanCard {
  name: string; price: string; priceSub?: string;
  qps: string; calls: string; tokens: string;
  m3d: boolean; isMain?: boolean;
}

const SCENE_DATA: SceneRow[] = [
  { scene: "大健康", calls: 405100, tokens: 1820, cost: 69.2 },
  { scene: "医疗", calls: 45100, tokens: 640, cost: 24.3 },
  { scene: "培训", calls: 623000, tokens: 2960, cost: 88.9 },
];

const PLANS: PlanCard[] = [
  {
    name: "体验版", price: "免费 30 天", priceSub: "",
    qps: "2", calls: "调用 3,000 次/月", tokens: "Token 10 万",
    m3d: false,
  },
  {
    name: "标准版", price: "¥12,000/年", priceSub: "",
    qps: "10", calls: "调用 5 万次/月", tokens: "Token 200 万",
    m3d: false,
  },
  {
    name: "专业版", price: "¥39,800/年", priceSub: "",
    qps: "50", calls: "调用 50 万次/月", tokens: "Token 2,000 万",
    m3d: true, isMain: true,
  },
  {
    name: "私有化", price: "项目制", priceSub: "",
    qps: "不限", calls: "调用 不限", tokens: "Token 客户自采",
    m3d: true,
  },
];

const BILLS = [
  { id: "B-202607-001", tenant: "颐森汇健康集团", period: "2026-07", calls: "38.6万", tokens: "182万", amount: 69800, status: "已支付" },
  { id: "B-202607-002", tenant: "杏林在线教育学院", period: "2026-07", calls: "61.0万", tokens: "296万", amount: 39800, status: "逾期" },
  { id: "B-202607-003", tenant: "沪上云杉中医馆", period: "2026-07", calls: "4.2万", tokens: "64万", amount: 12000, status: "已支付" },
  { id: "B-202607-004", tenant: "滇南康养之家", period: "2026-07", calls: "1.9万", tokens: "40万", amount: 12000, status: "待支付" },
];

export default function Billing() {
  const [sceneUsage] = useState<SceneRow[]>(SCENE_DATA);
  const [plans] = useState<PlanCard[]>(PLANS);
  const [bills] = useState(BILLS);

  const kpiCards = [
    { label: "本月总调用", value: "107.3 万次", sub: "环比 +12.4%" },
    { label: "本月 Token 消耗", value: "5,420 万", sub: "共识四模型合计" },
    { label: "本月 LLM 成本", value: "¥5,472", sub: "预算阈值 80% 告警" },
    { label: "本月应收", value: "¥120,400", sub: "含 3D 增值 ¥8,600" },
  ];

  return (
    <div className="space-y-4">
      {/* KPI 卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {kpiCards.map((k) => (
          <Card key={k.label} className="border shadow-none" style={{ borderColor: C.border }}>
            <CardContent className="p-4">
              <div className="text-[12px] mb-1" style={{ color: C.light }}>{k.label}</div>
              <div className="text-[22px] font-bold" style={{ color: C.ink }}>{k.value}</div>
              <div className="text-[11px] mt-1" style={{ color: k.sub.includes("告警") ? "#B03A2E" : C.mid }}>
                {k.sub}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 分场景计量 + 套餐体系 */}
      <div className="grid grid-cols-2 gap-4">
        {/* 分场景计量 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4" style={{ color: C.primary }} />
              <span className="text-[14px] font-medium" style={{ color: C.ink }}>分场景计量（2026-07）</span>
            </div>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-[11px]" style={{ color: C.light }}>
                  <th className="pb-2 font-normal">场景</th>
                  <th className="pb-2 font-normal text-right">调用量</th>
                  <th className="pb-2 font-normal text-right">Token（万）</th>
                  <th className="pb-2 font-normal text-right">成本（¥）</th>
                </tr>
              </thead>
              <tbody>
                {sceneUsage.map((r) => (
                  <tr key={r.scene} className="border-t" style={{ borderColor: C.border }}>
                    <td className="py-2.5 font-medium" style={{ color: C.ink }}>{r.scene}</td>
                    <td className="py-2.5 text-right" style={{ color: C.mid }}>{r.calls.toLocaleString()}</td>
                    <td className="py-2.5 text-right" style={{ color: C.mid }}>{r.tokens.toLocaleString()}</td>
                    <td className="py-2.5 text-right" style={{ color: C.mid }}>{r.cost.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 p-2.5 rounded text-[11px] leading-relaxed" style={{ background: "#EAF2EE", color: C.mid }}>
              计量埋点在 API 网关完成，按「调用次数 + Token + 增值模块加载」三维度入账；岐黄三境 3D 模块单独计量（组件加载次数 / CDN 流量），未开通租户不产生费用。
            </div>
          </CardContent>
        </Card>

        {/* 套餐体系 */}
        <Card className="border shadow-none" style={{ borderColor: C.border }}>
          <CardContent className="p-4">
            <div className="text-[14px] font-medium mb-3" style={{ color: C.ink }}>
              套餐体系 <span className="text-[12px] font-normal" style={{ color: C.light }}>（features_json 开关下发）</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {plans.map((p) => (
                <div
                  key={p.name}
                  className="rounded-lg border p-3.5 relative"
                  style={{
                    borderColor: p.isMain ? "#C8A45D" : C.border,
                    background: p.isMain ? "#FBF4E4" : "#fff",
                  }}
                >
                  {p.isMain && (
                    <span className="absolute -top-2 left-3 text-[10px] px-1.5 py-0.5 rounded" style={{ background: "#C8A45D", color: "#fff" }}>
                      主力套餐
                    </span>
                  )}
                  <div className="text-[14px] font-semibold" style={{ color: C.primary }}>{p.name}</div>
                  <div className="text-[12px] mt-0.5" style={{ color: p.price.includes("免费") ? "#2E5A4C" : C.gold }}>
                    {p.price}
                  </div>
                  <div className="mt-2.5 space-y-1 text-[11.5px]" style={{ color: C.mid }}>
                    <div>QPS {p.qps}</div>
                    <div>{p.calls}</div>
                    <div>{p.tokens}</div>
                    <div className="flex items-center gap-1">
                      {p.m3d ? (
                        <>
                          <Sparkles className="w-3 h-3" style={{ color: C.gold }} />
                          <span style={{ color: C.gold }}>含岐黄三境 3D</span>
                        </>
                      ) : (
                        <span style={{ color: C.light }}>— 无 3D 模块</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-3 text-[11px] leading-relaxed" style={{ color: C.light }}>
              套餐与 module_3d 开关写入租户 features_json，网关鉴权时随 Token / 签名响应下发，前端按开关渲染入口。
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 账单管理 */}
      <Card className="border shadow-none" style={{ borderColor: C.border }}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[14px] font-medium" style={{ color: C.ink }}>账单管理（2026-07 账期）</span>
            <Button variant="outline" size="sm" style={{ borderColor: C.border, color: C.primary }}>
              <Download className="w-3.5 h-3.5 mr-1" /> 导出对账单
            </Button>
          </div>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px]" style={{ color: C.light }}>
                {["账单号", "租户", "账期", "调用量", "Token", "金额", "状态"].map((h) => (
                  <th key={h} className="pb-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bills.map((b) => (
                <tr key={b.id} className="border-t hover:bg-[#F8FAF9]" style={{ borderColor: C.border }}>
                  <td className="py-2.5 font-mono text-[12px]" style={{ color: C.mid }}>{b.id}</td>
                  <td className="py-2.5" style={{ color: C.ink }}>{b.tenant}</td>
                  <td className="py-2.5" style={{ color: C.mid }}>{b.period}</td>
                  <td className="py-2.5" style={{ color: C.mid }}>{b.calls}</td>
                  <td className="py-2.5" style={{ color: C.mid }}>{b.tokens}</td>
                  <td className="py-2.5 font-medium" style={{ color: C.ink }}>¥{b.amount.toLocaleString()}</td>
                  <td className="py-2.5">
                    <span
                      className="text-[11px] px-2 py-0.5 rounded"
                      style={{
                        color: b.status === "已支付" ? "#2E5A4C" : b.status === "逾期" ? "#B03A2E" : "#8A6A1F",
                        background: b.status === "已支付" ? "#EAF2EE" : b.status === "逾期" ? "#FDECEA" : "#FBF4E4",
                      }}
                    >
                      {b.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
