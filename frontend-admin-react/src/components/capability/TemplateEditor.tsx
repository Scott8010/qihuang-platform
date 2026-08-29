import { useRef, useState } from "react";
import {
  Plus, Trash2, ChevronUp, ChevronDown, Upload,
  MapPin, FileText,
} from "lucide-react";
import { C } from "@/lib/types";

/* ═══════════════════════════════════════════
   能力中心 · 可视化模板编辑器（老黄 2026-08-21 拍板）
   目标：运营不再面对 JSON，直接用「客户能理解」的表单编辑模板。

   按 kind 路由：
     script        → 话术脚本（场景 + 步骤话术 + 要点）
     knowledge     → 知识课件（章节型 / 穴位型两种）
     project       → 项目 SOP（流程 + 禁忌 + 善后）
     product       → 产品培训（成分/用法/卖点/禁忌）
     questionnaire → 问卷草稿（字段清单）
     其他（herb/formula/…）→ JSON 高级模式（兜底）
   ═══════════════════════════════════════════ */

export interface TemplateEditorProps {
  kind: string;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

/* ─────────────── 类型安全取值工具 ─────────────── */
const asStr = (v: unknown, fallback = ""): string =>
  typeof v === "string" ? v : fallback;
const asNum = (v: unknown): number =>
  typeof v === "number" && Number.isFinite(v) ? v : 0;
const asStrArr = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
const asObjArr = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x)) : [];

/* ─────────────── 共享小部件 ─────────────── */

function FieldLabel({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="text-[13.5px] font-medium mb-1 flex items-center gap-1.5" style={{ color: C.mid }}>
      {text}
      {hint && <span className="text-[12px] font-normal" style={{ color: C.light }}>{hint}</span>}
    </div>
  );
}

const inputCls = "w-full text-[14.5px] rounded-md border px-2.5 py-1.5 outline-none focus:border-[#2E5A4C] transition-colors bg-white";
const inputStyle = { borderColor: C.border, color: C.ink } as const;

/** 字符串列表编辑器（tips / ingredients / cautions / sales_points / aftercare…） */
function StrListEditor({
  label, hint, items, onChange, tone = "green",
}: {
  label: string; hint?: string; items: string[];
  onChange: (next: string[]) => void; tone?: "green" | "gold" | "red";
}) {
  const [draft, setDraft] = useState("");
  const toneStyle = tone === "gold"
    ? { bg: "#FBF4E4", color: "#8A6A1F" }
    : tone === "red"
      ? { bg: "#FDECEA", color: "#B03A2E" }
      : { bg: C.soft, color: C.primary };
  const add = () => {
    const t = draft.trim();
    if (!t) return;
    onChange([...items, t]);
    setDraft("");
  };
  return (
    <div>
      <FieldLabel text={label} hint={hint} />
      <div className="flex flex-wrap gap-1 mb-1.5">
        {items.map((s, i) => (
          <span key={`${s}-${i}`} className="inline-flex items-center gap-1 text-[13.5px] pl-2 pr-1 py-0.5 rounded-full"
            style={{ background: toneStyle.bg, color: toneStyle.color }}>
            {s}
            <button type="button" className="w-4 h-4 rounded-full flex items-center justify-center hover:bg-black/10"
              onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="删除">
              <Trash2 className="w-2.5 h-2.5" />
            </button>
          </span>
        ))}
        {items.length === 0 && <span className="text-[13px]" style={{ color: C.light }}>（暂无，在下方输入后添加）</span>}
      </div>
      <div className="flex gap-1.5">
        <input value={draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={`输入一条${label.replace(/（.*）/, "")}，回车添加`}
          className={inputCls} style={inputStyle} />
        <button type="button" onClick={add}
          className="shrink-0 inline-flex items-center gap-1 text-[13.5px] px-2.5 rounded-md border transition-colors hover:opacity-80"
          style={{ borderColor: C.border, color: C.primary, background: C.soft }}>
          <Plus className="w-3 h-3" />添加
        </button>
      </div>
    </div>
  );
}

/** 步骤列表编辑器（script.steps / project.flow：[{step,name,script}]） */
function StepListEditor({
  label, stepNameLabel, scriptLabel, items, onChange,
}: {
  label: string; stepNameLabel: string; scriptLabel: string;
  items: Record<string, unknown>[]; onChange: (next: Record<string, unknown>[]) => void;
}) {
  const patch = (i: number, patchObj: Record<string, unknown>) =>
    onChange(items.map((x, j) => (j === i ? { ...x, ...patchObj } : x)));
  const move = (i: number, d: -1 | 1) => {
    const t = i + d;
    if (t < 0 || t >= items.length) return;
    const next = [...items];
    [next[i], next[t]] = [next[t], next[i]];
    onChange(next);
  };
  return (
    <div>
      <FieldLabel text={`${label}（${items.length} 步）`} hint="上下箭头可调整顺序" />
      <div className="space-y-1.5">
        {items.map((s, i) => (
          <div key={i} className="rounded-md border p-2 space-y-1.5" style={{ borderColor: C.border, background: "#FCFCFA" }}>
            <div className="flex items-center gap-2">
              <span className="shrink-0 w-5 h-5 rounded-full text-[12.5px] font-bold flex items-center justify-center"
                style={{ background: C.primary, color: "#fff" }}>{i + 1}</span>
              <input value={asStr(s.name)} onChange={(e) => patch(i, { name: e.target.value, step: i + 1 })}
                placeholder={stepNameLabel} className={inputCls} style={inputStyle} />
              <div className="shrink-0 flex items-center gap-0.5">
                <button type="button" onClick={() => move(i, -1)} disabled={i === 0}
                  className="w-6 h-6 rounded flex items-center justify-center hover:bg-black/5 disabled:opacity-25" aria-label="上移">
                  <ChevronUp className="w-3.5 h-3.5" style={{ color: C.mid }} />
                </button>
                <button type="button" onClick={() => move(i, 1)} disabled={i === items.length - 1}
                  className="w-6 h-6 rounded flex items-center justify-center hover:bg-black/5 disabled:opacity-25" aria-label="下移">
                  <ChevronDown className="w-3.5 h-3.5" style={{ color: C.mid }} />
                </button>
                <button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))}
                  className="w-6 h-6 rounded flex items-center justify-center hover:bg-[#FDECEA]" aria-label="删除步骤">
                  <Trash2 className="w-3.5 h-3.5" style={{ color: "#B03A2E" }} />
                </button>
              </div>
            </div>
            <textarea value={asStr(s.script)} onChange={(e) => patch(i, { script: e.target.value })}
              placeholder={scriptLabel} rows={2}
              className={`${inputCls} leading-relaxed resize-y`} style={inputStyle} />
          </div>
        ))}
        <button type="button" onClick={() => onChange([...items, { step: items.length + 1, name: "", script: "" }])}
          className="w-full inline-flex items-center justify-center gap-1 text-[14px] py-1.5 rounded-md border border-dashed transition-colors hover:bg-[#F8FAF9]"
          style={{ borderColor: C.border, color: C.primary }}>
          <Plus className="w-3.5 h-3.5" />添加一步
        </button>
      </div>
    </div>
  );
}

/* ─────────────── ① 话术脚本编辑器 ─────────────── */
const SCRIPT_SCENES: Array<{ value: string; label: string }> = [
  { value: "reception", label: "进店接待" },
  { value: "recommend", label: "产品推荐" },
  { value: "objection", label: "异议处理" },
  { value: "close", label: "促成下单" },
  { value: "followup", label: "跟进回访" },
  { value: "other", label: "其他场景" },
];

function ScriptEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const scene = asStr(value.scene, "reception");
  const steps = asObjArr(value.steps);
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text="适用场景" hint="这个话术用在哪个环节" />
        <div className="flex flex-wrap gap-1.5">
          {SCRIPT_SCENES.map((s) => (
            <button key={s.value} type="button"
              onClick={() => onChange({ ...value, scene: s.value })}
              className="text-[13.5px] px-2.5 py-1 rounded-full border transition-colors"
              style={scene === s.value
                ? { background: C.primary, color: "#fff", borderColor: C.primary }
                : { background: "#fff", color: C.mid, borderColor: C.border }}>
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <StepListEditor label="话术步骤" stepNameLabel="步骤名称，如：迎宾破冰" scriptLabel="这一步对顾客说的话（店员照着念即可）"
        items={steps} onChange={(next) => onChange({ ...value, steps: next })} />
      <StrListEditor label="话术要点" hint="店员要记住的分寸，如：先倾听后推荐"
        items={asStrArr(value.tips)} onChange={(next) => onChange({ ...value, tips: next })} />
    </div>
  );
}

/* ─────────────── ② 知识课件编辑器（章节型 / 穴位型） ─────────────── */
function KnowledgeEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const mode: "points" | "sections" = Array.isArray(value.points) && asObjArr(value.points).length > 0 ? "points" : "sections";
  const switchMode = (m: "points" | "sections") => {
    if (m === mode) return;
    if (m === "points") onChange({ category: asStr(value.category), points: [], common_cautions: asStrArr(value.common_cautions) });
    else onChange({ category: asStr(value.category), content: [{ title: "", body: "" }], talk_script: asStr(value.talk_script) });
  };
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text="课件形式" hint="按内容类型二选一" />
        <div className="flex gap-1.5">
          <button type="button" onClick={() => switchMode("sections")}
            className="inline-flex items-center gap-1 text-[13.5px] px-2.5 py-1 rounded-full border transition-colors"
            style={mode === "sections" ? { background: C.primary, color: "#fff", borderColor: C.primary } : { background: "#fff", color: C.mid, borderColor: C.border }}>
            <FileText className="w-3 h-3" />章节课件（讲义式）
          </button>
          <button type="button" onClick={() => switchMode("points")}
            className="inline-flex items-center gap-1 text-[13.5px] px-2.5 py-1 rounded-full border transition-colors"
            style={mode === "points" ? { background: C.primary, color: "#fff", borderColor: C.primary } : { background: "#fff", color: C.mid, borderColor: C.border }}>
            <MapPin className="w-3 h-3" />穴位课件（一穴一卡）
          </button>
        </div>
      </div>
      <div>
        <FieldLabel text="主题分类" hint="如：经络穴位 / 艾灸取穴" />
        <input value={asStr(value.category)} onChange={(e) => onChange({ ...value, category: e.target.value })}
          placeholder="如：经络穴位" className={inputCls} style={inputStyle} />
      </div>
      {mode === "sections" ? (
        <SectionsEditor value={value} onChange={onChange} />
      ) : (
        <PointsEditor value={value} onChange={onChange} />
      )}
    </div>
  );
}

/** 章节型：content:[{title,body}] + talk_script */
function SectionsEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const items = asObjArr(value.content);
  const patch = (i: number, p: Record<string, unknown>) =>
    onChange({ ...value, content: items.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text={`知识章节（${items.length} 节）`} hint="每节一个小标题 + 正文" />
        <div className="space-y-1.5">
          {items.map((s, i) => (
            <div key={i} className="rounded-md border p-2 space-y-1.5" style={{ borderColor: C.border, background: "#FCFCFA" }}>
              <div className="flex items-center gap-2">
                <span className="shrink-0 w-5 h-5 rounded-full text-[12.5px] font-bold flex items-center justify-center"
                  style={{ background: C.primary, color: "#fff" }}>{i + 1}</span>
                <input value={asStr(s.title)} onChange={(e) => patch(i, { title: e.target.value })}
                  placeholder="小标题，如：艾灸适用情况" className={inputCls} style={inputStyle} />
                <button type="button" onClick={() => onChange({ ...value, content: items.filter((_, j) => j !== i) })}
                  className="shrink-0 w-6 h-6 rounded flex items-center justify-center hover:bg-[#FDECEA]" aria-label="删除章节">
                  <Trash2 className="w-3.5 h-3.5" style={{ color: "#B03A2E" }} />
                </button>
              </div>
              <textarea value={asStr(s.body)} onChange={(e) => patch(i, { body: e.target.value })}
                placeholder="这一节的正文内容" rows={3}
                className={`${inputCls} leading-relaxed resize-y`} style={inputStyle} />
            </div>
          ))}
          <button type="button" onClick={() => onChange({ ...value, content: [...items, { title: "", body: "" }] })}
            className="w-full inline-flex items-center justify-center gap-1 text-[14px] py-1.5 rounded-md border border-dashed transition-colors hover:bg-[#F8FAF9]"
            style={{ borderColor: C.border, color: C.primary }}>
            <Plus className="w-3.5 h-3.5" />添加一节
          </button>
        </div>
      </div>
      <div>
        <FieldLabel text="店员讲解话术（可选）" hint="顾客在场时店员怎么讲这个课件" />
        <textarea value={asStr(value.talk_script)} onChange={(e) => onChange({ ...value, talk_script: e.target.value })}
          placeholder="如：艾灸是传统养生保健方法，适合日常调理…" rows={2}
          className={`${inputCls} italic resize-y`} style={{ background: "#F2EFEA", borderColor: "#E3DCCB", color: "#5B4F35" }} />
      </div>
    </div>
  );
}

/** 穴位型：points:[{name,meridian,location,effect,moxa_method,cautions,talk_script}] + common_cautions */
function PointsEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const points = asObjArr(value.points);
  const patch = (i: number, p: Record<string, unknown>) =>
    onChange({ ...value, points: points.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text={`穴位卡片（${points.length} 个）`} hint="每个穴位一张卡：定位/功效/灸法/禁忌/话术" />
        <div className="space-y-1.5">
          {points.map((p, i) => (
            <div key={i} className="rounded-md border p-2 space-y-1.5" style={{ borderColor: C.border, background: "#FCFCFA" }}>
              <div className="flex items-center gap-2">
                <input value={asStr(p.name)} onChange={(e) => patch(i, { name: e.target.value })}
                  placeholder="穴位名，如：足三里" className={`${inputCls} font-semibold`} style={inputStyle} />
                <input value={asStr(p.meridian)} onChange={(e) => patch(i, { meridian: e.target.value })}
                  placeholder="所属经络" className={`${inputCls} shrink-0`} style={{ ...inputStyle, width: 130 }} />
                <button type="button" onClick={() => onChange({ ...value, points: points.filter((_, j) => j !== i) })}
                  className="shrink-0 w-6 h-6 rounded flex items-center justify-center hover:bg-[#FDECEA]" aria-label="删除穴位">
                  <Trash2 className="w-3.5 h-3.5" style={{ color: "#B03A2E" }} />
                </button>
              </div>
              <input value={asStr(p.location)} onChange={(e) => patch(i, { location: e.target.value })}
                placeholder="定位（怎么找到它）" className={inputCls} style={inputStyle} />
              <input value={asStr(p.effect)} onChange={(e) => patch(i, { effect: e.target.value })}
                placeholder="功效（调理什么）" className={inputCls} style={inputStyle} />
              <input value={asStr(p.moxa_method)} onChange={(e) => patch(i, { moxa_method: e.target.value })}
                placeholder="灸法/按揉方法（做多久、多久一次）" className={inputCls} style={inputStyle} />
              <StrListEditor label="该穴位禁忌" items={asStrArr(p.cautions)}
                onChange={(next) => patch(i, { cautions: next })} tone="red" />
              <textarea value={asStr(p.talk_script)} onChange={(e) => patch(i, { talk_script: e.target.value })}
                placeholder="给顾客介绍这个穴位时的话术" rows={2}
                className={`${inputCls} italic resize-y`} style={{ background: "#F2EFEA", borderColor: "#E3DCCB", color: "#5B4F35" }} />
            </div>
          ))}
          <button type="button" onClick={() => onChange({ ...value, points: [...points, { name: "", meridian: "", location: "", effect: "", moxa_method: "", cautions: [], talk_script: "" }] })}
            className="w-full inline-flex items-center justify-center gap-1 text-[14px] py-1.5 rounded-md border border-dashed transition-colors hover:bg-[#F8FAF9]"
            style={{ borderColor: C.border, color: C.primary }}>
            <Plus className="w-3.5 h-3.5" />添加一个穴位
          </button>
        </div>
      </div>
      <StrListEditor label="通用注意事项" hint="所有穴位通用的红线，如：不替代医疗"
        items={asStrArr(value.common_cautions)}
        onChange={(next) => onChange({ ...value, common_cautions: next })} tone="gold" />
    </div>
  );
}

/* ─────────────── ③ 项目 SOP 编辑器 ─────────────── */
function ProjectEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  return (
    <div className="space-y-3.5">
      <div className="flex gap-2">
        <div className="flex-1">
          <FieldLabel text="项目名称 / 类型" hint="如：拔罐调理" />
          <input value={asStr(value.type)} onChange={(e) => onChange({ ...value, type: e.target.value })}
            placeholder="如：service（服务项目）" className={inputCls} style={inputStyle} />
        </div>
        <div style={{ width: 130 }}>
          <FieldLabel text="时长（分钟）" />
          <input type="number" min={0} value={asNum(value.duration_min) || ""}
            onChange={(e) => onChange({ ...value, duration_min: Number(e.target.value) || 0 })}
            placeholder="30" className={inputCls} style={inputStyle} />
        </div>
      </div>
      <StepListEditor label="服务流程" stepNameLabel="步骤名称，如：问询评估" scriptLabel="这一步的操作说明 / 话术"
        items={asObjArr(value.flow)} onChange={(next) => onChange({ ...value, flow: next })} />
      <StrListEditor label="禁忌 / 注意事项" hint="什么人不能做、操作红线"
        items={asStrArr(value.cautions)} onChange={(next) => onChange({ ...value, cautions: next })} tone="red" />
      <StrListEditor label="善后建议" hint="做完之后叮嘱顾客什么"
        items={asStrArr(value.aftercare)} onChange={(next) => onChange({ ...value, aftercare: next })} />
    </div>
  );
}

/* ─────────────── ④ 产品培训编辑器 ─────────────── */
function ProductEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text="品类" hint="如：tea 养生茶 / soup 汤品" />
        <input value={asStr(value.type)} onChange={(e) => onChange({ ...value, type: e.target.value })}
          placeholder="如：tea" className={inputCls} style={inputStyle} />
      </div>
      <div>
        <FieldLabel text="产品定位（一句话）" hint="给顾客的第一印象" />
        <input value={asStr(value.positioning)} onChange={(e) => onChange({ ...value, positioning: e.target.value })}
          placeholder="如：清肝明目，适合长期用眼的日常调理" className={inputCls} style={inputStyle} />
      </div>
      <div>
        <FieldLabel text="用法用量" />
        <input value={asStr(value.usage)} onChange={(e) => onChange({ ...value, usage: e.target.value })}
          placeholder="如：每日 1 包，85°C 热水冲泡 3-5 分钟" className={inputCls} style={inputStyle} />
      </div>
      <div>
        <FieldLabel text="适宜人群" />
        <input value={asStr(value.suitable)} onChange={(e) => onChange({ ...value, suitable: e.target.value })}
          placeholder="如：适合大部分成年人群日常保健" className={inputCls} style={inputStyle} />
      </div>
      <StrListEditor label="配方 / 成分" items={asStrArr(value.ingredients)}
        onChange={(next) => onChange({ ...value, ingredients: next })} />
      <StrListEditor label="销售卖点" items={asStrArr(value.sales_points)}
        onChange={(next) => onChange({ ...value, sales_points: next })} tone="gold" />
      <StrListEditor label="注意事项" items={asStrArr(value.cautions)}
        onChange={(next) => onChange({ ...value, cautions: next })} tone="red" />
    </div>
  );
}

/* ─────────────── ⑤ 问卷草稿编辑器 ─────────────── */
const FIELD_TYPES: Array<{ value: string; label: string }> = [
  { value: "text", label: "单行文本" },
  { value: "textarea", label: "多行文本" },
  { value: "number", label: "数字" },
  { value: "select", label: "单选" },
  { value: "boolean", label: "是/否" },
  { value: "date", label: "日期" },
];

function QuestionnaireEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const schema = (value.schema && typeof value.schema === "object" && !Array.isArray(value.schema))
    ? value.schema as Record<string, unknown> : {};
  const fields = asObjArr(schema.fields);
  const setSchema = (p: Record<string, unknown>) => onChange({ ...value, schema: { ...schema, ...p } });
  const patchField = (i: number, p: Record<string, unknown>) =>
    setSchema({ fields: fields.map((x, j) => (j === i ? { ...x, ...p } : x)) });
  return (
    <div className="space-y-3.5">
      <div>
        <FieldLabel text="问卷名称" />
        <input value={asStr(schema.title)} onChange={(e) => setSchema({ title: e.target.value })}
          placeholder="如：进店顾客体质调研" className={inputCls} style={inputStyle} />
      </div>
      <div>
        <FieldLabel text="问卷说明" hint="填表人开头会看到的话" />
        <textarea value={asStr(schema.description)} onChange={(e) => setSchema({ description: e.target.value })}
          placeholder="如：为了更好地为您服务，请花 1 分钟填写…" rows={2}
          className={`${inputCls} resize-y`} style={inputStyle} />
      </div>
      <div>
        <FieldLabel text={`问题清单（${fields.length} 项）`} hint="每项一个标签 + 题型 + 是否必填" />
        <div className="space-y-1.5">
          {fields.map((f, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md border px-2 py-1.5" style={{ borderColor: C.border, background: "#FCFCFA" }}>
              <span className="shrink-0 text-[12.5px] font-mono w-5 text-center" style={{ color: C.light }}>Q{i + 1}</span>
              <input value={asStr(f.label)} onChange={(e) => patchField(i, { label: e.target.value })}
                placeholder="问题，如：您平时睡眠如何？" className={`${inputCls} flex-1`} style={inputStyle} />
              <select value={asStr(f.type, "text")} onChange={(e) => patchField(i, { type: e.target.value })}
                className="text-[13.5px] rounded-md border px-1.5 py-1 outline-none bg-white shrink-0" style={{ borderColor: C.border, color: C.mid }}>
                {FIELD_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
              <label className="shrink-0 inline-flex items-center gap-1 text-[13px] cursor-pointer" style={{ color: C.mid }}>
                <input type="checkbox" checked={!!f.required} onChange={(e) => patchField(i, { required: e.target.checked })} />
                必填
              </label>
              <button type="button" onClick={() => setSchema({ fields: fields.filter((_, j) => j !== i) })}
                className="shrink-0 w-6 h-6 rounded flex items-center justify-center hover:bg-[#FDECEA]" aria-label="删除问题">
                <Trash2 className="w-3.5 h-3.5" style={{ color: "#B03A2E" }} />
              </button>
            </div>
          ))}
          <button type="button" onClick={() => setSchema({ fields: [...fields, { label: "", type: "text", required: false }] })}
            className="w-full inline-flex items-center justify-center gap-1 text-[14px] py-1.5 rounded-md border border-dashed transition-colors hover:bg-[#F8FAF9]"
            style={{ borderColor: C.border, color: C.primary }}>
            <Plus className="w-3.5 h-3.5" />添加一个问题
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────── ⑥ JSON 高级模式（herb/formula/… 兜底） ─────────────── */
function JsonFallbackEditor({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [err, setErr] = useState("");
  const apply = () => {
    try {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("顶层必须是对象");
      onChange(parsed);
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "JSON 不合法");
    }
  };
  return (
    <div className="space-y-2">
      <div className="text-[13px] rounded-md px-2.5 py-1.5" style={{ background: "#FBF4E4", color: "#8A6A1F" }}>
        此类型暂无表单编辑器，可先在左上角切换类型，或直接编辑 JSON（改完点「应用」）。
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10}
        className="w-full text-[14px] font-mono rounded-md border p-2 outline-none resize-y"
        style={{ borderColor: err ? "#B03A2E" : C.border, background: "#FCFCFA" }} />
      <div className="flex items-center gap-2">
        <button type="button" onClick={apply}
          className="text-[13.5px] px-2.5 py-1 rounded-md" style={{ background: C.primary, color: "#fff" }}>
          应用 JSON
        </button>
        {err && <span className="text-[13px]" style={{ color: "#B03A2E" }}>⚠ {err}</span>}
      </div>
    </div>
  );
}

/* ─────────────── 主入口：按 kind 路由 ─────────────── */
export default function TemplateEditor({ kind, value, onChange }: TemplateEditorProps) {
  switch (kind) {
    case "script": return <ScriptEditor value={value} onChange={onChange} />;
    case "knowledge": return <KnowledgeEditor value={value} onChange={onChange} />;
    case "project": return <ProjectEditor value={value} onChange={onChange} />;
    case "product": return <ProductEditor value={value} onChange={onChange} />;
    case "questionnaire": return <QuestionnaireEditor value={value} onChange={onChange} />;
    default: return <JsonFallbackEditor value={value} onChange={onChange} />;
  }
}

/* ═══════════════════════════════════════════
   文本导入器：txt / md / docx → 结构化模板
   老黄诉求："用现成的文本上传再修改"
   策略：docx 用 mammoth 抽纯文本，然后按 kind 启发式解析；
        解析不全没关系——塞进合理结构，用户在编辑器里再改。
   ═══════════════════════════════════════════ */

export function TextImporter({
  kind, onImport,
}: {
  kind: string;
  onImport: (parsed: Record<string, unknown>) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const handleFile = async (file: File) => {
    setBusy(true);
    setNote("");
    try {
      let text = "";
      if (/\.docx$/i.test(file.name)) {
        const mod = await import("mammoth");
        const mammoth = ((mod as unknown as { default?: unknown }).default ?? mod) as {
          extractRawText: (o: { arrayBuffer: ArrayBuffer }) => Promise<{ value: string }>;
        };
        const arrayBuffer = await file.arrayBuffer();
        const r = await mammoth.extractRawText({ arrayBuffer });
        text = r.value;
      } else {
        text = await file.text();
      }
      const parsed = parseImportedText(kind, text, file.name.replace(/\.[^.]+$/, ""));
      onImport(parsed);
      setNote(`已导入「${file.name}」，请检查并补充细节`);
    } catch (e) {
      setNote(`导入失败：${e instanceof Error ? e.message : "文件读取异常"}`);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="rounded-md border border-dashed p-2.5" style={{ borderColor: C.border, background: "#F8FAF9" }}>
      <div className="flex items-center gap-2 flex-wrap">
        <Upload className="w-3.5 h-3.5" style={{ color: C.accent }} />
        <span className="text-[13.5px]" style={{ color: C.mid }}>
          <b>从现成文档导入</b>：支持 .txt / .md / .docx（Word 文档），导入后可直接修改
        </span>
        <input ref={inputRef} type="file" accept=".txt,.md,.docx" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
        <button type="button" disabled={busy} onClick={() => inputRef.current?.click()}
          className="ml-auto text-[13.5px] px-2.5 py-1 rounded-md inline-flex items-center gap-1 disabled:opacity-50"
          style={{ background: C.soft, color: C.primary }}>
          {busy ? "解析中…" : "选择文件"}
        </button>
      </div>
      {note && <div className="text-[13px] mt-1.5" style={{ color: C.primary }}>{note}</div>}
    </div>
  );
}

/* ─────────────── 导入文本启发式解析 ─────────────── */

/** 行按「标题/正文」粗切：markdown 标题、加粗短行、短行无标点 → 标题 */
function splitSections(text: string): Array<{ title: string; body: string }> {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const out: Array<{ title: string; body: string }> = [];
  let cur: { title: string; body: string[] } | null = null;
  for (const line of lines) {
    const isMd = /^#{1,6}\s+/.test(line);
    const cleaned = line.replace(/^#{1,6}\s+/, "").replace(/\*\*/g, "").replace(/^【|】$/g, "");
    const isTitle = isMd || (cleaned.length <= 20 && !/[。；，,.!?？!]/.test(cleaned) && cleaned.length > 1);
    if (isTitle) {
      if (cur) out.push({ title: cur.title, body: cur.body.join("\n") });
      cur = { title: cleaned, body: [] };
    } else if (cur) {
      cur.body.push(line.replace(/\*\*/g, ""));
    } else {
      cur = { title: "", body: [line.replace(/\*\*/g, "")] };
    }
  }
  if (cur) out.push({ title: cur.title, body: cur.body.join("\n") });
  return out.filter((s) => s.title || s.body);
}

/** 解析「1. 步骤名：话术」/「一、步骤名：话术」样式的行 */
function parseSteps(text: string): Array<{ step: number; name: string; script: string }> {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const steps: Array<{ step: number; name: string; script: string }> = [];
  for (const line of lines) {
    const m = line.match(/^(?:第?[一二三四五六七八九十\d]+\d*[步、.．)]、?]?)\s*(.*)$/);
    const body = (m ? m[1] : line).replace(/\*\*/g, "");
    const sep = body.match(/^(.{1,25})[：:](.+)$/);
    if (sep) {
      steps.push({ step: steps.length + 1, name: sep[1].trim(), script: sep[2].trim() });
    } else if (steps.length > 0 && !/[。；]/.test(body)) {
      steps[steps.length - 1].script += ` ${body}`;
    } else if (body) {
      steps.push({ step: steps.length + 1, name: `第 ${steps.length + 1} 步`, script: body });
    }
  }
  return steps;
}

/** 从文本里抓「标签：值」KV（成分/用法/适宜/注意/卖点…） */
function parseKV(text: string): Record<string, string[]> {
  const kv: Record<string, string[]> = {};
  for (const raw of text.split(/\r?\n/)) {
    const m = raw.trim().match(/^(.{1,12})[：:](.+)$/);
    if (!m) continue;
    kv[m[1].trim()] = [m[2].trim().replace(/\*\*/g, "")];
  }
  return kv;
}

const pick = (kv: Record<string, string[]>, keys: string[]): string => {
  for (const [label, vals] of Object.entries(kv)) {
    if (keys.some((x) => label.includes(x))) return vals[0] || "";
  }
  return "";
};

function parseImportedText(kind: string, text: string, fileName: string): Record<string, unknown> {
  // 通用兜底：章节型内容（任何 kind 都能承接全文，用户再改）
  const fallback = (): Record<string, unknown> => ({
    category: fileName,
    content: splitSections(text).map((s) => ({ title: s.title || fileName, body: s.body })),
  });

  if (kind === "script" || kind === "project") {
    const sections = splitSections(text);
    // 找正文最长的段当步骤主体；「提示/注意/禁忌」段单拎
    const tipsSections = sections.filter((s) => /提示|要点|注意|技巧/.test(s.title));
    const mainSections = sections.filter((s) => !tipsSections.includes(s));
    const mainText = (mainSections.length > 0 ? mainSections : sections)
      .map((s) => (s.title ? `${s.title}：${s.body}` : s.body)).join("\n");
    const steps = parseSteps(mainText);
    if (steps.length === 0) return fallback();
    const tips = tipsSections.flatMap((s) => s.body.split(/\n|[；;]/).map((x) => x.trim()).filter(Boolean));
    if (kind === "script") {
      return { scene: "other", steps, tips };
    }
    return {
      type: "service",
      flow: steps,
      cautions: [],
      ...(tips.length ? { aftercare: tips } : {}),
    };
  }

  if (kind === "knowledge") {
    const sections = splitSections(text);
    // 穴位特征：标题行含「穴」或出现定位/功效字样
    const pointLike = sections.some((s) => /穴/.test(s.title)) ||
      /定位|功效|经络/.test(text);
    if (pointLike) {
      const points = sections.filter((s) => s.title).map((s) => ({
        name: s.title.replace(/穴$/, ""),
        meridian: "",
        location: (s.body.match(/定位[：:]?(.+)/)?.[1] || "").trim(),
        effect: (s.body.match(/功效[：:]?(.+)/)?.[1] || "").trim(),
        moxa_method: (s.body.match(/灸法|操作[：:]?(.+)/)?.[1] || "").trim(),
        cautions: [] as string[],
        talk_script: "",
      }));
      if (points.length > 0) {
        return { category: fileName, points, common_cautions: [] };
      }
    }
    return { category: fileName, content: sections.map((s) => ({ title: s.title || fileName, body: s.body })), talk_script: "" };
  }

  if (kind === "product") {
    const kv = parseKV(text);
    const result: Record<string, unknown> = { type: "" };
    const positioning = pick(kv, ["定位", "定位人群", "卖点"]);
    if (positioning) result.positioning = positioning;
    const usage = pick(kv, ["用法", "冲泡", "食用方法"]);
    if (usage) result.usage = usage;
    const suitable = pick(kv, ["适宜", "适合"]);
    if (suitable) result.suitable = suitable;
    const ingLine = pick(kv, ["成分", "配料", "配方"]);
    if (ingLine) result.ingredients = ingLine.split(/[、,，;；\s]+/).filter(Boolean);
    const cautionLine = pick(kv, ["注意", "禁忌", "慎用"]);
    if (cautionLine) result.cautions = cautionLine.split(/[、,，;；\s]+/).filter(Boolean);
    const salesLine = pick(kv, ["卖点"]);
    if (salesLine) result.sales_points = salesLine.split(/[、,，;；]+/).filter(Boolean);
    if (Object.keys(result).length <= 1) return fallback();
    return result;
  }

  if (kind === "questionnaire") {
    const lines = text.split(/\r?\n/).map((l) => l.trim().replace(/^\d+[.、)]\s*/, "").replace(/[?？]$/, "")).filter(Boolean);
    const fields = lines.filter((l) => l.length >= 2 && l.length <= 40).map((l) => {
      const type = /[与否|是否]/.test(l) ? "boolean" : /多少|几|年龄|电话/.test(l) ? "text" : "text";
      return { label: l, type, required: false };
    });
    return { schema: { title: fileName, description: "", fields: fields.slice(0, 30) } };
  }

  return fallback();
}

/* ─────────────── 新建模板的默认值（按 kind 给一个可编辑的起点） ─────────────── */
export function defaultContentFor(kind: string): Record<string, unknown> {
  switch (kind) {
    case "script":
      return {
        scene: "reception",
        steps: [
          { step: 1, name: "", script: "" },
          { step: 2, name: "", script: "" },
        ],
        tips: [],
      };
    case "knowledge":
      return { category: "", content: [{ title: "", body: "" }], talk_script: "" };
    case "project":
      return {
        type: "service", duration_min: 30,
        flow: [{ step: 1, name: "", script: "" }],
        cautions: [], aftercare: [],
      };
    case "product":
      return { type: "", ingredients: [], positioning: "", usage: "", suitable: "", cautions: [], sales_points: [] };
    case "questionnaire":
      return { schema: { title: "", description: "", fields: [{ label: "", type: "text", required: false }] } };
    default:
      return {};
  }
}
