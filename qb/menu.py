# -*- coding: utf-8 -*-
"""双击 启动.bat 后看到的菜单。"""
import glob
import os
import re
import subprocess
import sys
import time
import webbrowser

from . import agent, blender, config, ollama, selftest, tools


def _open(path):
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        print("打不开，路径是：" + path)


def new_job_dir(cfg, task):
    """任务目录名只用英文和数字（任务描述存在 task.txt 里），路径里不带中文，各种工具都不会出岔子。"""
    slug = re.sub(r"[^0-9A-Za-z]+", "_", task).strip("_")[:24]
    base = os.path.join(cfg["jobs_dir"], time.strftime("%Y%m%d_%H%M%S") + ("_" + slug if slug else ""))
    path, k = base, 2
    while os.path.exists(path):
        path = "%s_%d" % (base, k)
        k += 1
    os.makedirs(path)
    return path


def task_of(job_dir, n=36):
    try:
        t = open(os.path.join(job_dir, "task.txt"), encoding="utf-8").read().strip().replace("\n", " ")
        return t[:n] + ("…" if len(t) > n else "")
    except OSError:
        return ""


def jobs(cfg):
    ds = [d for d in glob.glob(os.path.join(cfg["jobs_dir"], "*")) if os.path.isdir(d) and not os.path.basename(d).startswith("_")]
    return sorted(ds, key=os.path.getmtime, reverse=True)


def report(job, st):
    print("\n" + "=" * 60)
    left = tools.problems(job)
    if st.get("finished"):
        print("做完了（%s 轮，%s 秒）。" % (st.get("rounds", "?"), st.get("seconds", "?")))
        if st.get("summary"):
            print("模型的总结：" + st["summary"])
        if st.get("unresolved") or st.get("left"):
            print("模型自己报告没解决的问题：" + (st.get("unresolved") or ""))
            for p in st.get("left") or []:
                print("  - " + p)
    else:
        print("没做完就停了（%s 轮）。现在还差：" % st.get("rounds", "?"))
        for p in left:
            print("  - " + p)
    print("任务文件夹：" + job.path)
    html = job.out("index.html")
    if os.path.exists(html):
        print("网页：" + html)
        _open(html)
    elif os.path.exists(job.out("sheet.png")):
        _open(job.out("sheet.png"))


def status(cfg):
    kind, exe = blender.find_blender(cfg)
    print("Blender：" + (exe if kind else "没找到  ← " + exe))
    try:
        model = ollama.pick_model(cfg)
        caps = ollama.capabilities(cfg, model)
        miss = [c for c in ("tools", "vision") if caps and c not in caps]
        print("Ollama ：已连接，模型 %s%s" % (model, "  ← 这个模型缺少能力：" + "、".join(miss) if miss else ""))
        return model
    except ollama.OllamaError as e:
        print("Ollama ：" + str(e))
        return None


def main():
    cfg = config.load()
    print("QwenBlender —— 让本地 Qwen 建模、做网页演示\n")
    model = status(cfg)
    while True:
        print("\n  1  新任务（模型 + 网页演示）")
        print("  2  新任务（只要模型）")
        print("  3  给上一个任务提修改意见")
        print("  4  自检（不用 Qwen，检查 Blender 和浏览器能不能用）")
        print("  5  打开任务文件夹")
        print("  0  退出")
        try:
            c = input("\n选一个数字：").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if c == "0" or c == "":
            return
        try:
            if c in ("1", "2"):
                task = input("要做什么？（一句话，可以写尺寸和要讲的重点）\n> ").strip()
                if not task:
                    continue
                model = model or ollama.pick_model(cfg)
                job = tools.Job(new_job_dir(cfg, task), cfg, want_page=(c == "1"))
                report(job, agent.run(job, cfg, task=task, model=model))
            elif c == "3":
                js = jobs(cfg)
                if not js:
                    print("还没有任务。")
                    continue
                for i, d in enumerate(js[:8], 1):
                    print("  %d  %s  %s" % (i, os.path.basename(d), task_of(d)))
                k = input("哪一个？（直接回车 = 1）").strip() or "1"
                if not k.isdigit() or not 1 <= int(k) <= len(js[:8]):
                    continue
                fb = input("修改意见：\n> ").strip()
                if not fb:
                    continue
                model = model or ollama.pick_model(cfg)
                job = tools.Job(js[int(k) - 1], cfg)
                report(job, agent.run(job, cfg, feedback=fb, model=model))
            elif c == "4":
                selftest.main(cfg)
            elif c == "5":
                os.makedirs(cfg["jobs_dir"], exist_ok=True)
                _open(cfg["jobs_dir"])
        except ollama.OllamaError as e:
            print("\n" + str(e))
        except KeyboardInterrupt:
            print("\n已中断，回到菜单。")
