# -*- coding: utf-8 -*-
"""demo.json 校验 + 拼成单文件 index.html。"""
import base64
import copy
import difflib
import json
import math
import os
import re

from .config import ROOT

WEB = os.path.join(ROOT, "web")
VIEWS = ("front", "back", "right", "left", "top", "bottom", "iso", "iso2")
ANIM_FIELDS = {
    "spin": {"need": ["part", "speed"], "opt": ["axis", "pivot", "delay", "hollow"]},
    "turn": {"need": ["part", "by"], "opt": ["axis", "pivot", "time", "loop", "pause", "delay", "ease"]},
    "move": {"need": ["part", "by"], "opt": ["time", "loop", "pause", "delay", "ease"]},
    "screw": {"need": ["part", "turns", "pitch"], "opt": ["axis", "pivot", "time", "loop", "pause", "delay", "ease"]},
    "blink": {"need": ["part"], "opt": ["time", "delay"]},
}
LINK_FIELDS = {
    "crank_slider": {"need": ["crank", "rod", "slider", "center", "crank_pin", "slider_pin"],
                     "opt": ["id", "axis", "slide", "speed", "angle", "delay", "hollow"]},
    "four_bar": {"need": ["crank", "coupler", "rocker", "a", "b", "c", "d"],
                 "opt": ["id", "axis", "speed", "angle", "delay", "hollow"]},
}
POINT_KEYS = ("pivot", "center", "crank_pin", "slider_pin", "a", "b", "c", "d")
STEP_KEYS = {"title", "text", "view", "explode", "highlight", "ghost", "hide", "section", "labels", "anim", "readouts"}
TOP_KEYS = {"title", "subtitle", "parts", "explode", "steps", "params", "readouts"}
MATH = set("abs acos asin atan atan2 ceil cos exp floor log max min pow round sign sin sqrt tan PI E hypot trunc".split())
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _near(name, pool):
    m = difflib.get_close_matches(str(name), list(pool), n=2, cutoff=0.5)
    return "（是不是想写 %s？）" % " 或 ".join(m) if m else ""


def resolve_points(cfg, parts):
    """动画里写成零件名的点（铰点、转轴上的点），换成那个零件的中心坐标。返回新的配置，原来的不动。"""
    centers = {p["name"]: p.get("center") for p in parts}
    out = copy.deepcopy(cfg)
    for s in out.get("steps", []) if isinstance(out, dict) and isinstance(out.get("steps"), list) else []:
        for a in s.get("anim", []) if isinstance(s, dict) and isinstance(s.get("anim"), list) else []:
            if not isinstance(a, dict):
                continue
            for k in POINT_KEYS:
                if isinstance(a.get(k), str) and centers.get(a[k]):
                    a[k] = [float(c) for c in centers[a[k]]]
    return out


class Check:
    def __init__(self, parts):
        self.parts = [p["name"] for p in parts]
        self.centers = {p["name"]: p.get("center") for p in parts}
        self.errors, self.warnings = [], []
        self.params = set()

    def err(self, where, msg):
        self.errors.append("%s：%s" % (where, msg))

    def warn(self, where, msg):
        self.warnings.append("%s：%s" % (where, msg))

    def part(self, where, name):
        if not isinstance(name, str) or name not in self.parts:
            self.err(where, "没有叫 %r 的零件%s。现有零件：%s" % (name, _near(name, self.parts), "、".join(self.parts)))
            return False
        return True

    def part_list(self, where, v):
        if not isinstance(v, list):
            self.err(where, "要写成零件名的列表，比如 [\"%s\"]" % (self.parts[0] if self.parts else "Name"))
            return
        for n in v:
            self.part(where, n)

    def num(self, where, v, lo=None, hi=None):
        """数字或表达式。"""
        if isinstance(v, bool) or v is None:
            self.err(where, "要写数字或表达式，现在是 %r" % (v,))
            return
        if isinstance(v, (int, float)):
            if lo is not None and v < lo or hi is not None and v > hi:
                self.err(where, "数值 %s 超出范围 %s ~ %s" % (v, lo, hi))
            return
        if isinstance(v, str):
            stripped = re.sub(r"\d+\.?\d*(e[+-]?\d+)?", " ", v, flags=re.I)
            for name in IDENT.findall(stripped):
                if name not in self.params and name not in MATH and name != "t":
                    self.err(where, "表达式 %r 里的 %s 不是参数。能用的：%s、t（秒）和 sin/cos/abs/min/max/PI 等%s" % (
                        v, name, "、".join(sorted(self.params)) or "（还没定义 params）", _near(name, self.params)))
            if re.search(r"[;{}\[\]`'\"]", v) or re.search(r"(?<![<>=!])=(?!=)", v):
                self.err(where, "表达式 %r 里只能写算式（加减乘除、括号、比较、?:），不能赋值或写语句" % v)
            if v.count("(") != v.count(")"):
                self.err(where, "表达式 %r 的括号不配对" % v)
            return
        self.err(where, "要写数字或表达式，现在是 %r" % (v,))

    def axis(self, where, v):
        if isinstance(v, str):
            if v.lower().strip().lstrip("+-") not in ("x", "y", "z"):
                self.err(where, "axis 要写 \"x\" \"y\" \"z\"（可带 - 号），现在是 %r" % v)
        elif isinstance(v, list) and len(v) == 3 and all(isinstance(c, (int, float)) for c in v):
            if not any(v):
                self.err(where, "axis 不能是 [0,0,0]")
        else:
            self.err(where, "axis 要写 \"x\" \"y\" \"z\" 或 [x,y,z]，现在是 %r" % (v,))

    def vec3(self, where, v, expr=False):
        if not isinstance(v, list) or len(v) != 3:
            self.err(where, "要写 [x, y, z] 三个数（毫米），现在是 %r" % (v,))
            return
        for c in v:
            if expr:
                self.num(where, c)
            elif isinstance(c, bool) or not isinstance(c, (int, float)):
                self.err(where, "要写 [x, y, z] 三个数（毫米），现在是 %r" % (v,))
                return

    def point(self, where, v):
        """一个点：[x, y, z]，或者一个零件名（用那个零件的中心，销子、轴最合适）。"""
        if isinstance(v, str):
            self.part(where, v)
            return
        self.vec3(where, v)

    def unknown(self, where, d, allowed):
        for k in d:
            if k not in allowed:
                self.warn(where, "不认识的字段 %r，会被忽略%s" % (k, _near(k, allowed)))


def _v3(v):
    return [float(x) for x in v]


def _axis_vec(a):
    if isinstance(a, list):
        n = math.sqrt(sum(float(x) ** 2 for x in a)) or 1.0
        return [float(x) / n for x in a]
    k = str(a).lower().strip()
    sign = -1.0 if k.startswith("-") else 1.0
    k = k.lstrip("+-")
    return [sign * (k == "x"), sign * (k == "y"), sign * (k == "z")]


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _plane(v, n):
    d = _dot(v, n)
    return [v[i] - n[i] * d for i in range(3)]


def _len(v):
    return math.sqrt(_dot(v, v))


def linkage_problem(a):
    """连杆机构装不装得上。返回一句话的问题说明，没问题返回 None。只在曲柄连续转（用 speed）时检查整圈。"""
    try:
        n = _axis_vec(a.get("axis", "y"))
        if a["type"] == "crank_slider":
            o, p0, s0 = _v3(a["center"]), _v3(a["crank_pin"]), _v3(a["slider_pin"])
            d = _plane(_axis_vec(a.get("slide", "z")), n)
            if _len(d) < 1e-6:
                return "slide（滑块移动方向）和 axis（转动轴）不能是同一个方向"
            d = [x / _len(d) for x in d]
            r = _len(_plane(_sub(p0, o), n))
            L = _len(_plane(_sub(s0, p0), n))
            off = _plane(_sub(s0, o), n)
            e = math.sqrt(max(_dot(off, off) - _dot(off, d) ** 2, 0.0))       # 导轨离曲柄中心的偏距
            if r < 1e-6:
                return "crank_pin 和 center 重合了，曲柄半径是 0"
            if L < 1e-6:
                return "slider_pin 和 crank_pin 重合了，连杆长度是 0"
            if "speed" in a and L < r + e - 1e-6:
                return "连杆长度 %.1f 比「曲柄半径 %.1f + 导轨偏距 %.1f」还短，曲柄转不了整圈。把连杆加长，或者检查三个点的坐标" % (L, r, e)
        else:
            A, B, C, D = (_v3(a[k]) for k in "abcd")
            r1 = _len(_plane(_sub(B, A), n))
            r2 = _len(_plane(_sub(C, B), n))
            r3 = _len(_plane(_sub(C, D), n))
            r4 = _len(_plane(_sub(D, A), n))
            if min(r1, r2, r3) < 1e-6:
                return "a、b、c、d 里有两个点重合了"
            if "speed" in a:
                lens = sorted([r1, r2, r3, r4])
                if lens[0] + lens[3] > lens[1] + lens[2] + 1e-6 or abs(lens[0] - r1) > 1e-6:
                    return ("曲柄 %.1f、连杆 %.1f、摇杆 %.1f、机架 %.1f 这组长度，曲柄转不了整圈（要求曲柄最短，且最短 + 最长 ≤ 另外两根之和）。"
                            "改杆长，或者不用 speed，改用 angle 配一个范围合适的滑条" % (r1, r2, r3, r4))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def validate(cfg, parts):
    """返回 (错误列表, 警告列表)。"""
    c = Check(parts)
    if not isinstance(cfg, dict):
        return ["demo.json 最外层要是一个 {…} 对象"], []
    c.unknown("demo.json", cfg, TOP_KEYS)
    if not isinstance(cfg.get("title"), str) or not cfg.get("title").strip():
        c.err("title", "要写一个标题")
    # params
    ps = cfg.get("params", [])
    if not isinstance(ps, list):
        c.err("params", "要写成列表")
        ps = []
    for i, p in enumerate(ps):
        w = "params[%d]" % i
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not IDENT.fullmatch(p.get("id", "")):
            c.err(w, "每个参数要有 id（字母开头的英文名）")
            continue
        if p["id"] in c.params or p["id"] in MATH or p["id"] == "t":
            c.err(w, "参数 id %r 重复了或者和内置名字冲突" % p["id"])
        c.params.add(p["id"])
        c.unknown(w, p, {"id", "label", "min", "max", "value", "step", "unit"})
        try:
            lo, hi, val = float(p.get("min", 0)), float(p.get("max", 100)), float(p.get("value", 0))
            if not lo < hi:
                c.err(w, "min 要小于 max")
            elif not lo <= val <= hi:
                c.err(w, "value=%s 不在 min~max（%s~%s）之间" % (val, lo, hi))
        except (TypeError, ValueError):
            c.err(w, "min / max / value 要是数字")
    # 连杆机构的 id 会生成变量：<id>_pos（滑块位移，毫米）、<id>_angle（曲柄角，度）、<id>_rocker（摇杆摆角，度）
    for st in cfg.get("steps", []) if isinstance(cfg.get("steps"), list) else []:
        for a in (st.get("anim", []) if isinstance(st, dict) and isinstance(st.get("anim"), list) else []):
            if isinstance(a, dict) and a.get("type") in LINK_FIELDS and isinstance(a.get("id"), str) and IDENT.fullmatch(a["id"]):
                c.params.update({a["id"] + "_pos", a["id"] + "_angle", a["id"] + "_rocker"})
    # parts 覆盖
    over = cfg.get("parts", {})
    if not isinstance(over, dict):
        c.err("parts", "要写成 {\"零件名\": {…}}")
    else:
        for name, o in over.items():
            if c.part("parts", name) and isinstance(o, dict):
                c.unknown("parts.%s" % name, o, {"cn", "info", "group", "explode"})
                if "explode" in o:
                    c.vec3("parts.%s.explode" % name, o["explode"])
    ex = cfg.get("explode")
    if ex is not None and (not isinstance(ex, dict) or not isinstance(ex.get("scale", 1), (int, float))):
        c.err("explode", "要写成 {\"scale\": 1.0}")

    def readouts(where, rs):
        if not isinstance(rs, list):
            c.err(where, "要写成列表")
            return
        for i, r in enumerate(rs):
            w = "%s[%d]" % (where, i)
            if not isinstance(r, dict) or "label" not in r or "expr" not in r:
                c.err(w, "每个读数要有 label 和 expr")
                continue
            c.unknown(w, r, {"label", "expr", "unit", "digits"})
            c.num(w + ".expr", r["expr"])

    readouts("readouts", cfg.get("readouts", []))
    steps = cfg.get("steps", [])
    if not isinstance(steps, list):
        c.err("steps", "要写成列表")
        steps = []
    if not steps:
        c.warn("steps", "一个讲解步骤都没有，页面只会显示零件和爆炸图")
    for i, s in enumerate(steps):
        w = "steps[%d]" % i
        if not isinstance(s, dict):
            c.err(w, "每一步要是 {…} 对象")
            continue
        c.unknown(w, s, STEP_KEYS)
        if not isinstance(s.get("title"), str) or not s.get("title").strip():
            c.err(w + ".title", "每一步要有标题")
        if not isinstance(s.get("text", ""), str):
            c.err(w + ".text", "要是文字")
        elif not s.get("text", "").strip():
            c.warn(w + ".text", "这一步没有讲解文字")
        v = s.get("view")
        if isinstance(v, str):
            if v not in VIEWS:
                c.err(w + ".view", "没有 %r 这个视角%s。可用：%s" % (v, _near(v, VIEWS), "、".join(VIEWS)))
        elif isinstance(v, dict):
            c.unknown(w + ".view", v, {"preset", "az", "el", "zoom", "focus"})
            if "preset" in v and v["preset"] not in VIEWS:
                c.err(w + ".view.preset", "没有 %r 这个视角" % v["preset"])
            for k in ("az", "el", "zoom"):
                if k in v and (isinstance(v[k], bool) or not isinstance(v[k], (int, float))):
                    c.err(w + ".view." + k, "要是数字")
            if "zoom" in v and isinstance(v["zoom"], (int, float)) and not 0.2 <= v["zoom"] <= 8:
                c.err(w + ".view.zoom", "zoom 要在 0.2 ~ 8 之间")
            if v.get("focus") is not None:
                c.part(w + ".view.focus", v["focus"])
        elif v is not None:
            c.err(w + ".view", "要写视角名（如 \"iso\"）或 {\"az\":…, \"el\":…}")
        if "explode" in s:
            if isinstance(s["explode"], bool) or not isinstance(s["explode"], (int, float)) or not 0 <= s["explode"] <= 1:
                c.err(w + ".explode", "要是 0 ~ 1 之间的数")
        for k in ("highlight", "ghost", "hide"):
            if k in s:
                c.part_list(w + "." + k, s[k])
        if isinstance(s.get("hide"), list) and parts and set(s["hide"]) >= set(c.parts):
            c.err(w + ".hide", "所有零件都被隐藏了，画面会是空的")
        sec = s.get("section")
        if sec is not None:
            if not isinstance(sec, dict) or sec.get("axis") not in ("x", "y", "z"):
                c.err(w + ".section", "要写成 {\"axis\": \"x\", \"pos\": 0.5}，axis 是 x/y/z，pos 是 0~1")
            elif "pos" in sec and (isinstance(sec["pos"], bool) or not isinstance(sec["pos"], (int, float))
                                   or not 0 <= sec["pos"] <= 1):
                c.err(w + ".section.pos", "要是 0 ~ 1 之间的数（0.5 是正中间）")
        for j, lb in enumerate(s.get("labels", []) if isinstance(s.get("labels", []), list) else []):
            wl = "%s.labels[%d]" % (w, j)
            if not isinstance(lb, dict):
                c.err(wl, "要是 {…} 对象")
            elif "part" in lb:
                c.part(wl + ".part", lb["part"])
            elif "at" in lb:
                c.vec3(wl + ".at", lb["at"])
                if not lb.get("text"):
                    c.err(wl, "用 at 定位的标签要写 text")
            else:
                c.err(wl, "标签要有 part（零件名）或 at（[x,y,z] 坐标）")
        if "labels" in s and not isinstance(s["labels"], list):
            c.err(w + ".labels", "要写成列表")
        if "readouts" in s:
            readouts(w + ".readouts", s["readouts"])
        anims = s.get("anim", [])
        if not isinstance(anims, list):
            c.err(w + ".anim", "要写成列表")
            anims = []
        for j, a in enumerate(anims):
            wa = "%s.anim[%d]" % (w, j)
            if not isinstance(a, dict):
                c.err(wa, "要是 {…} 对象")
                continue
            t = a.get("type")
            if t in LINK_FIELDS:
                spec = LINK_FIELDS[t]
                c.unknown(wa, a, set(spec["need"]) | set(spec["opt"]) | {"type"})
                miss = [k for k in spec["need"] if k not in a]
                if miss:
                    c.err(wa, "%s 还缺字段：%s" % (t, "、".join(miss)))
                for k in ("crank", "rod", "slider", "coupler", "rocker"):
                    if k in a:
                        c.part_list(wa + "." + k, a[k] if isinstance(a[k], list) else [a[k]])
                for k in ("center", "crank_pin", "slider_pin", "a", "b", "c", "d"):
                    if k in a:
                        c.point(wa + "." + k, a[k])
                for k in ("axis", "slide"):
                    if k in a:
                        c.axis(wa + "." + k, a[k])
                if ("speed" in a) == ("angle" in a):
                    c.err(wa, "speed（一直转，度/秒）和 angle（直接给角度，度）要写一个，而且只写一个")
                for k in ("speed", "angle"):
                    if k in a:
                        c.num(wa + "." + k, a[k])
                if "id" in a and (not isinstance(a["id"], str) or not IDENT.fullmatch(a["id"])):
                    c.err(wa + ".id", "id 要是字母开头的英文名")
                if not miss and not c.errors:
                    ar = dict(a)
                    for k in POINT_KEYS:
                        if isinstance(ar.get(k), str):
                            ar[k] = c.centers.get(ar[k])
                    prob = linkage_problem(ar)
                    if prob:
                        c.err(wa, prob)
                continue
            if t not in ANIM_FIELDS:
                c.err(wa + ".type", "没有 %r 这种动画%s。可用：%s" % (
                    t, _near(t, list(ANIM_FIELDS) + list(LINK_FIELDS)), "、".join(list(ANIM_FIELDS) + list(LINK_FIELDS))))
                continue
            spec = ANIM_FIELDS[t]
            c.unknown(wa, a, set(spec["need"]) | set(spec["opt"]) | {"type"})
            miss = [k for k in spec["need"] if k not in a]
            if miss:
                c.err(wa, "%s 动画还缺字段：%s" % (t, "、".join(miss)))
            if "part" in a:
                c.part(wa + ".part", a["part"])
            if "axis" in a:
                c.axis(wa + ".axis", a["axis"])
            if "pivot" in a:
                c.point(wa + ".pivot", a["pivot"])
            if t == "move" and "by" in a:
                c.vec3(wa + ".by", a["by"], expr=True)
            if t == "turn" and "by" in a:
                c.num(wa + ".by", a["by"])
            for k in ("speed", "turns", "pitch"):
                if k in a:
                    c.num(wa + "." + k, a[k])
            for k in ("time", "pause", "delay"):
                if k in a and (isinstance(a[k], bool) or not isinstance(a[k], (int, float)) or a[k] < 0):
                    c.err(wa + "." + k, "要是不小于 0 的数字（秒）")
            if a.get("time") == 0:
                c.err(wa + ".time", "time 不能是 0")
            if "loop" in a and a["loop"] not in ("once", "repeat", "pingpong"):
                c.err(wa + ".loop", "loop 要写 once / repeat / pingpong")
            if "ease" in a and a["ease"] not in ("smooth", "linear"):
                c.err(wa + ".ease", "ease 要写 smooth 或 linear")
    return c.errors, c.warnings


def load_json(path):
    """读 JSON；出错时返回 (None, 中文提示)。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "还没有 %s" % os.path.basename(path)
    except ValueError as e:
        m = re.search(r"line (\d+) column (\d+)", str(e))
        hint = ""
        if m:
            lines = open(path, encoding="utf-8-sig").read().splitlines()
            ln = int(m.group(1))
            if 0 < ln <= len(lines):
                hint = "\n    第 %d 行：%s" % (ln, lines[ln - 1].strip()[:120])
        return None, "%s 不是合法的 JSON：%s%s\n（常见原因：多了或少了逗号、用了单引号、写了注释）" % (
            os.path.basename(path), e, hint)


def _read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def build(job):
    """校验并生成 out/index.html。返回 {'ok', 'errors', 'warnings', 'path', 'kb'}。"""
    out = os.path.join(job, "out")
    parts, e = load_json(os.path.join(out, "parts.json"))
    if e or not os.path.exists(os.path.join(out, "model.glb")):
        return {"ok": False, "errors": ["还没有模型，先用 build_model 把模型做出来"], "warnings": []}
    cfg, e = load_json(os.path.join(job, "demo.json"))
    if e:
        return {"ok": False, "errors": [e], "warnings": []}
    errors, warnings = validate(cfg, parts)
    custom = ""
    cp = os.path.join(job, "custom.js")
    if os.path.exists(cp):
        custom = open(cp, encoding="utf-8-sig").read()
        for name in re.findall(r"api\.part\(\s*['\"]([^'\"]+)['\"]\s*\)", custom):
            if name not in [p["name"] for p in parts]:
                errors.append("custom.js：api.part(%r) 里的零件不存在%s" % (name, _near(name, [p["name"] for p in parts])))
        for pid in re.findall(r"api\.(?:param|setParam)\(\s*['\"]([^'\"]+)['\"]", custom):
            if pid not in [p.get("id") for p in cfg.get("params", []) if isinstance(p, dict)]:
                errors.append("custom.js：api.param(%r) 用的参数没有在 demo.json 的 params 里定义" % pid)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    with open(os.path.join(out, "model.glb"), "rb") as f:
        glb = base64.b64encode(f.read()).decode("ascii")
    data = json.dumps({"config": resolve_points(cfg, parts), "parts": parts, "glb": glb}, ensure_ascii=False).replace("</", "<\\/")
    html = _read("template.html")
    html = html.replace("__QB_TITLE__", str(cfg.get("title", "演示")).replace("<", "&lt;"))
    for mark, text in (("/*__QB_THREE__*/", _read(os.path.join("vendor", "three.bundle.min.js"))),
                       ("/*__QB_DATA__*/null", data),
                       ("/*__QB_VIEWER__*/", _read("viewer.js")),
                       ("/*__QB_CUSTOM__*/", custom)):
        if mark not in html:
            raise RuntimeError("模板里缺少标记 " + mark)
        html = html.replace(mark, text.replace("</script", "<\\/script"), 1)
    path = os.path.join(out, "index.html")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return {"ok": True, "errors": [], "warnings": warnings, "path": path, "kb": os.path.getsize(path) // 1024}
