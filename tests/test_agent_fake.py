# -*- coding: utf-8 -*-
"""工具循环测试：用一个假的 Ollama（按剧本回复）把整条链路走一遍，不需要真模型。

    python tests/test_agent_fake.py

剧本里故意安排了几种出错情况，检查工具有没有把它们拦住并给出能用的提示。
"""
import base64
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qb import agent, config, tools  # noqa: E402

EX = os.path.join(ROOT, "examples", "bolt_joint")
GOOD_MODEL = open(os.path.join(EX, "model.py"), encoding="utf-8").read()
GOOD_DEMO = open(os.path.join(EX, "demo.json"), encoding="utf-8").read()
BAD_NAME = "from qblib import *\nplate = rounded_box(40, 40, 6, 4)\nbolt = hexbolt(8, 30)\n"
OVERLAP = ("from qblib import *\nplate = rounded_box(40, 40, 6, 4)\npart(plate, 'PlateLower', cn='下板')\n"
           "bolt = hex_bolt(8, 30, thread=False)\nat(bolt, 0, 0, 6)\npart(bolt, 'Bolt', cn='螺栓')\n")


def call(tool, **args):
    return {"function": {"name": tool, "arguments": args}}


PLAN = [{"name": n, "cn": c, "size": s} for n, c, s in (
    ("PlateLower", "下板", [40, 40, 6]), ("PlateUpper", "上板", [40, 40, 6]), ("WasherTop", "上垫圈", [16, 16, 1.6]),
    ("Bolt", "螺栓", [13, 15, 35]), ("WasherBottom", "下垫圈", [16, 16, 1.6]), ("Nut", "螺母", [13, 15, 6.4]))]

# 每一项：(模型这一轮的回复, 检查上一轮工具结果的函数)
SCRIPT = [
    ({"content": "我打算先做两块板。"}, None),                                   # 只说话不调工具 → 应该被催
    ({"tool_calls": [call("write_file", name="model.py", content=BAD_NAME)]}, lambda t: "请继续调用工具" in t),
    ({"tool_calls": [call("submit_plan", parts=PLAN, notes="螺栓从上往下穿")]}, lambda t: "submit_plan" in t),
    ({"tool_calls": [call("write_file", name="model.py", content=BAD_NAME)]}, lambda t: "计划已记录" in t),
    ({"tool_calls": [call("build_model")]}, lambda t: "已写入" in t),
    ({"tool_calls": [call("edit_file", name="model.py", old="hexbolt(8, 30)", new="hex_bolt(8, 30)"),
                     call("lib_help", topic="hex_bolt")]},
     lambda t: "第 3 行" in t and "hex_bolt" in t and "NameError" in t),      # 报错带行号，并提示相近的函数名
    ({"tool_calls": [call("write_file", name="model.py", content=OVERLAP)]}, lambda t: "六角头螺栓" in t),
    ({"tool_calls": [call("build_model")]}, None),
    ({"tool_calls": [call("measure", a="Bolt", b="PlateLower"), call("finish", summary="好了")]},
     lambda t: "穿模" in t and "Bolt" in t and "打孔" in t),                    # 螺栓直接插进没打孔的板，提示里说要打孔
    ({"tool_calls": [call("write_file", name="model.py", content=GOOD_MODEL)]},
     lambda t: "还不能结束" in t or "还有问题" in t),                               # finish 被拒绝
    ({"tool_calls": [call("build_model")]}, None),
    ({"tool_calls": [call("calc", kind="screw", pitch="1.25", turns=4), call("restore", name="model.py")]},
     lambda t: "构建成功：6 个零件" in t and "必须修的问题" not in t and "解决了" in t),   # 和上一次比，问题解决了
    ({"tool_calls": [call("build_model")]}, lambda t: "走 5 mm" in t and "已把 model.py 退回" in t),
    ({"tool_calls": [call("section", axis="x"), call("look", az=30, el=-20, focus="Nut"), call("list_parts")]},
     lambda t: "构建成功：6 个零件" in t and "必须修的问题" not in t),
    ({"tool_calls": [call("write_file", name="demo.json", content=GOOD_DEMO.replace('"part": "Nut", "type"', '"part": "Nutt", "type"'))]},
     lambda t: "WasherBottom" in t),
    ({"tool_calls": [call("build_page")]}, None),
    ({"tool_calls": [call("edit_file", name="demo.json", old='"part": "Nutt"', new='"part": "Nut"')]},
     lambda t: "Nutt" in t and "是不是想写 Nut" in t),                            # 零件名写错被指出来
    ({"tool_calls": [call("build_page")]}, None),
    ({"tool_calls": [call("check_page")]}, lambda t: "网页已生成" in t),
    # 最后一轮：把工具调用写成文字（有的模型偶尔会这样）
    ({"content": '<tool_call>{"name": "finish", "arguments": {"summary": "螺栓连接模型和 5 步讲解页面都做好了"}}</tool_call>'},
     lambda t: "网页检查通过" in t),
]

state = {"i": 0, "fail": [], "image_rounds": 0, "max_images": 0}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, ndjson=False):
        body = ("\n".join(json.dumps(o, ensure_ascii=False) for o in obj) + "\n") if ndjson else json.dumps(obj)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson" if ndjson else "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "gpt-oss:20b"}, {"name": "qwen3.8:27b"}, {"name": "qwen3.8:27b-q8_0"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        if self.path == "/api/show":
            return self._send({"capabilities": ["completion", "vision", "tools", "thinking"]})
        msgs = req["messages"]
        try:
            assert req["model"] == "qwen3.8:27b-q8_0", "应该自动选中 q8 的 qwen：%s" % req["model"]
            assert req["stream"] is True and req.get("think") is True and req["options"]["num_ctx"] > 0
            assert msgs[0]["role"] == "system" and "qblib 速查" in msgs[0]["content"]
            assert len(req["tools"]) == 17
            with_img = [m for m in msgs if m.get("images")]
            assert len(with_img) <= 1, "历史里应该只保留最后一组图"
            for m in with_img:
                assert m["role"] == "user"
                for b in m["images"]:
                    assert base64.b64decode(b)[:8] == b"\x89PNG\r\n\x1a\n", "图要是 PNG 的 base64"
                state["max_images"] = max(state["max_images"], len(m["images"]))
            if with_img:
                state["image_rounds"] += 1
            for m in msgs:
                if m["role"] == "tool":
                    assert m.get("tool_name") and isinstance(m["content"], str)
            i = state["i"]
            reply, check = SCRIPT[i]
            tail = []
            for m in reversed(msgs):                     # 上一轮助手消息之后的所有内容
                if m["role"] == "assistant":
                    break
                tail.append(m["content"])
            text = "\n".join(reversed(tail))
            if check and not check(text):
                state["fail"].append("第 %d 轮：上一轮的工具结果不符合预期：\n%s" % (i + 1, text[:700]))
        except AssertionError as e:
            state["fail"].append("第 %d 轮请求格式不对：%s" % (state["i"] + 1, e))
            reply = SCRIPT[min(state["i"], len(SCRIPT) - 1)][0]
        state["i"] += 1
        chunks = [{"message": {"role": "assistant", "thinking": "想一下…"}, "done": False}]
        if reply.get("content"):
            for k in range(0, len(reply["content"]), 40):
                chunks.append({"message": {"role": "assistant", "content": reply["content"][k:k + 40]}, "done": False})
        if reply.get("tool_calls"):
            chunks.append({"message": {"role": "assistant", "content": "", "tool_calls": reply["tool_calls"]}, "done": False})
        chunks.append({"message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": 4000 + 300 * state["i"], "eval_count": 100})
        self._send(chunks, ndjson=True)


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = config.load()
    cfg["ollama_host"] = "http://127.0.0.1:%d" % srv.server_address[1]
    cfg["model"] = "auto"
    d = os.path.join(tempfile.gettempdir(), "qb_test_agent")
    shutil.rmtree(d, ignore_errors=True)
    job = tools.Job(d, cfg)
    st = agent.run(job, cfg, task="做一个 M8 螺栓连接，讲清楚它为什么能夹紧", console=agent.Console(quiet="-v" not in sys.argv))
    srv.shutdown()
    for f in state["fail"]:
        print("✗ " + f)
    assert not state["fail"], "%d 处不符合预期" % len(state["fail"])
    assert state["i"] == len(SCRIPT), "剧本走了 %d / %d 轮" % (state["i"], len(SCRIPT))
    assert st["finished"] and not st.get("left"), st
    assert state["image_rounds"] >= 4 and state["max_images"] >= 3, state
    for f in ("out/model.glb", "out/sheet.png", "out/section.png", "out/view.png", "out/index.html",
              "out/page_desktop.png", "out/page_mobile.png", "messages.json", "plan.json", "state.json"):
        assert os.path.exists(os.path.join(d, f)), "缺少 " + f
    saved = json.load(open(os.path.join(d, "messages.json"), encoding="utf-8"))
    assert not any(len(x) > 10 for m in saved for x in m.get("images", [])), "存盘的对话里不应该带图片数据"
    print("test_agent_fake 通过：%d 轮，图片回传 %d 次，任务目录 %s" % (state["i"], state["image_rounds"], d))


if __name__ == "__main__":
    main()
