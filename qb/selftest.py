# -*- coding: utf-8 -*-
"""自检：不需要 Qwen。把范例跑一遍，确认 Blender、网页生成、浏览器检查这条链路是通的。"""
import glob
import os
import shutil
import time

from . import blender, browser, config, page, tools
from .config import ROOT


def main(cfg=None, names=None, keep=True):
    cfg = cfg or config.load()
    kind, exe = blender.find_blender(cfg)
    print("Blender：%s" % (exe if kind else "没找到：" + exe))
    if not kind:
        return False
    ok_all = True
    for d in sorted(glob.glob(os.path.join(ROOT, "examples", "*", "model.py"))):
        name = os.path.basename(os.path.dirname(d))
        if names and name not in names:
            continue
        job_dir = os.path.join(cfg["jobs_dir"], "_selftest_" + name)
        shutil.rmtree(job_dir, ignore_errors=True)
        os.makedirs(job_dir)
        for f in ("model.py", "demo.json", "custom.js"):
            src = os.path.join(os.path.dirname(d), f)
            if os.path.exists(src):
                shutil.copy(src, job_dir)
        job = tools.Job(job_dir, cfg)
        job.state["plan"] = True
        t = time.time()
        text, imgs = tools.call(job, "build_model", {})
        b = job.state["build"]
        good = b["ok"] and not b["issues"]
        print("\n[%s] 建模 %s（%.0f 秒，%d 个零件）" % (name, "通过" if good else "有问题", time.time() - t, b["parts"]))
        if not good:
            print(text)
            ok_all = False
            continue
        if b["warnings"]:
            print("  提醒：" + "；".join(b["warnings"]))
        r = page.build(job_dir)
        print("[%s] 网页 %s%s" % (name, "生成成功" if r["ok"] else "生成失败", "" if r["ok"] else "：" + "；".join(r["errors"])))
        if not r["ok"]:
            ok_all = False
            continue
        t = time.time()
        c = browser.check(job_dir, cfg)
        print("[%s] 浏览器检查 %s（%.0f 秒）%s" % (name, "通过" if c["ok"] else "有问题", time.time() - t,
                                             "" if c["ok"] else "：" + "；".join(c["errors"])))
        for w in c["warnings"]:
            print("  提醒：" + w)
        ok_all = ok_all and c["ok"]
        print("  输出：" + os.path.join(job_dir, "out", "index.html"))
    print("\n自检结果：" + ("全部通过" if ok_all else "有没通过的项，见上面"))
    return ok_all
