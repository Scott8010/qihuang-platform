import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getIdentity } from "@/lib/api";
import { C } from "@/lib/types";

/** 客户工作台「使用说明」：替换首页那段开发口径声明，用大白话讲清能用什么、怎么找人。 */
export default function MyHelp() {
  const identity = getIdentity();
  const orgName = identity?.tenant_name || "你的机构";

  const sections = [
    {
      title: "这里能做什么",
      lines: [
        "数据看板：看本机构的套餐、调用量、积分余额、调用趋势和能力分布。",
        "使用情况：看本月配额用了多少、各能力的调用次数、消耗和费用明细。",
        "我的密钥：管理服务器对接用的密钥，可查看、轮换或停用。",
        "工单中心：需要开通能力、调整套餐或遇到问题时，在这里提交给平台。",
        "使用日志：查看每一次调用的详细信息，也可以导出成表格。",
        "联系客服：常见问题和联系方式都在这里。",
      ],
    },
    {
      title: "调用次数和积分是怎么算的",
      lines: [
        "套餐决定你能用哪些能力，以及本月包含多少次调用。",
        "调用 AI 能力会消耗积分；用完套餐赠送的积分后，可联系平台方补充。",
        "需要更多能力或调整套餐，不用改代码——在「工单中心」提交申请，或在微信里联系平台方，我们会为你的机构配置。",
      ],
    },
    {
      title: "对接时需要注意什么",
      lines: [
        "你的服务器用「密钥 + 签名」调用接口，密钥不要发给无关人员，也不要写进公开网页。",
        "如果发现密钥可能泄露，立刻到「我的密钥」停用并重新生成。",
        "使用日志只记录你自己的调用；平台自身运行 AI 的成本由平台承担，不计入你的账单。",
      ],
    },
    {
      title: "遇到问题怎么办",
      lines: [
        "接口报错、额度不够、能力未开通：先在「使用日志」看返回状态，再提交工单并附上时间点和接口路径，我们处理得更快。",
        "忘记密码：请联系平台方重置，暂时没有短信找回入口。",
      ],
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-xl p-5" style={{ background: C.soft, border: `1px solid ${C.border}` }}>
        <div className="text-[18px] font-bold" style={{ color: C.primary }}>使用说明</div>
        <div className="text-[13px] mt-1" style={{ color: C.mid }}>
          {orgName} · 这份说明用大白话讲清工作台怎么用，遇到不懂的地方随时找平台方。
        </div>
      </div>

      {sections.map((s, i) => (
        <Card key={s.title} className="border" style={{ borderColor: C.border }}>
          <CardHeader className="pb-2">
            <CardTitle className="text-[16px]" style={{ color: C.primary }}>{i + 1}. {s.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-[14px]" style={{ color: C.mid }}>
              {s.lines.map((line) => (
                <li key={line} className="flex gap-2 leading-relaxed">
                  <span style={{ color: C.light }}>•</span><span>{line}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
