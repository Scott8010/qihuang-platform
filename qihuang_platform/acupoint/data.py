"""
穴位数据层 — 从 model/opensource/opensource_acupoints.json 加载并结构化

提供:
- 穴位列表（含3D坐标、释义、功能、定位）
- 经络循行路径（穴位按码序连接的坐标序列）
- 3D模型资源元信息（CDN地址待T0-1云环境就绪后替换）
"""
import json
import os
from typing import Optional, List, Dict, Any
from functools import lru_cache


# 经络定义：code → {name, name_en, element, yin_yang, region, time}
MERIDIAN_DEFS = {
    "LU": {"name": "手太阴肺经", "name_en": "Lung", "element": "金", "yin_yang": "yin", "region": "arm", "time": "寅时 3-5点"},
    "LI": {"name": "手阳明大肠经", "name_en": "Large Intestine", "element": "金", "yin_yang": "yang", "region": "arm", "time": "卯时 5-7点"},
    "ST": {"name": "足阳明胃经", "name_en": "Stomach", "element": "土", "yin_yang": "yang", "region": "leg", "time": "辰时 7-9点"},
    "SP": {"name": "足太阴脾经", "name_en": "Spleen", "element": "土", "yin_yang": "yin", "region": "leg", "time": "巳时 9-11点"},
    "HT": {"name": "手少阴心经", "name_en": "Heart", "element": "火", "yin_yang": "yin", "region": "arm", "time": "午时 11-13点"},
    "SI": {"name": "手太阳小肠经", "name_en": "Small Intestine", "element": "火", "yin_yang": "yang", "region": "arm", "time": "未时 13-15点"},
    "BL": {"name": "足太阳膀胱经", "name_en": "Bladder", "element": "水", "yin_yang": "yang", "region": "leg", "time": "申时 15-17点"},
    "KI": {"name": "足少阴肾经", "name_en": "Kidney", "element": "水", "yin_yang": "yin", "region": "leg", "time": "酉时 17-19点"},
    "PC": {"name": "手厥阴心包经", "name_en": "Pericardium", "element": "火", "yin_yang": "yin", "region": "arm", "time": "戌时 19-21点"},
    "TE": {"name": "手少阳三焦经", "name_en": "Triple Energizer", "element": "火", "yin_yang": "yang", "region": "arm", "time": "亥时 21-23点"},
    "GB": {"name": "足少阳胆经", "name_en": "Gallbladder", "element": "木", "yin_yang": "yang", "region": "leg", "time": "子时 23-1点"},
    "LR": {"name": "足厥阴肝经", "name_en": "Liver", "element": "木", "yin_yang": "yin", "region": "leg", "time": "丑时 1-3点"},
    "CV": {"name": "任脉", "name_en": "Conception Vessel", "element": "", "yin_yang": "yin", "region": "trunk", "time": ""},
    "GV": {"name": "督脉", "name_en": "Governing Vessel", "element": "", "yin_yang": "yang", "region": "trunk", "time": ""},
}

# 经络颜色映射（与前端岐黄三境.html配色一致）
MERIDIAN_COLORS = {
    "LU": "#CC9999", "LI": "#CCCC99", "ST": "#99CC99", "SP": "#9999CC",
    "HT": "#CC6666", "SI": "#CC9966", "BL": "#6699CC", "KI": "#666699",
    "PC": "#CC6699", "TE": "#99CCCC", "GB": "#99CC66", "LR": "#66CC99",
    "CV": "#CC99CC", "GV": "#99CC99",
}

# CDN资源地址（T0-1云环境就绪后替换为真实COS地址）
CDN_BASE = "https://cdn.yshealth.com.cn/3d/"

# 模型资源清单
MODEL_ASSETS = {
    "version": "1.0.0",
    "models": {
        "body": {
            "url": f"{CDN_BASE}man_body.obj",
            "format": "obj",
            "size_mb": 7.8,
            "description": "开源人体模型（当前生产）"
        },
        "bronze": {
            "url": f"{CDN_BASE}acupuncture-tongren-baked.glb",
            "format": "glb",
            "size_mb": 8.9,
            "description": "针灸铜人烘焙精简版（推荐）"
        },
        "bronze_full": {
            "url": f"{CDN_BASE}acupuncture-baked.glb",
            "format": "glb",
            "size_mb": 85.5,
            "description": "针灸铜人完整烘焙版（高精度）"
        }
    },
    "textures": {
        "base": f"{CDN_BASE}textures/",
    },
    "acupoint_count": 361,
    "meridian_count": 14,
    "cdn_base": CDN_BASE,
    "threejs_version": "r160",
    "min_threejs": "r152",
}


class AcupointData:
    """穴位数据管理器（单例模式，惰性加载）"""

    def __init__(self):
        self._data_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..",
            "model", "opensource", "opensource_acupoints.json"
        )
        # 尝试多个可能的路径
        self._alt_paths = [
            os.path.join(os.path.dirname(__file__), "acupoints.json"),  # 内嵌副本
            "C:/Users/Administrator/Desktop/岐黄大脑/model/opensource/opensource_acupoints.json",
            "/C/Users/Administrator/Desktop/岐黄大脑/model/opensource/opensource_acupoints.json",
        ]
        self._acupoints: Optional[List[Dict]] = None
        self._by_meridian: Optional[Dict[str, List[Dict]]] = None
        self._by_code: Optional[Dict[str, Dict]] = None

    def _find_data_path(self) -> str:
        """查找穴位数据文件"""
        for path in self._alt_paths:
            if os.path.exists(path):
                return path
        # 搜索桌面
        import glob
        matches = glob.glob("C:/Users/*/Desktop/岐黄大脑/model/opensource/opensource_acupoints.json")
        if matches:
            return matches[0]
        return self._alt_paths[-1]  # fallback

    def load(self):
        """加载穴位数据"""
        if self._acupoints is not None:
            return

        data_path = self._find_data_path()
        with open(data_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self._acupoints = raw.get("acupoints", [])
        self._by_meridian = {}
        self._by_code = {}

        for pt in self._acupoints:
            mc = pt["meridian_code"]
            if mc not in self._by_meridian:
                self._by_meridian[mc] = []
            self._by_meridian[mc].append(pt)
            self._by_code[pt["code"]] = pt

        # 每个经络内按code排序
        for mc in self._by_meridian:
            self._by_meridian[mc].sort(key=lambda p: p["code"])

    @property
    def acupoints(self) -> List[Dict]:
        self.load()
        return self._acupoints

    def get_by_meridian(self, meridian_code: str) -> Optional[List[Dict]]:
        """获取指定经络的所有穴位"""
        self.load()
        meridian_code = meridian_code.upper()
        return self._by_meridian.get(meridian_code)

    def get_by_code(self, acupoint_code: str) -> Optional[Dict]:
        """获取单个穴位"""
        self.load()
        return self._by_code.get(acupoint_code.upper())

    def list_meridians(self) -> List[Dict]:
        """列出所有经络及其统计信息"""
        self.load()
        result = []
        for code in sorted(self._by_meridian.keys()):
            pts = self._by_meridian[code]
            defn = MERIDIAN_DEFS.get(code, {})
            result.append({
                "code": code,
                "name": defn.get("name", code),
                "name_en": defn.get("name_en", ""),
                "element": defn.get("element", ""),
                "yin_yang": defn.get("yin_yang", ""),
                "region": defn.get("region", ""),
                "time": defn.get("time", ""),
                "color": MERIDIAN_COLORS.get(code, "#888888"),
                "acupoint_count": len(pts),
                "acupoint_codes": [p["code"] for p in pts],
            })
        return result

    def get_meridian_path(self, meridian_code: str) -> Optional[Dict]:
        """获取经络循行路径（穴位坐标序列）"""
        self.load()
        meridian_code = meridian_code.upper()
        pts = self._by_meridian.get(meridian_code)
        if not pts:
            return None

        defn = MERIDIAN_DEFS.get(meridian_code, {})
        path_points = []
        for pt in pts:
            path_points.append({
                "code": pt["code"],
                "name": pt["chinese_name"],
                "pinyin": pt["pinyin"],
                "position_3d": pt["position_3d"],
            })

        return {
            "code": meridian_code,
            "name": defn.get("name", meridian_code),
            "name_en": defn.get("name_en", ""),
            "color": MERIDIAN_COLORS.get(meridian_code, "#888888"),
            "element": defn.get("element", ""),
            "region": defn.get("region", ""),
            "time": defn.get("time", ""),
            "acupoint_count": len(pts),
            "path_points": path_points,
        }

    def search(self, keyword: str) -> List[Dict]:
        """按关键词搜索穴位（名称/拼音/编码/释义）"""
        self.load()
        keyword = keyword.lower()
        results = []
        for pt in self._acupoints:
            search_text = f"{pt['code']} {pt['chinese_name']} {pt['pinyin']} {pt.get('shiyi','')} {pt.get('gongneng','')}".lower()
            if keyword in search_text:
                results.append(self._serialize_point(pt))
        return results[:50]  # 最多50条

    def get_model_meta(self) -> Dict:
        """获取3D模型资源元信息"""
        return MODEL_ASSETS

    def _serialize_point(self, pt: Dict) -> Dict:
        """序列化单个穴位为API响应格式"""
        return {
            "code": pt["code"],
            "name": pt["chinese_name"],
            "pinyin": pt["pinyin"],
            "meridian": {
                "code": pt["meridian_code"],
                "name": pt["meridian_name"],
                "color": MERIDIAN_COLORS.get(pt["meridian_code"], "#888888"),
            },
            "position_3d": pt["position_3d"],
            "shiyi": pt.get("shiyi", ""),
            "gongneng": pt.get("gongneng", ""),
            "location": pt.get("location", ""),
        }


# 全局单例
acupoint_data = AcupointData()
