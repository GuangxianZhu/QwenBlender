# -*- coding: utf-8 -*-
"""试跑：不用输入任何东西。先自检，再让 Qwen 把同一个任务在「没有工具」和「有工具」两种条件下各做一遍，
全过程写进 jobs/trial_log.txt，对比结果在 jobs/compare_时间/compare.md。"""
import os
import platform
import sys
import time
import traceback

from . import menu, ollama, selftest

TASK = ("做一个 C 形夹（G 字夹）：一个 C 形的夹体，开口大约 50 mm；一根 M8 丝杆竖着穿过夹体下臂的孔；"
        "丝杆顶端有一个圆形压块，丝杆下端横穿一根手柄。"
        "网页演示讲清楚：转手柄，丝杆为什么会往上走并把工件夹紧。")


class Tee:
    def __init__(self, stream, path):
        self.stream = stream
        self.f = open(path, "w", encoding="utf-8", newline="\n")

    def write(self, s):
        try:
            self.stream.write(s)
        except Exception:  # noqa
            pass
        self.f.write(s)
        self.f.flush()
        return len(s)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:  # noqa
            pass
        self.f.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def main(cfg, task=None):
    os.makedirs(cfg["jobs_dir"], exist_ok=True)
    tf = os.path.join(cfg["jobs_dir"], "trial_task.txt")      # 想换题目：把任务写进 jobs/trial_task.txt
    if not task and os.path.exists(tf):
        task = open(tf, encoding="utf-8-sig").read().strip() or None
    opts = {}                                                 # 可选：jobs/trial_options.json
    of = os.path.join(cfg["jobs_dir"], "trial_options.json")  # {"selftest": false, "a_think": false, "only": "a"}
    if os.path.exists(of):
        try:
            import json
            opts = json.load(open(of, encoding="utf-8-sig"))
        except Exception:  # noqa
            opts = {}
    log = os.path.join(cfg["jobs_dir"], "trial_log.txt")
    old = sys.stdout
    sys.stdout = Tee(old, log)
    result = "error"
    try:
        print("试跑开始 %s  %s  Python %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), platform.platform(), platform.python_version()))
        model = menu.status(cfg)
        if opts.get("selftest", True):
            print("\n===== 第一部分：自检（不用 Qwen）=====")
            ok = selftest.main(cfg)
            print("TRIAL_SELFTEST %s" % ("ok" if ok else "failed"))
        if model is None:
            print("Ollama 连不上或没有 qwen 模型，第二部分跳过。")
            result = "no_model"
            return False
        print("\n===== 第二部分：同一个任务，没有工具和有工具各做一遍 =====")
        from . import compare
        import re
        tasks = [t.strip() for t in re.split(r"(?m)^\s*-{3,}\s*$", task or TASK) if t.strip()]   # 多道题用一行 --- 隔开
        done = []
        for i, one in enumerate(tasks, 1):
            if len(tasks) > 1:
                print("\n########## 第 %d / %d 道题 ##########" % (i, len(tasks)))
            root, a, b = compare.main(cfg, one, model=model, a_think=opts.get("a_think"), only=opts.get("only"))
            done.append(bool(b.get("finished")))
            print("TRIAL_TASK_DONE %d %s %s" % (i, "finished" if done[-1] else "stopped", root))
        result = "finished" if all(done) else "stopped"
        return all(done)
    except ollama.OllamaError as e:
        print("\nOllama 出错：%s" % e)
        return False
    except BaseException as e:  # noqa
        print("\n试跑中断：%s: %s" % (type(e).__name__, e))
        print(traceback.format_exc())
        return False
    finally:
        print("\nTRIAL_END %s %s" % (result, time.strftime("%H:%M:%S")))
        sys.stdout = old
        print("日志：" + log)
