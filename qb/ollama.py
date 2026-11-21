# -*- coding: utf-8 -*-
"""Ollama 原生接口 /api/chat（流式，带工具）。只用标准库。"""
import base64
import json
import urllib.error
import urllib.request


class OllamaError(Exception):
    pass


def _get(cfg, path, timeout=5):
    with urllib.request.urlopen(cfg["ollama_host"] + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_models(cfg):
    try:
        return [m["name"] for m in _get(cfg, "/api/tags").get("models", [])]
    except Exception as e:  # noqa
        raise OllamaError("连不上 Ollama（%s）：%s。先打开 Ollama，或者运行 ollama serve" % (cfg["ollama_host"], e))


def pick_model(cfg):
    """config 里写了就用写的；auto 就在已下载的模型里挑 qwen（优先 q8，其次名字靠后的新版本）。"""
    names = list_models(cfg)
    want = cfg.get("model", "auto")
    if want and want != "auto":
        if want in names or want + ":latest" in names:
            return want
        raise OllamaError("Ollama 里没有模型 %s。已有：%s" % (want, "、".join(names) or "（空）"))
    qwen = [n for n in names if "qwen" in n.lower() and "embed" not in n.lower()]
    if not qwen:
        raise OllamaError("Ollama 里没找到 qwen 模型。已有：%s。可以在 config.json 里用 \"model\" 指定" % ("、".join(names) or "（空）"))
    qwen.sort(key=lambda n: (("q8" in n.lower()), n), reverse=True)
    return qwen[0]


def capabilities(cfg, model):
    try:
        req = urllib.request.Request(cfg["ollama_host"] + "/api/show", data=json.dumps({"model": model}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")).get("capabilities", [])
    except Exception:  # noqa
        return []


def image_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def chat(cfg, model, messages, tools, on_delta=None, think=None, _retry=False):
    """发一轮对话，返回 {'content', 'thinking', 'tool_calls', 'prompt_tokens', 'output_tokens'}。
    on_delta(kind, text)：kind 是 'thinking' 或 'content'，流式输出用。"""
    body = {"model": model, "messages": messages, "stream": True, "keep_alive": "30m",
            "options": {"num_ctx": int(cfg["num_ctx"]), "temperature": float(cfg["temperature"])}}
    if tools:
        body["tools"] = tools
    use_think = cfg.get("think", True) if think is None else think
    if not _retry:
        body["think"] = bool(use_think)  # 不写的话，带思考能力的模型默认是开着的，所以关也要明说
    req = urllib.request.Request(cfg["ollama_host"] + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    out = {"content": "", "thinking": "", "tool_calls": [], "prompt_tokens": 0, "output_tokens": 0}
    try:
        with urllib.request.urlopen(req, timeout=cfg["request_timeout"]) as r:
            for raw in r:
                raw = raw.strip()
                if not raw:
                    continue
                ch = json.loads(raw.decode("utf-8"))
                if ch.get("error"):
                    raise OllamaError(ch["error"])
                m = ch.get("message") or {}
                if m.get("thinking"):
                    out["thinking"] += m["thinking"]
                    if on_delta:
                        on_delta("thinking", m["thinking"])
                if m.get("content"):
                    out["content"] += m["content"]
                    if on_delta:
                        on_delta("content", m["content"])
                for tc in m.get("tool_calls") or []:
                    out["tool_calls"].append(tc)
                if ch.get("done"):
                    out["prompt_tokens"] = ch.get("prompt_eval_count", 0)
                    out["output_tokens"] = ch.get("eval_count", 0)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(msg).get("error", msg)
        except ValueError:
            pass
        if "think" in msg.lower() and not _retry:        # 模型不支持思考开关：去掉这个字段再发一次
            return chat(cfg, model, messages, tools, on_delta, think=think, _retry=True)
        if "does not support tools" in msg:
            raise OllamaError("模型 %s 不支持工具调用，换一个带 tools 能力的模型（ollama show %s 可以看）" % (model, model))
        raise OllamaError("Ollama 返回错误：%s" % msg)
    except urllib.error.URLError as e:
        raise OllamaError("连不上 Ollama（%s）：%s" % (cfg["ollama_host"], e.reason))
    return out
