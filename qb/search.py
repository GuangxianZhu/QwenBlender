# -*- coding: utf-8 -*-
"""查资料：零件库说明、范例、Blender API 索引。都在本机查，不联网。"""
import ast
import glob
import json
import os
import re

from .config import ROOT

LIB = os.path.join(ROOT, "blender", "qblib.py")
GROUPS = [
    ("基本体", "box rounded_box cylinder cone tube sphere torus prism extrude revolve pipe spring"),
    ("机械件", "hex_bolt socket_screw nut screw_on washer threaded_rod bearing flange l_bracket bent_plate link_bar"),
    ("传动件", "spur_gear helical_gear ring_gear mesh worm worm_wheel mesh_worm pulley belt"),
    ("加工", "union cut intersect hole holes_circle bevel chamfer"),
    ("铰接", "pin_joint shaft_through"),
    ("摆放", "at move rot rot_about aim on_axis stack beside center_on copy mirror_copy array_circular array_linear join delete"),
    ("信息", "bbox part mat color allow_overlap allow_float"),
]
_lib_cache = None


def lib_functions():
    """{名字: (签名, 说明)}，从 qblib.py 的源码里读（不需要 Blender）。"""
    global _lib_cache
    if _lib_cache is None:
        src = open(LIB, encoding="utf-8").read()
        tree = ast.parse(src)
        out = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                seg = ast.get_source_segment(src, node) or ""
                sig = seg.split(":\n", 1)[0].replace("def ", "", 1)
                sig = re.sub(r"\s+", " ", sig)
                out[node.name] = (sig, ast.get_docstring(node) or "")
        mats = re.search(r"MATERIALS = \{(.*?)\n\}", src, re.S)
        out["__materials__"] = ("", " ".join(re.findall(r'"(\w+)":', mats.group(1))) if mats else "")
        _lib_cache = out
    return _lib_cache


def lib_names():
    return [k for k in lib_functions() if not k.startswith("__")]


def cheat_sheet():
    """一行一个函数的速查表（放进系统提示词）。"""
    fn = lib_functions()
    lines = []
    for title, names in GROUPS:
        lines.append("【%s】" % title)
        for n in names.split():
            if n in fn:
                sig, doc = fn[n]
                lines.append("  %s  — %s" % (sig, doc.split("\n")[0]))
    lines.append("【材质名】" + fn["__materials__"][1])
    return "\n".join(lines)


def _doc_file(name):
    p = os.path.join(ROOT, "docs", name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def lib_help(topic=""):
    fn = lib_functions()
    t = (topic or "").strip()
    if not t:
        return cheat_sheet() + "\n\n要看某个函数的完整说明：lib_help(\"函数名\")；网页配置：lib_help(\"demo\")；custom.js：lib_help(\"custom\")"
    if t.lower() in ("demo", "demo.json", "页面", "网页"):
        return _doc_file("demo_schema.md")
    if t.lower() in ("custom", "custom.js", "api"):
        return _doc_file("custom_api.md")
    if t.lower() in ("mat", "材质", "materials"):
        return "材质名：" + fn["__materials__"][1] + "\n用法：mat(obj, \"steel\")；自定义颜色：color(obj, \"#ff8800\", metal=0, rough=0.5)"
    out = []
    for name in re.split(r"[\s,，、]+", t):
        name = name.strip("()")
        if name in fn:
            out.append("%s\n%s" % fn[name])
        elif name:
            import difflib
            close = difflib.get_close_matches(name, lib_names(), n=4, cutoff=0.4)
            hits = [k for k in lib_names() if name.lower() in k.lower() or name in fn[k][1]]
            cand = list(dict.fromkeys(close + hits))[:6]
            out.append("没有叫 %s 的函数。" % name + ("相近的：" + "、".join(cand) if cand else "用 lib_help() 看全部"))
    return "\n\n".join(out)


# ------------------------------------------------------------------ 检索

def _tokens(q):
    q = q.lower()
    words = re.findall(r"[a-z0-9_]+", q)
    cjk = re.findall(r"[一-鿿]+", q)
    grams = []
    for w in cjk:
        grams += [w] if len(w) <= 2 else [w[i:i + 2] for i in range(len(w) - 1)]
    return words + grams


def _score(tokens, title, text):
    title_l, text_l = title.lower(), text.lower()
    s = 0.0
    for t in tokens:
        s += 4 * title_l.count(t) + min(5, text_l.count(t))
    return s


def search_examples(query, limit=2, max_lines=70):
    tokens = _tokens(query)
    docs = []
    for p in sorted(glob.glob(os.path.join(ROOT, "examples", "snippets", "*.py"))):
        docs.append((os.path.relpath(p, ROOT), open(p, encoding="utf-8").read()))
    for d in sorted(glob.glob(os.path.join(ROOT, "examples", "*", ""))):
        for f in ("model.py", "demo.json", "custom.js"):
            p = os.path.join(d, f)
            if os.path.exists(p):
                docs.append((os.path.relpath(p, ROOT), open(p, encoding="utf-8").read()))
    scored = []
    for path, text in docs:
        head = "\n".join(text.splitlines()[:3])
        sc = _score(tokens, path + " " + head, text)
        if sc > 0:
            scored.append((sc, path, text))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "没找到相关范例。现有范例：\n" + "\n".join("  " + p + "  " + t.splitlines()[0][:60] for p, t in docs)
    out = []
    for sc, path, text in scored[:limit]:
        lines = text.splitlines()
        body = "\n".join(lines[:max_lines]) + ("\n…（后面还有 %d 行）" % (len(lines) - max_lines) if len(lines) > max_lines else "")
        out.append("=== %s ===\n%s" % (path.replace("\\", "/"), body))
    more = [p.replace("\\", "/") for _, p, _ in scored[limit:limit + 5]]
    if more:
        out.append("其他相关的：" + "、".join(more))
    return "\n\n".join(out)


def _index_path(version):
    d = os.path.join(ROOT, "cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "bpy_index_%s.json" % re.sub(r"[^0-9A-Za-z.]", "_", version or "unknown"))


def search_bpy(query, cfg, limit=10):
    from . import blender
    files = sorted(glob.glob(os.path.join(ROOT, "cache", "bpy_index_*.json")))
    if not files:
        tmp = _index_path("tmp")
        r = blender.run(cfg, "index", tmp, timeout=180)
        if not r.get("ok"):
            return "Blender API 索引生成失败：%s" % (r.get("error", {}).get("msg", ""))
        final = _index_path(r.get("version", ""))
        os.replace(tmp, final)
        files = [final]
    data = json.load(open(files[-1], encoding="utf-8"))
    tokens = _tokens(query)
    scored = []
    for it in data["items"]:
        sc = _score(tokens, it["n"], it["s"] + " " + it["d"])
        if sc > 0:
            scored.append((sc - len(it["n"]) * 0.01, it))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "Blender %s 的 API 里没搜到 %r。换个英文关键词试试（比如 bevel、solidify、boolean、extrude）" % (data["version"], query)
    lines = ["Blender %s API（前 %d 条）：" % (data["version"], min(limit, len(scored)))]
    for _, it in scored[:limit]:
        lines.append("%s%s — %s" % (it["n"], (" " + it["s"]) if it["s"] else "", it["d"][:160]))
    return "\n".join(lines)
