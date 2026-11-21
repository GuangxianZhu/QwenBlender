# -*- coding: utf-8 -*-
"""工具循环：模型 → 调工具 → 把结果（文字 + 图）喂回去 → …… 直到 finish。"""
import json
import os
import re
import sys
import time

from . import ollama, search, tools

SYSTEM = """你是一个机械建模助手，在用户的电脑上工作。你的任务：按用户的要求，用 Blender 做出三维模型，再做一个讲解它的网页演示。
你自己不会「看到」任何东西，全靠工具：写文件 → 运行 → 看返回的数字和图 → 修改。

# 工作流程（按顺序）
1. submit_plan：列出零件清单（英文名、中文名、作用、大概尺寸）和装配关系。
2. 写 model.py：先写一两个零件就 build_model，看报告和四视图；对了再加下一个。不要一口气写完。
3. 修到 build_model 的报告里没有「必须修的问题」，并且四视图看起来就是要做的东西。内部配合用 section 剖开确认。
4. list_parts 确认零件名 → lib_help("demo") 看写法 → 写 demo.json → build_page → check_page。
5. 修到 check_page 通过，看截图确认画面正常。check_page 会让动画真的走几步，报「动起来以后穿模」多半是转向反了（speed 取负）或速比不对。
6. finish。

# 建模约定
- model.py 第一行写 `from qblib import *`。单位毫米，角度是度，Z 朝上。
- 优先用 qblib 的函数拼零件；它做不出来的形状用 extrude（平面轮廓拉伸）、revolve（轮廓旋转）、cut/union（布尔）组合。
  实在不行才直接写 bpy / bmesh，写之前先 search_bpy 确认 API 名字。
- 基本体的原点在底面中心，向 +Z 生长。螺栓的原点在头部下表面，杆朝 -Z。
- 摆放用 at / move / rot / stack / beside，不要自己心算包围盒：stack(a, b) 把 a 叠到 b 上面，beside(a, b, "+x") 把 a 贴到 b 的 +X 侧。
- 齿轮的位置和对齿交给 mesh(g, ref, angle)，蜗轮蜗杆交给 mesh_worm，皮带交给 belt(p1, p2)，不要自己算相位和切点。
  这几个都要求轴线竖直：先在竖直状态下装好，需要横过来时再把相关零件一起 rot_about。
- 每个最终零件都用 part(obj, "EnglishName", cn="中文名", info="一两句作用说明") 登记，并用 mat(obj, "steel") 上材质。
- 做刀具用的临时物体（被 cut 掉的）会自动删除，不用管。
- 尺寸定义成脚本开头的变量，后面都用变量算，方便改。

# 看结果
- 报告里的数字比图可靠：先看每个零件的尺寸、z 范围、接触了谁。
- 「穿模」= 两个零件互相扎进去，要改位置或尺寸。一个零件穿过另一个（轴穿板、螺杆穿臂），给被穿过的零件 hole() 打孔；
  allow_overlap(a, b) 只用于过盈配合这种本来就挤在一起的情况，重叠超过 1 mm 不认。
- hole() 的 pos 要落在零件表面上（孔口的位置），axis 是孔的方向："z" 竖着打，"x"、"y" 横着打。
  轴是横的，给它让路的孔也要横着打：轴沿 X，就 hole(支座, 孔径, pos=(支座侧面的 x, y, 轴的高度), axis="x")。
- 穿模报告里给了「最深的地方在 (x, y, z) 附近」，先看这个坐标落在哪个零件的哪个部位，再决定改谁。
- 圆柱、长方体转了方向以后，原点还在原来的底面中心。要让它居中，用 center_on(obj, 参照物, "xy") 或者看报告里的「中心」。
- 「悬空」= 零件不接触任何别的零件，一般是位置算错了。
- 四视图里：FRONT 是从 -Y 往 +Y 看，RIGHT 是从 +X 往 -X 看，TOP 是从上往下看。左下角的小箭头是坐标轴标记。
- 不确定某个地方，就用 look 换角度看，或者 measure 量。

# 网页演示
- 页面骨架是固定的，你只写 demo.json（讲解步骤、视角、高亮、动画、滑条）。写法看 lib_help("demo")。
- demo.json 里的零件名必须和 list_parts 返回的英文名一字不差。
- 讲解写给第一次见这个东西的人：4~7 步，每步 2~4 句，先说看到什么，再说为什么。数字要和模型一致。
- 要有至少一步用到爆炸图（explode）认零件；讲原理的步骤尽量配动画或滑条。
- 曲柄滑块、四连杆这类连杆机构，用 crank_slider / four_bar 动画，页面会自己解出各零件的位置，不要用 spin、move 去凑。

# 规矩
- 每次回复都要调用工具，直到 finish。不要只用文字描述你打算做什么。
- 一次只改一处，改完就验证。同一个错误连续两次没修好，换一种做法，或者用 lib_help / search_examples 查。
- 不要编造工具没有返回的结果。解决不了的问题在 finish 的 unresolved 里如实写出来。

# qblib 速查
{cheat}
"""

SYSTEM_NO_PAGE = "\n# 这次任务只要模型，不做网页：跳过第 4、5 步，模型没问题就 finish。\n"


def system_prompt(want_page=True):
    return SYSTEM.replace("{cheat}", search.cheat_sheet()) + ("" if want_page else SYSTEM_NO_PAGE)


class Console:
    """把过程打印到终端。"""

    def __init__(self, quiet=False):
        self.quiet = quiet
        self._kind = None

    def delta(self, kind, text):
        if self.quiet:
            return
        if kind != self._kind:
            sys.stdout.write("\n[思考] " if kind == "thinking" else "\n[回答] ")
            self._kind = kind
        sys.stdout.write(text)
        sys.stdout.flush()

    def line(self, text=""):
        self._kind = None
        if not self.quiet:
            print(text)
            sys.stdout.flush()


def parse_text_calls(content):
    """有的模型偶尔把工具调用写成文字：<tool_call>{…}</tool_call> 或 ```json {"name":…} ```。"""
    calls = []
    for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>|```(?:json)?\s*(\{.*?\})\s*```", content or "", re.S):
        raw = m.group(1) or m.group(2)
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        name = d.get("name") or (d.get("function") or {}).get("name")
        args = d.get("arguments", d.get("parameters", (d.get("function") or {}).get("arguments", {})))
        if isinstance(name, str) and name in tools.IMPL:
            calls.append({"function": {"name": name, "arguments": args if args is not None else {}}})
    return calls


def _strip_old_images(messages):
    """只保留最后一组图，旧图换成一句话（图很占上下文）。"""
    idx = [i for i, m in enumerate(messages) if m.get("images")]
    for i in idx[:-1]:
        messages[i].pop("images", None)
        messages[i]["content"] = "（这里原来有图，已经看过，移除了）"


def _compact(messages, keep_tail=8):
    """上下文快满时，把早先的长工具结果截短。"""
    n = 0
    for m in messages[1:-keep_tail]:
        if m.get("role") == "tool" and len(m.get("content", "")) > 500:
            m["content"] = m["content"][:300] + "\n…（较早的结果，后面省略）"
            n += 1
        if m.get("role") == "assistant" and len(m.get("content", "")) > 800:
            m["content"] = m["content"][:400] + "…"
    return n


def run(job, cfg, task=None, feedback=None, console=None, model=None):
    """跑一个任务。task：新任务的描述；feedback：对已有任务提的修改意见。返回 job.state。"""
    con = console or Console()
    model = model or ollama.pick_model(cfg)
    spec = tools.specs(job.state.get("want_page", True))
    log_path = job.file("messages.json")
    if feedback is not None and os.path.exists(log_path):
        messages = json.load(open(log_path, encoding="utf-8"))
        for m in messages:                       # 存盘时图已经去掉了
            if "images" in m:
                m.pop("images")
                m["content"] = "（这里原来有图，已经看过，移除了）"
        messages[0] = {"role": "system", "content": system_prompt(job.state.get("want_page", True))}
        job.state["finished"] = False
        messages.append({"role": "user", "content": "修改意见：%s\n请按意见修改，改完重新检查，再 finish。" % feedback})
    else:
        messages = [{"role": "system", "content": system_prompt(job.state.get("want_page", True))},
                    {"role": "user", "content": "任务：%s" % task}]
        with open(job.file("task.txt"), "w", encoding="utf-8") as f:
            f.write(task or "")
    con.line("模型：%s    任务目录：%s" % (model, job.path))
    nudges, t0, step = 0, time.time(), 0
    for step in range(1, int(cfg["max_steps"]) + 1):
        _strip_old_images(messages)
        con.line("\n──── 第 %d 轮 ────" % step)
        resp = ollama.chat(cfg, model, messages, spec, on_delta=con.delta)
        calls = resp["tool_calls"] or parse_text_calls(resp["content"])
        amsg = {"role": "assistant", "content": resp["content"]}
        if calls:
            amsg["tool_calls"] = calls
        messages.append(amsg)
        if resp["prompt_tokens"] > 0.75 * int(cfg["num_ctx"]):
            if _compact(messages):
                con.line("\n（上下文用了 %d / %d，已压缩较早的工具结果）" % (resp["prompt_tokens"], cfg["num_ctx"]))
        if not calls:
            nudges += 1
            if nudges > 3:
                con.line("\n模型连续几轮没有调用工具，停止。")
                break
            left = tools.problems(job)
            messages.append({"role": "user", "content": "请继续调用工具。" + (
                "现在还差：" + "；".join(left[:5]) if left else "都做完了就调用 finish。")})
            continue
        nudges = 0
        images = []
        for tc in calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments", {})
            shown = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
            con.line("\n[工具] %s %s" % (name, shown if len(shown) < 160 else shown[:160] + "…"))
            text, imgs = tools.call(job, name, args)
            con.line("[结果] " + (text if len(text) < 1500 else text[:1500] + "\n…"))
            messages.append({"role": "tool", "tool_name": name, "content": text})
            images += [(name, p) for p in imgs]
        if images:
            messages.append({"role": "user",
                             "content": "（系统）上面工具返回的图：" + "；".join("%s → %s" % (n, os.path.basename(p)) for n, p in images),
                             "images": [ollama.image_b64(p) for _, p in images]})
        slim = [dict(m, images=["…"] * len(m["images"])) if m.get("images") else m for m in messages]
        json.dump(slim, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if job.state.get("finished"):
            break
    else:
        con.line("\n到了最多 %d 轮的上限，停止。" % cfg["max_steps"])
    job.state["rounds"] = step
    job.state["seconds"] = round(time.time() - t0)
    job.save()
    return job.state
