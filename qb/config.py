# -*- coding: utf-8 -*-
"""配置：默认值 ← config.json（仓库根目录，可没有）← 环境变量。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "ollama_host": "http://127.0.0.1:11434",
    "model": "auto",            # auto = 在 Ollama 里找 qwen，优先 q8
    "num_ctx": 32768,
    "think": True,
    "temperature": 0.4,
    "request_timeout": 1800,    # 秒。预填充很长时不要掐断，掐断会让 Ollama 从头再算
    "max_steps": 80,
    "blender": "auto",          # blender.exe 的路径；auto = 自动找；python = 用装了 bpy 模块的当前 Python
    "blender_timeout": 300,
    "render_res": 512,          # 四视图里每一格的像素
    "render_samples": 16,
    "render_device": "cpu",     # cpu / gpu
    "browser": "auto",          # 浏览器 exe 路径；auto = Edge → Chrome → Playwright 自带
    "jobs_dir": "jobs",
}

ENV = {"OLLAMA_HOST": "ollama_host", "QB_MODEL": "model", "QB_BLENDER": "blender", "QB_BROWSER": "browser",
       "QB_NUM_CTX": "num_ctx", "QB_RENDER_DEVICE": "render_device", "QB_JOBS_DIR": "jobs_dir"}


def load():
    cfg = dict(DEFAULTS)
    path = os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except Exception as e:  # noqa
            print("config.json 读不了，先用默认配置：%s" % e)
    for env, key in ENV.items():
        v = os.environ.get(env)
        if v:
            cfg[key] = type(DEFAULTS[key])(v) if not isinstance(DEFAULTS[key], bool) else v not in ("0", "false")
    host = cfg["ollama_host"]
    if not host.startswith("http"):
        host = "http://" + host
    cfg["ollama_host"] = host.rstrip("/").replace("0.0.0.0", "127.0.0.1")
    if not os.path.isabs(cfg["jobs_dir"]):
        cfg["jobs_dir"] = os.path.join(ROOT, cfg["jobs_dir"])
    return cfg
