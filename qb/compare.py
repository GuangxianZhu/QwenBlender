# -*- coding: utf-8 -*-
"""对比：同一个任务、同一个模型，分别在「没有工具」和「有工具」两种条件下做一遍，用同一把尺子量结果。

没有工具：Qwen 只回答一次，直接写出 Blender 脚本和网页，没有零件库、没有报告和图的反馈、没有修改机会。
有工具：  完整的工具循环。
"""
import json
import os
import re
import time

from . import agent, blender, browser, menu, ollama, tools

BASE_PROMPT = """任务：{task}

请一次写完下面两个文件，不要解释，也不要省略代码。

1. model.py：Blender 的 Python 脚本（import bpy），在空场景里把模型建出来。
   单位：1 个 Blender 单位 = 1 毫米，Z 朝上。每个零件是一个独立的网格物体，起英文名字。
2. index.html：一个单文件网页，用 three.js（从 CDN 引入）做一个讲解这个东西的 3D 演示，
   要有分步讲解的文字，手机上也能看。

输出格式（只要这两个代码块）：
```python
# model.py
...
```
```html
<!-- index.html -->
...
```"""


def _blocks(text):
    py = re.findall(r"```(?:python|py)\s*\n(.*?)```", text, re.S)
    html = re.findall(r"```html\s*\n(.*?)```", text, re.S)
    if not html:
        m = re.search(r"(<!DOCTYPE html.*?</html>)", text, re.S | re.I)
        html = [m.group(1)] if m else []
    return (max(py, key=len) if py else ""), (max(html, key=len) if html else "")


def run_baseline(cfg, model, task, job_dir, con):
    """没有工具的一次性回答。返回结果字典。"""
    os.makedirs(os.path.join(job_dir, "out"), exist_ok=True)
    t0 = time.time()
    resp = ollama.chat(cfg, model, [{"role": "user", "content": BASE_PROMPT.format(task=task)}], None, on_delta=con.delta)
    con.line("")
    secs = round(time.time() - t0)
    with open(os.path.join(job_dir, "reply.md"), "w", encoding="utf-8") as f:
        f.write(resp["content"])
    py, html = _blocks(resp["content"])
    res = {"seconds": secs, "rounds": 1, "output_tokens": resp["output_tokens"], "has_py": bool(py), "has_html": bool(html)}
    if py:
        with open(os.path.join(job_dir, "model.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(py)
        rep = blender.run(cfg, "build", job_dir)
        res["build"] = rep
        con.line(tools.format_build(rep))
    if html:
        hp = os.path.join(job_dir, "out", "index.html")
        with open(hp, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        res["page"] = browser.check_plain(hp, os.path.join(job_dir, "out"), cfg)
        con.line("网页检查：%s" % ("没有报错" if res["page"]["ok"] else "；".join(res["page"]["errors"][:6])))
    return res


def _row(name, r):
    b = r.get("build") or {}
    pg = r.get("page") or {}
    if not r.get("has_py", True):
        model = "没写出脚本"
    elif not b.get("ok"):
        e = b.get("error", {})
        model = "脚本跑不通：%s %s" % (e.get("type", ""), str(e.get("msg", ""))[:60])
    else:
        model = "跑通，%d 个零件，必须修的问题 %d 个，提醒 %d 个" % (len(b.get("parts", [])), len(b.get("issues", [])), len(b.get("warnings", [])))
    if not r.get("has_html", True):
        page = "没写出网页"
    elif not pg:
        page = "没生成"
    else:
        page = "没有报错" if pg.get("ok") else "%d 处报错" % len(pg.get("errors", []))
    return "| %s | %s 秒 | %s | %s | %s |" % (name, r.get("seconds", "?"), r.get("rounds", "?"), model, page)


def main(cfg, task, model=None, con=None):
    con = con or agent.Console()
    model = model or ollama.pick_model(cfg)
    root = os.path.join(cfg["jobs_dir"], time.strftime("compare_%Y%m%d_%H%M%S"))
    a_dir, b_dir = os.path.join(root, "A_no_tools"), os.path.join(root, "B_with_tools")
    os.makedirs(a_dir)
    with open(os.path.join(root, "task.txt"), "w", encoding="utf-8") as f:
        f.write(task)
    con.line("对比目录：%s\n模型：%s\n任务：%s" % (root, model, task))

    con.line("\n===== A：没有工具（只回答一次）=====")
    try:
        a = run_baseline(cfg, model, task, a_dir, con)
    except ollama.OllamaError as e:
        con.line("A 出错：%s" % e)
        a = {"seconds": 0, "rounds": 1, "has_py": False, "has_html": False, "error": str(e)}
    json.dump(a, open(os.path.join(a_dir, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    con.line("COMPARE_A_DONE")

    con.line("\n===== B：有工具 =====")
    job = tools.Job(b_dir, cfg)
    try:
        st = agent.run(job, cfg, task=task, model=model, console=con)
    except ollama.OllamaError as e:
        con.line("B 出错：%s" % e)
        st = dict(job.state, error=str(e))
    rep, _ = (None, None)
    try:
        rep = json.load(open(job.out("report.json"), encoding="utf-8"))
    except Exception:  # noqa
        rep = {"ok": False, "error": {"type": "", "msg": "没有构建结果"}}
    ck = st.get("check")
    b = {"seconds": st.get("seconds"), "rounds": st.get("rounds"), "has_py": os.path.exists(job.file("model.py")),
         "has_html": os.path.exists(job.out("index.html")), "build": rep,
         "page": ({"ok": ck.get("ok"), "errors": ck.get("errors", [])} if ck else None),
         "finished": st.get("finished"), "summary": st.get("summary"), "unresolved": st.get("unresolved")}
    json.dump(b, open(os.path.join(b_dir, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = ["# 有工具和没有工具的对比", "", "任务：" + task, "", "模型：" + model, "",
             "| 条件 | 用时 | 轮数 | 模型 | 网页 |", "|---|---|---|---|---|", _row("A 没有工具", a), _row("B 有工具", b), ""]
    for tag, d, r in (("A 没有工具", "A_no_tools", a), ("B 有工具", "B_with_tools", b)):
        lines += ["## " + tag, ""]
        bd = r.get("build") or {}
        if bd.get("ok"):
            for p in bd["parts"]:
                lines.append("- %s %s：%s mm" % (p["name"], p.get("cn", ""), "×".join("%g" % x for x in p["size"])))
            lines += ["", "必须修的问题：" + ("；".join(bd["issues"]) or "无"), "", "提醒：" + ("；".join(bd["warnings"]) or "无"), ""]
        elif bd:
            lines += ["脚本出错：%s" % json.dumps(bd.get("error", {}), ensure_ascii=False)[:400], ""]
        pg = r.get("page") or {}
        if pg.get("errors"):
            lines += ["网页报错：" + "；".join(pg["errors"][:8]), ""]
        for img in ("sheet.png", "page_desktop.png", "page_mobile.png"):
            if os.path.exists(os.path.join(root, d, "out", img)):
                lines.append("![%s](%s/out/%s)" % (img, d, img))
        lines.append("")
    if b.get("unresolved"):
        lines += ["B 自己报告没解决的问题：" + b["unresolved"], ""]
    with open(os.path.join(root, "compare.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    con.line("\n" + "\n".join(lines[:11]))
    con.line("对比报告：" + os.path.join(root, "compare.md"))
    for d in (a_dir, b_dir):
        h = os.path.join(d, "out", "index.html")
        if os.path.exists(h):
            menu._open(h)
    return root, a, b
