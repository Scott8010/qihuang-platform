import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowRight, Clock3, Headset, Mail, MessageSquare, Phone, Ticket } from "lucide-react";
import { getIdentity } from "@/lib/api";
import { C } from "@/lib/types";

/**
 * MyContact — 机构端「联系客服」入口（mock 页）。
 * 平台客服的真实联系方式（企微 / 电话 / 邮箱 / 服务时间）配置后替换下面的占位内容即可，
 * 目前保持占位，避免把未确认的信息写成"官方联系方式"。
 */
export default function MyContact({ go }: { go: (p: string) => void }) {
  const identity = getIdentity();
  const orgName = identity?.tenant_name || "你的机构";

  const channels = [
    { icon: MessageSquare, label: "在线客服", value: "待平台配置", note: "配置后可在这里直接发起咨询" },
    { icon: Phone, label: "客服电话", value: "待平台配置", note: "配置后显示服务热线与接听时间" },
    { icon: Mail, label: "客服邮箱", value: "待平台配置", note: "配置后可发送问题与反馈材料" },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-xl p-5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div className="flex items-center gap-2 text-[18px] font-bold" style={{ color: C.primary }}>
          <Headset className="w-5 h-5" /> 联系客服
        </div>
        <div className="text-[14px] mt-2" style={{ color: C.mid }}>
          {orgName} · 客服联系方式由平台统一配置，配置完成后会显示在这里。
        </div>
      </div>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[16px]" style={{ color: C.primary }}>客服联系方式</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          {channels.map(({ icon: Icon, label, value, note }) => (
            <div key={label} className="rounded-xl p-4" style={{ background: C.bg, border: `1px solid ${C.border}` }}>
              <div className="flex items-center gap-2 text-[14px] font-medium" style={{ color: C.ink }}>
                <Icon className="w-4 h-4" style={{ color: C.primary }} /> {label}
              </div>
              <div className="mt-3 text-[17px] font-semibold" style={{ color: C.light }}>{value}</div>
              <div className="mt-2 text-[12px] leading-relaxed" style={{ color: C.light }}>{note}</div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="border" style={{ borderColor: C.border }}>
        <CardHeader className="pb-2">
          <CardTitle className="text-[16px]" style={{ color: C.primary }}>服务时间与响应</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-[14px]" style={{ color: C.mid }}>
            <Clock3 className="w-4 h-4" style={{ color: C.primary }} />
            服务时间：待平台配置
          </div>
          <div className="text-[13px] leading-relaxed" style={{ color: C.light }}>
            当前页面为客服入口占位。等平台确定客服渠道与服务时间后，这里会替换为真实信息；期间有紧急问题请先提交工单。
          </div>
          <Button size="sm" onClick={() => go("mytickets")} style={{ background: C.primary }}>
            <Ticket className="w-4 h-4 mr-1" /> 去工单中心提交问题 <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
