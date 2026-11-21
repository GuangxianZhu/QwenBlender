# -*- coding: utf-8 -*-
"""命令行入口。

    python -m qb                      菜单
    python -m qb new "任务描述"        让 Qwen 做一个新任务（--no-page 只要模型）
    python -m qb fix <任务目录> "意见"  让 Qwen 按意见修改
    python -m qb selftest             自检（不用 Qwen）
    python -m qb trial ["任务"]       试跑：自检 + 同一个任务没有工具/有工具各做一遍，日志写到 jobs/trial_log.txt

下面这些是单个工具，不经过 Qwen，其他编程助手也可以直接调用：
    python -m qb build   <任务目录>          运行 model.py，打印报告，出四视图
    python -m qb look    <任务目录> az el [零件]
    python -m qb section <任务目录> x|y|z [位置]
    python -m qb measure <任务目录> A [B]
    python -m qb parts   <任务目录>
    python -m qb page    <任务目录>          校验 demo.json，生成网页
    python -m qb check   <任务目录>          浏览器检查网页
    python -m qb help    [函数名|demo|custom]
    python -m qb examples "关键词"
    python -m qb bpy "关键词"
"""
import os
import sys


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import agent, config, menu, search, selftest, tools
    cfg = config.load()
    if not argv:
        return menu.main()
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    if cmd == "trial":
        from . import trial
        return 0 if trial.main(cfg, task=rest[0] if rest else None) else 1
    if cmd == "selftest":
        return 0 if selftest.main(cfg, names=rest or None) else 1
    if cmd == "help":
        print(search.lib_help(" ".join(rest)))
        return 0
    if cmd == "examples":
        print(search.search_examples(" ".join(rest)))
        return 0
    if cmd == "bpy":
        print(search.search_bpy(" ".join(rest), cfg))
        return 0
    if cmd == "new":
        want_page = "--no-page" not in rest
        rest = [r for r in rest if r != "--no-page"]
        if not rest:
            print("用法：python -m qb new \"任务描述\"")
            return 2
        job = tools.Job(menu.new_job_dir(cfg, rest[0]), cfg, want_page=want_page)
        menu.report(job, agent.run(job, cfg, task=rest[0]))
        return 0
    if cmd == "fix":
        job = tools.Job(rest[0], cfg)
        menu.report(job, agent.run(job, cfg, feedback=rest[1]))
        return 0
    single = {"build": "build_model", "look": "look", "section": "section", "measure": "measure",
              "parts": "list_parts", "page": "build_page", "check": "check_page"}
    if cmd in single:
        if not rest or not os.path.isdir(rest[0]):
            print("要给任务目录（里面有 model.py）")
            return 2
        job = tools.Job(rest[0], cfg)
        job.state["plan"] = True
        a = rest[1:]
        args = {}
        if cmd == "look":
            args = {"az": float(a[0]) if a else 35, "el": float(a[1]) if len(a) > 1 else 28}
            if len(a) > 2:
                args["focus"] = a[2]
        elif cmd == "section":
            args = {"axis": a[0] if a else "x"}
            if len(a) > 1:
                args["pos"] = float(a[1])
        elif cmd == "measure":
            args = {"a": a[0] if a else ""}
            if len(a) > 1:
                args["b"] = a[1]
        text, imgs = tools.call(job, single[cmd], args)
        print(text)
        for p in imgs:
            print("图：" + p)
        return 0
    print("不认识的命令 %s\n%s" % (cmd, __doc__))
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
