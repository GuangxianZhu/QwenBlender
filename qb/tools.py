# -*- coding: utf-8 -*-
"""给模型用的工具：定义（schema）+ 实现。每个工具返回 (文字, [图片路径])。"""
import difflib
import json
import os
import re
import shutil
import time

from . import blender, browser, calc, page, search

FILES = ("model.py", "demo.json", "custom.js")


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}

SPECS = [
    _fn("submit_plan", "第一步必须调用：提交零件清单。每个零件写英文名、中文名、作用、大概尺寸（毫米）。之后 build_model 会拿它来核对。",
        {"parts": {"type": "array", "items": {"type": "object", "properties": {
            "name": dict(S, description="英文名，字母开头，只含字母数字下划线"),
            "cn": dict(S, description="中文名"), "purpose": dict(S, description="这个零件是干什么的"),
            "size": {"type": "array", "items": N, "description": "[长x, 宽y, 高z] 毫米，大概值"}},
            "required": ["name", "cn"]}},
         "notes": dict(S, description="装配关系和关键尺寸，几句话")}, ["parts"]),
    _fn("lib_help", "查零件库 qblib 的用法。不带参数列出全部函数；带函数名看完整说明；\"demo\" 看网页配置写法；\"custom\" 看 custom.js 写法。",
        {"topic": dict(S, description="函数名（可以多个，空格隔开），或 demo / custom / mat")}),
    _fn("search_examples", "搜范例代码（model.py、demo.json、custom.js 的现成写法）。关键词用中文或英文都行。",
        {"query": S}, ["query"]),
    _fn("search_bpy", "查本机 Blender 版本的 Python API（bpy.ops、bpy.types、bmesh.ops）。只有 qblib 做不到、要直接写 bpy 时才用。关键词用英文。",
        {"query": S}, ["query"]),
    _fn("read_file", "读任务目录里的文件，带行号。", {"name": dict(S, enum=list(FILES) + ["plan.json"])}, ["name"]),
    _fn("write_file", "写整个文件（覆盖）。model.py 是建模脚本，demo.json 是网页配置，custom.js 是可选的网页脚本。",
        {"name": dict(S, enum=list(FILES)), "content": S}, ["name", "content"]),
    _fn("edit_file", "改文件里的一小段：把 old 换成 new。old 必须和文件里的原文一字不差，而且只出现一次。小修改用这个，比重写整个文件快。",
        {"name": dict(S, enum=list(FILES)), "old": S, "new": S}, ["name", "old", "new"]),
    _fn("calc", "机构计算器，建模之前先把数算清楚，不要心算。kind 选一种：four_bar（给 crank coupler rocker frame 四个杆长 → 能不能转整圈、摆角、传动角；"
        "或者给 crank 和 want_swing → 按想要的摆角反推杆长）、crank_slider（crank rod offset → 行程）、gear（z1 z2 → 速比和转向）、"
        "worm（teeth starts → 减速比）、belt（d1 d2 → 速比）、planetary（sun ring → 行星轮齿数和各自的转速）、screw（pitch 加 turns 或 travel）。",
        {"kind": dict(S, enum=list(calc.KINDS)), "crank": N, "coupler": N, "rocker": N, "frame": dict(N, description="两个固定转轴之间的距离"),
         "arm": dict(N, description="摇杆轴上固定的那根臂的长度（可选）"), "want_swing": dict(N, description="想要的摆角（度）"),
         "rod": N, "offset": N, "z1": dict(N, description="主动轮齿数"), "z2": dict(N, description="从动轮齿数"), "internal": B, "module": N,
         "teeth": dict(N, description="蜗轮齿数"), "starts": dict(N, description="蜗杆头数"), "q": N, "d1": N, "d2": N, "center": N,
         "sun": N, "ring": N, "planets": N, "pitch": N, "turns": N, "travel": N}, ["kind"]),
    _fn("restore", "把 model.py 或 demo.json 退回到上一个通过检查的版本。越改越糟的时候用。",
        {"name": dict(S, enum=["model.py", "demo.json"])}, ["name"]),
    _fn("build_model", "在 Blender 里运行 model.py。返回：报错位置、每个零件的尺寸和位置、检查结果（穿模/悬空/破面/和计划不符），外加一张四视图。每写完一两个零件就调用一次。"),
    _fn("look", "从指定角度再看一眼上次构建的模型（返回一张图）。az=0 正前方（相机在 -Y），az=90 右侧（相机在 +X），az=180 背面；el 仰角，90 是正上方，负数是从下往上看。",
        {"az": N, "el": N, "focus": dict(S, description="可选：对准并放大某个零件")}, ["az", "el"]),
    _fn("section", "把上次构建的模型沿一个轴剖开看内部（返回一张图，每个被切到的零件切面一种颜色）。检查孔、轴、螺纹这些内部配合时用。",
        {"axis": dict(S, enum=["x", "y", "z"]), "pos": dict(N, description="剖切位置的坐标（毫米）。不写就切在正中间")}, ["axis"]),
    _fn("measure", "量上次构建的模型：只给 a 返回它的尺寸、位置、朝向；再给 b 返回两个零件的间隙、穿入深度、中心距。",
        {"a": S, "b": S}, ["a"]),
    _fn("list_parts", "列出上次构建出来的零件：英文名、中文名、尺寸、位置。写 demo.json 之前先看这个，零件名必须一字不差。"),
    _fn("build_page", "校验 demo.json（零件名、动画字段、表达式）并生成网页 out/index.html。有错会逐条指出来。"),
    _fn("check_page", "检查网页：控制台报错、每一步是否正常、动画有没有动、手机上是否溢出；还会让动画真的走起来检查："
        "动起来以后会不会穿模（转向反了、速比不对都能查出来）、贴着的零件会不会离开、铰点上有没有销子、转轴上有没有轴、"
        "网页里写的摆角和行程对不对；并返回运动范围（摆角、行程、每个零件扫过的范围）。返回电脑和手机的截图。"),
    _fn("finish", "全部做完后调用。模型和网页还有没解决的问题时会被拒绝；确实解决不了的，在 unresolved 里如实写明。",
        {"summary": dict(S, description="做了什么，几句话"),
         "unresolved": dict(S, description="还没解决的问题。没有就留空")}, ["summary"]),
]


class Job:
    def __init__(self, path, cfg, want_page=True):
        self.path = os.path.abspath(path)
        self.cfg = cfg
        os.makedirs(os.path.join(self.path, "out"), exist_ok=True)
        self.state = {"plan": False, "build": None, "build_stale": True, "page": None, "page_stale": True,
                      "check": None, "want_page": want_page, "finished": False, "summary": "", "unresolved": ""}
        sp = os.path.join(self.path, "state.json")
        if os.path.exists(sp):
            try:
                self.state.update(json.load(open(sp, encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        json.dump(self.state, open(os.path.join(self.path, "state.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    def file(self, name):
        return os.path.join(self.path, name)

    def out(self, name):
        return os.path.join(self.path, "out", name)

    def part_names(self):
        parts, _ = page.load_json(self.out("parts.json"))
        return [p["name"] for p in parts or []]


# ------------------------------------------------------------------ 文字格式

def _f(v):
    return "×".join("%g" % round(x, 1) for x in v)


def _p(v):
    return "(" + ", ".join("%g" % round(x, 1) for x in v) + ")"


def format_build(rep):
    if not rep.get("ok"):
        e = rep.get("error", {})
        t = e.get("type", "")
        if t in ("NoBlender", "Timeout", "Crash", "Missing") or t.startswith("Internal"):
            return "构建失败：%s\n%s" % (e.get("msg", ""), e.get("trace", ""))
        lines = ["构建失败：model.py%s 出错" % (" 第 %s 行" % e["line"] if e.get("line") else "")]
        if e.get("src"):
            lines.append("    " + e["src"])
        lines.append("%s%s：%s" % (t, "（在 %s 里）" % e["via"] if e.get("via") else "", e.get("msg", "")))
        msg = e.get("msg", "")
        names = search.lib_names()
        m = re.search(r"name '(\w+)' is not defined", msg)
        if m:
            close = difflib.get_close_matches(m.group(1), names, n=3, cutoff=0.5)
            lines.append("提示：qblib 里没有 %s。%s" % (m.group(1), "相近的函数：" + "、".join(close) if close
                                                    else "用 lib_help() 看有哪些函数；变量要先定义再用"))
        m = re.search(r"(\w+)\(\) (got an unexpected keyword argument|missing \d+ required|takes )", msg)
        if m and m.group(1) in names:
            lines.append("正确写法：" + search.lib_functions()[m.group(1)][0])
        if rep.get("printed"):
            lines.append("脚本打印的内容：\n" + rep["printed"][-500:])
        return "\n".join(lines)
    tot = rep["total"]
    lines = ["构建成功：%d 个零件，用时 %s 秒（Blender %s）" % (len(rep["parts"]), rep.get("seconds", "?"), rep.get("blender", "")),
             "整体尺寸 %s mm，范围 x %g~%g  y %g~%g  z %g~%g" % (
                 _f(tot["size"]), tot["min"][0], tot["max"][0], tot["min"][1], tot["max"][1], tot["min"][2], tot["max"][2]),
             "零件："]
    for i, p in enumerate(rep["parts"], 1):
        lines.append("  %d. %s%s  尺寸 %s  中心 %s  z %g~%g  接触：%s" % (
            i, p["name"], "「%s」" % p["cn"] if p["cn"] else "", _f(p["size"]), _p(p["center"]),
            p["min"][2], p["max"][2], "、".join(p["touches"]) or "无"))
    if rep.get("joints"):
        lines.append("销子和轴（demo.json 的连杆动画里，铰点和转轴上的点可以直接写它们的名字）：")
        for j in rep["joints"]:
            lines.append("  %s：%s %s，在 %s 附近，方向 %s" % (
                j["name"], "铰接" if j["kind"] == "pin" else "穿过", "、".join(j["parts"]), _p(j["point"]), _axis_name(j["axis"])))
    if rep["issues"]:
        lines.append("必须修的问题：")
        lines += ["  ✗ " + x for x in rep["issues"]]
    if rep["warnings"]:
        lines.append("提醒：")
        lines += ["  ! " + x for x in rep["warnings"]]
    if not rep["issues"] and not rep["warnings"]:
        lines.append("检查：没有穿模、悬空、破面")
    if rep.get("hidden"):
        lines.append("图上看不到的零件（报告里的数字照常可信）：")
        lines += ["  · " + x for x in rep["hidden"][:8]]
    if rep.get("printed"):
        lines.append("脚本打印的内容：\n" + rep["printed"][-500:])
    if rep.get("image"):
        lines.append("附图是四视图：左上 FRONT（从 -Y 看），右上 RIGHT（从 +X 看），左下 TOP（从上往下，+Y 朝上），右下 ISO。"
                     "每格左下角的红绿蓝小箭头是 X/Y/Z 方向标，不是模型。对照图看：形状对不对、位置和朝向对不对、有没有缺东西。")
    return "\n".join(lines)


def _issue_key(text):
    """一条问题去掉数字以后的样子，用来比较前后两次是不是同一个问题。"""
    head = re.split(r"[，。（(：:]", str(text).replace("动起来以后穿模：", "动起来以后穿模 "), 1)
    return re.sub(r"[-+]?\d+(?:\.\d+)?", "#", head[0] + (re.split(r"[，。]", head[1])[0] if len(head) > 1 else ""))[:80]


def compare_issues(old, new):
    """和上一次比：返回 (解决了的, 新出现的)。"""
    ko, kn = {_issue_key(x): x for x in old or []}, {_issue_key(x): x for x in new or []}
    return [ko[k] for k in ko if k not in kn], [kn[k] for k in kn if k not in ko]


def _short(text, n=46):
    t = str(text)
    return t if len(t) <= n else t[:n] + "…"


def _axis_name(v):
    for i, ch in enumerate("xyz"):
        if abs(abs(v[i]) - 1) < 1e-3:
            return ("-" if v[i] < 0 else "") + ch
    return "(%s)" % ", ".join("%g" % round(c, 3) for c in v)


_NUM_RULES = (
    ("swing", "摆角", "°", 5.0, 3.0, 0.06,
     re.compile(r"(?:摆角|摆幅|摆动范围|摆动角度|摆动的角度)([^。；;\n]{0,40})"), re.compile(r"([-+−]?\d+(?:\.\d+)?)\s*°")),
    ("stroke", "行程", " mm", 0.5, 1.0, 0.05,
     re.compile(r"行程([^。；;\n]{0,40})"), re.compile(r"([-+−]?\d+(?:\.\d+)?)\s*(?:mm|毫米)")),
)


def text_number_problems(cfg, parts, ranges):
    """网页文字里写的摆角、行程，和按模型、动画算出来的对不对得上。返回问题列表。"""
    texts = []
    for k, w in (("title", "标题"), ("subtitle", "副标题")):
        if cfg.get(k):
            texts.append((w, str(cfg[k])))

    def readouts(where, rs):
        for r in rs if isinstance(rs, list) else []:
            if isinstance(r, dict) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", str(r.get("expr", ""))):
                texts.append(("%s读数「%s」" % (where, r.get("label", "")),
                              "%s %s%s" % (r.get("label", ""), str(r["expr"]).strip(), r.get("unit", ""))))

    readouts("", cfg.get("readouts"))
    for i, st in enumerate(cfg.get("steps", []) if isinstance(cfg.get("steps"), list) else []):
        if isinstance(st, dict):
            texts.append(("第 %d 步的文字" % (i + 1), "%s。%s" % (st.get("title", ""), st.get("text", ""))))
            readouts("第 %d 步的" % (i + 1), st.get("readouts"))
    for p in parts or []:
        if p.get("info"):
            texts.append(("零件 %s 的说明（model.py 里 part 的 info）" % p["name"], str(p["info"])))
    out = []
    for key, what, unit, floor, tol_abs, tol_rel, rx_clause, rx_num in _NUM_RULES:
        actual = sorted({v for r in ranges for v in r.get(key, [])})
        if not actual:
            continue
        for where, text in texts:
            for m in rx_clause.finditer(text):
                nums = [float(x.replace("−", "-")) for x in rx_num.findall(m.group(1))]
                if not nums:
                    continue
                cand = {abs(v) for v in nums} | {abs(a - b) for a in nums for b in nums if a != b}
                if any(abs(c - x) <= max(tol_abs, tol_rel * x) for c in cand for x in actual):
                    continue
                big = [abs(v) for v in nums if abs(v) >= floor]
                if not big:
                    continue
                out.append("%s写的%s是 %g%s，按模型和动画算出来是 %s。把它改成算出来的数" % (
                    where, what, big[0], unit, "、".join("%g%s" % (x, unit) for x in actual)))
                break
        if len(out) >= 6:
            break
    return out


# ------------------------------------------------------------------ 实现

def _need_build(job):
    if not job.state.get("build"):
        return "还没有构建结果，先调用 build_model"
    return None


def t_submit_plan(job, a):
    parts = a.get("parts")
    if isinstance(parts, str):
        try:
            parts = json.loads(parts)
        except ValueError:
            parts = None
    if not isinstance(parts, list) or not parts:
        return "parts 要是零件的列表，至少一个", []
    bad = []
    seen = set()
    for p in parts:
        nm = p.get("name") if isinstance(p, dict) else None
        if not isinstance(nm, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", nm):
            bad.append("零件名 %r 不合规：要字母开头，只含字母、数字、下划线" % (nm,))
        elif nm in seen:
            bad.append("零件名 %s 重复了" % nm)
        seen.add(nm)
        sz = p.get("size") if isinstance(p, dict) else None
        if sz is not None and not (isinstance(sz, list) and len(sz) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in sz)):
            bad.append("%s 的 size 要写成 [x, y, z] 三个大于 0 的数" % nm)
    if bad:
        return "计划有问题：\n" + "\n".join("  ✗ " + b for b in bad), []
    json.dump({"parts": parts, "notes": a.get("notes", "")}, open(job.file("plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    job.state["plan"] = True
    return ("计划已记录：%d 个零件。接下来写 model.py：一次只加一两个零件，写完就 build_model 看结果，没问题再加下一个。"
            % len(parts)), []


def t_lib_help(job, a):
    return search.lib_help(a.get("topic", "")), []


def t_search_examples(job, a):
    return search.search_examples(str(a.get("query", ""))), []


def t_search_bpy(job, a):
    return search.search_bpy(str(a.get("query", "")), job.cfg), []


def t_read_file(job, a):
    name = a.get("name")
    if name not in FILES + ("plan.json",):
        return "只能读：%s、plan.json" % "、".join(FILES), []
    p = job.file(name)
    if not os.path.exists(p):
        return "%s 还不存在" % name, []
    lines = open(p, encoding="utf-8-sig").read().splitlines()
    if len(lines) > 400:
        return "\n".join("%4d  %s" % (i + 1, l) for i, l in enumerate(lines[:400])) + "\n…（共 %d 行，只显示前 400 行）" % len(lines), []
    return "\n".join("%4d  %s" % (i + 1, l) for i, l in enumerate(lines)) or "（空文件）", []


def _touch(job, name):
    if name == "model.py":
        job.state["build_stale"] = True
        job.state["page_stale"] = True
    else:
        job.state["page_stale"] = True
    job.state["check"] = None


def _strip_fence(text):
    m = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n```\s*", text, re.S)
    return m.group(1) if m else text


def t_write_file(job, a):
    name, content = a.get("name"), a.get("content")
    if name not in FILES:
        return "只能写：%s" % "、".join(FILES), []
    if not isinstance(content, str) or not content.strip():
        return "content 是空的", []
    if name == "model.py" and not job.state.get("plan"):
        return "先调用 submit_plan 提交零件清单，再写 model.py", []
    content = _strip_fence(content)
    if name == "demo.json":
        try:
            json.loads(content)
        except ValueError as e:
            return "没有写入：demo.json 不是合法的 JSON：%s（检查逗号、引号，不能写注释）" % e, []
    if name == "model.py":
        try:
            compile(content, "model.py", "exec")
        except SyntaxError as e:
            return "没有写入：model.py 第 %s 行有语法错误：%s\n    %s" % (e.lineno, e.msg, (e.text or "").strip()), []
        if "qblib" not in content:
            content = "from qblib import *\n" + content
    with open(job.file(name), "w", encoding="utf-8", newline="\n") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    _touch(job, name)
    nxt = {"model.py": "下一步：build_model", "demo.json": "下一步：build_page", "custom.js": "下一步：build_page"}[name]
    return "已写入 %s（%d 行）。%s" % (name, content.count("\n") + 1, nxt), []


def t_edit_file(job, a):
    name, old, new = a.get("name"), a.get("old"), a.get("new")
    if name not in FILES:
        return "只能改：%s" % "、".join(FILES), []
    p = job.file(name)
    if not os.path.exists(p):
        return "%s 还不存在，用 write_file 创建" % name, []
    if not isinstance(old, str) or not old or not isinstance(new, str):
        return "old 和 new 都要是文字，old 不能为空", []
    text = open(p, encoding="utf-8-sig").read()
    n = text.count(old)
    if n == 0:
        key = old.strip().splitlines()[0].strip() if old.strip() else ""
        near = difflib.get_close_matches(key, [l.strip() for l in text.splitlines()], n=2, cutoff=0.6)
        return "没有改：文件里找不到 old 这段原文。" + ("最像的行：\n" + "\n".join("    " + x for x in near) if near
                                              else "先 read_file 看看现在的内容"), []
    if n > 1:
        return "没有改：old 在文件里出现了 %d 次，多带几行上下文让它唯一" % n, []
    text2 = text.replace(old, new, 1)
    if name == "model.py":
        try:
            compile(text2, "model.py", "exec")
        except SyntaxError as e:
            return "没有改：改完以后第 %s 行有语法错误：%s\n    %s" % (e.lineno, e.msg, (e.text or "").strip()), []
    if name == "demo.json":
        try:
            json.loads(text2)
        except ValueError as e:
            return "没有改：改完以后 demo.json 不是合法的 JSON：%s" % e, []
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text2)
    _touch(job, name)
    return "已修改 %s。" % name, []


def t_build_model(job, a):
    if not job.state.get("plan"):
        return "先调用 submit_plan 提交零件清单", []
    if not os.path.exists(job.file("model.py")):
        return "还没有 model.py，先用 write_file 写", []
    prev = job.state.get("build")
    rep = blender.run(job.cfg, "build", job.path)
    job.state["build"] = {"ok": bool(rep.get("ok")), "issues": rep.get("issues", []), "warnings": rep.get("warnings", []),
                          "parts": len(rep.get("parts", [])), "time": time.time()}
    job.state["build_stale"] = False
    job.state["page_stale"] = True
    job.state["check"] = None
    imgs = [job.out("sheet.png")] if rep.get("ok") and rep.get("image") else []
    text = format_build(rep)
    good = job.out("good_model.py")
    if rep.get("ok") and not rep.get("issues"):
        shutil.copyfile(job.file("model.py"), good)                 # 留一份没有问题的版本，改坏了可以退回来
        job.state["good_model_parts"] = len(rep.get("parts", []))
    extra = []
    if prev and prev.get("ok") and rep.get("ok"):
        fixed, fresh = compare_issues(prev.get("issues"), rep.get("issues"))
        if fixed or fresh:
            extra.append("和上一次构建比：解决了 %d 个问题，新出现 %d 个%s。" % (
                len(fixed), len(fresh), "（新出现的：%s）" % "；".join(_short(x) for x in fresh[:3]) if fresh else ""))
        lost = prev.get("parts", 0) - len(rep.get("parts", []))
        if lost > 0:
            extra.append("零件比上一次少了 %d 个。" % lost)
    # 连续两次比上一次更糟（问题变多，或者原来能跑现在跑不通），才提醒可以退回去
    n_now = len(rep.get("issues", [])) if rep.get("ok") else 10 ** 6
    n_prev = (len(prev.get("issues", [])) if prev.get("ok") else 10 ** 6) if prev else None
    if n_prev is not None and n_now > n_prev:
        job.state["worse_streak"] = job.state.get("worse_streak", 0) + 1
    elif n_prev is None or n_now < n_prev or n_now == 0:
        job.state["worse_streak"] = 0
    if job.state.get("worse_streak", 0) >= 2 and os.path.exists(good):
        extra.append("连续两次越改问题越多。上一个没有问题的 model.py 还留着（%d 个零件）：调用 restore(name=\"model.py\") 可以退回去，再一次只改一处。" % job.state.get("good_model_parts", 0))
    return text + ("\n" + "\n".join(extra) if extra else ""), imgs


def _err(rep):
    return rep.get("error", {}).get("msg", "失败") + ("\n" + rep["error"]["trace"] if rep.get("error", {}).get("trace") else "")


def t_look(job, a):
    e = _need_build(job)
    if e:
        return e, []
    args = ["--az", a.get("az", 35), "--el", a.get("el", 28)]
    if a.get("focus"):
        args += ["--focus", a["focus"]]
    rep = blender.run(job.cfg, "view", job.path, *args)
    if not rep.get("ok"):
        return _err(rep), []
    stale = "（注意：model.py 改过之后还没重新 build_model，这是上一次的模型）" if job.state.get("build_stale") else ""
    return "附图：az=%s el=%s%s 的视图。%s" % (a.get("az", 35), a.get("el", 28),
                                       "，对准 " + a["focus"] if a.get("focus") else "", stale), [job.out("view.png")]


def t_section(job, a):
    e = _need_build(job)
    if e:
        return e, []
    axis = str(a.get("axis", "x")).lower()
    if axis not in ("x", "y", "z"):
        return "axis 要写 x、y 或 z", []
    args = ["--axis", axis]
    if a.get("pos") is not None:
        args += ["--pos", a["pos"]]
    rep = blender.run(job.cfg, "section", job.path, *args)
    if not rep.get("ok"):
        return _err(rep), []
    legend = "，".join("%s=%s" % (x["part"], x["color"]) for x in rep.get("legend", [])) or "没有零件被切到"
    return ("附图：在 %s=%g 处剖开，去掉了 %s 更大的那一半，朝 -%s 方向看。切面颜色：%s。没被切到的零件保持原来的颜色。"
            % (axis, rep["pos"], axis, axis, legend)), [job.out("section.png")]


def t_measure(job, a):
    e = _need_build(job)
    if e:
        return e, []
    if not a.get("a"):
        return "至少给一个零件名 a", []
    args = ["--a", a["a"]] + (["--b", a["b"]] if a.get("b") else [])
    rep = blender.run(job.cfg, "measure", job.path, *args)
    if not rep.get("ok"):
        return _err(rep), []
    lines = []
    for it in rep["items"]:
        lines.append("%s：尺寸 %s mm，范围 x %g~%g  y %g~%g  z %g~%g，中心 %s，原点 %s，旋转(度) %s，体积 %g mm³%s" % (
            it["name"], _f(it["size"]), it["min"][0], it["max"][0], it["min"][1], it["max"][1], it["min"][2], it["max"][2],
            _p(it["center"]), _p(it["origin"]), _p(it["rotation_deg"]), it["volume"], "" if it["closed"] else "（网格没封闭）"))
    r = rep.get("relation")
    if r:
        d = r["center_delta_b_minus_a"]
        state = "穿模，最深约 %.2f mm" % r["penetration"] if r["penetration"] > 0.05 else \
            "接触" if r["gap"] <= 0.05 else "间隙配合，最近处相距约 %.2f mm" % r["gap"] if r["gap"] <= 0.25 else \
            "不接触，最近处相距约 %.2f mm" % r["gap"]
        lines.append("%s 和 %s：%s。%s 的中心相对 %s 的中心偏移 %s。" % (a["a"], a["b"], state, a["b"], a["a"], _p(d)))
        if rep.get("note"):
            lines.append("（%s）" % rep["note"])
    return "\n".join(lines), []


def t_list_parts(job, a):
    e = _need_build(job)
    if e:
        return e, []
    parts, err = page.load_json(job.out("parts.json"))
    if err:
        return "还没有构建成功的模型", []
    lines = ["上次构建的零件（demo.json 里用英文名）："]
    for p in parts:
        lines.append("  %s「%s」 尺寸 %s  中心 %s%s" % (p["name"], p.get("cn") or "未登记", _f(p["size"]), _p(p["center"]),
                                                   "  爆炸方向 %s" % _p(p["explode"]) if p.get("explode") else ""))
    return "\n".join(lines), []


def t_build_page(job, a):
    b = job.state.get("build")
    if not b or not b.get("ok"):
        return "模型还没构建成功，先把 build_model 跑通", []
    if job.state.get("build_stale"):
        return "model.py 改过之后还没重新 build_model，先构建", []
    if not os.path.exists(job.file("demo.json")):
        return "还没有 demo.json。先 lib_help(\"demo\") 看写法，再用 write_file 写", []
    r = page.build(job.path)
    job.state["page"] = {"ok": r["ok"], "errors": r["errors"]}
    job.state["page_stale"] = not r["ok"]
    job.state["check"] = None
    lines = []
    if r["ok"]:
        lines.append("网页已生成：out/index.html（%d KB）。下一步：check_page" % r["kb"])
    else:
        lines.append("demo.json 有 %d 处错误，网页没有生成：" % len(r["errors"]))
        lines += ["  ✗ " + e for e in r["errors"][:20]]
    if r["warnings"]:
        lines.append("提醒：")
        lines += ["  ! " + w for w in r["warnings"][:10]]
    return "\n".join(lines), []


def t_check_page(job, a):
    if job.state.get("page_stale") or not (job.state.get("page") or {}).get("ok"):
        return "网页还没生成，或者文件改过之后没有重新生成。先 build_page", []
    r = browser.check(job.path, job.cfg)
    # 运动检查：动起来以后会不会穿模、贴着的零件会不会离开、铰点和转轴上有没有东西；再算出运动范围
    range_lines = []
    cfg_demo, _ = page.load_json(job.file("demo.json"))
    if cfg_demo and any(isinstance(s_, dict) and s_.get("anim") for s_ in cfg_demo.get("steps", [])):
        mo = blender.run(job.cfg, "motion", job.path)
        probs = list(mo.get("problems", []))
        if any("穿模" in x for x in probs):
            probs.append("（动起来穿模的常见原因——齿轮、蜗轮蜗杆、皮带轮：转向反了或者速比不对，把其中一个的 speed 取负，或者核对齿数比；"
                         "连杆：铰点写得和模型里的真实位置不一样，或者运动的零件路上有东西挡着，给被撞的零件开槽或挪开）")
        parts_now, _ = page.load_json(job.out("parts.json"))
        probs += text_number_problems(cfg_demo, parts_now or [], mo.get("ranges", []))
        if probs:
            r["errors"] = r["errors"] + probs
            r["ok"] = False
        r["warnings"] += list(mo.get("warnings", [])) + list(mo.get("notes", []))
        if not mo.get("ok") and mo.get("error"):
            r["warnings"].append("运动检查没跑起来：%s" % mo["error"].get("msg", ""))
        for rg in mo.get("ranges", []):
            range_lines += ["  第 %d 步：%s" % (rg["step"], ln) for ln in rg["lines"]]
    prev_ck = job.state.get("check_last")
    job.state["check"] = {"ok": r["ok"], "errors": r["errors"], "warnings": r["warnings"]}
    job.state["check_last"] = {"ok": r["ok"], "errors": r["errors"]}
    good_demo = job.out("good_demo.json")
    if r["ok"]:
        shutil.copyfile(job.file("demo.json"), good_demo)
    lines = []
    info = r.get("info") or {}
    if r["ok"]:
        lines.append("网页检查通过：%s 步、%s 个零件，没有报错。" % (info.get("steps", "?"), info.get("parts", "?")))
    else:
        lines.append("网页检查发现问题：")
        lines += ["  ✗ " + e for e in r["errors"][:15]]
    if r["warnings"]:
        lines.append("提醒：")
        lines += ["  ! " + w for w in r["warnings"][:10]]
    if range_lines:
        lines.append("运动范围（按模型和动画算出来的，网页里写的数字要和它一致）：")
        lines += range_lines[:14]
    if prev_ck:
        fixed, fresh = compare_issues(prev_ck.get("errors"), r["errors"])
        if fixed or fresh:
            lines.append("和上一次检查比：解决了 %d 个问题，新出现 %d 个%s。" % (
                len(fixed), len(fresh), "（新出现的：%s）" % "；".join(_short(x) for x in fresh[:3]) if fresh else ""))
        if prev_ck.get("ok") and not r["ok"] and os.path.exists(good_demo):
            lines.append("上一个通过检查的 demo.json 还留着：调用 restore(name=\"demo.json\") 可以退回去。")
    if not r["ok"]:
        lines.append("下一步：问题在 model.py 的，改完依次 build_model → build_page → check_page；只在 demo.json 的，改完 build_page → check_page。")
    names = {"page_desktop.png": "电脑上的第 1 步", "page_last.png": "电脑上的最后一步", "page_mobile.png": "手机上的第 1 步"}
    imgs = [job.out(n) for n in r["images"]]
    if imgs:
        lines.append("附图：" + "、".join(names.get(n, n) for n in r["images"]) +
                     "。看一下：模型有没有显示完整、文字有没有挤在一起、视角合不合适。")
    return "\n".join(lines), imgs


def t_calc(job, a):
    args = {}
    for k, v in a.items():
        if isinstance(v, str) and k != "kind":
            try:
                v = float(v)
            except ValueError:
                if v.strip().lower() in ("true", "false"):
                    v = v.strip().lower() == "true"
        args[k] = v
    return calc.run(args), []


def t_restore(job, a):
    name = a.get("name")
    src = {"model.py": job.out("good_model.py"), "demo.json": job.out("good_demo.json")}.get(name)
    if src is None:
        return "restore 只能退回 model.py 或 demo.json，现在写的是 %r" % (name,), []
    if not os.path.exists(src):
        return "%s 还没有通过检查的版本可以退回。继续改现在这一版" % name, []
    shutil.copyfile(src, job.file(name))
    _touch(job, name)
    n = len(open(job.file(name), encoding="utf-8-sig").read().splitlines())
    return "已把 %s 退回到上一个通过检查的版本（%d 行）。下一步：%s" % (
        name, n, "build_model，然后一次只改一处" if name == "model.py" else "build_page → check_page"), []


def problems(job):
    """现在还挡着 finish 的问题。"""
    st = job.state
    out = []
    b = st.get("build")
    if not b:
        return ["模型还没构建过"]
    if st.get("build_stale"):
        out.append("model.py 改过之后还没重新 build_model")
    elif not b.get("ok"):
        out.append("model.py 还跑不通")
    else:
        out += b.get("issues", [])
    if st.get("want_page"):
        pg, ck = st.get("page"), st.get("check")
        if not pg or not pg.get("ok") or st.get("page_stale"):
            out.append("网页还没生成成功（build_page）")
        elif not ck:
            out.append("网页生成后还没检查（check_page）")
        elif not ck.get("ok"):
            out += ck.get("errors", [])[:8]
    return out


def t_finish(job, a):
    left = problems(job)
    unresolved = str(a.get("unresolved") or "").strip()
    blocking = [p for p in left if "还没" in p or "跑不通" in p]
    if blocking:
        return "还不能结束：\n" + "\n".join("  ✗ " + p for p in blocking), []
    if left and not unresolved:
        return ("还有问题没解决：\n" + "\n".join("  ✗ " + p for p in left) +
                "\n继续修；确实修不了的，再调用 finish 并在 unresolved 里如实写明是哪些。"), []
    job.state.update({"finished": True, "summary": str(a.get("summary", "")), "unresolved": unresolved,
                      "left": left})
    return "已结束。", []


IMPL = {"submit_plan": t_submit_plan, "lib_help": t_lib_help, "search_examples": t_search_examples,
        "search_bpy": t_search_bpy, "read_file": t_read_file, "write_file": t_write_file, "edit_file": t_edit_file,
        "calc": t_calc, "restore": t_restore, "build_model": t_build_model, "look": t_look, "section": t_section, "measure": t_measure,
        "list_parts": t_list_parts, "build_page": t_build_page, "check_page": t_check_page, "finish": t_finish}


def specs(want_page=True):
    if want_page:
        return SPECS
    return [s for s in SPECS if s["function"]["name"] not in ("build_page", "check_page")]


def call(job, name, args):
    if name not in IMPL:
        close = difflib.get_close_matches(str(name), list(IMPL), n=2, cutoff=0.5)
        return "没有叫 %s 的工具。%s" % (name, "是不是想用 " + " 或 ".join(close) if close else "可用：" + "、".join(IMPL)), []
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            return "工具参数不是合法的 JSON，重新调用", []
    if not isinstance(args, dict):
        args = {}
    try:
        text, imgs = IMPL[name](job, args)
    except Exception as e:  # noqa
        text, imgs = "工具 %s 内部出错：%s: %s" % (name, type(e).__name__, e), []
    job.save()
    return text, [p for p in imgs if os.path.exists(p)]
