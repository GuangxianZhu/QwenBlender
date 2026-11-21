# -*- coding: utf-8 -*-
"""找到 Blender，并让它跑 blender/runner.py。"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from .config import ROOT

RUNNER = os.path.join(ROOT, "blender", "runner.py")


def _has_bpy():
    try:
        import importlib.util
        return importlib.util.find_spec("bpy") is not None
    except Exception:
        return False


def _version_key(path):
    m = re.search(r"Blender[ _-]?(\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _from_registry():
    """Windows：从 .blend 文件的打开方式里找 Blender 的安装位置。"""
    out = []
    try:
        import winreg
        for root in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
            for key in (r"blendfile\shell\open\command", r"Software\Classes\blendfile\shell\open\command"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        val = winreg.QueryValueEx(k, "")[0]
                except OSError:
                    continue
                m = re.match(r'\s*"([^"]+)"', val) or re.match(r"\s*(\S+)", val)
                if m:
                    exe = os.path.join(os.path.dirname(m.group(1)), "blender.exe")
                    if os.path.isfile(exe):
                        out.append(exe)
    except Exception:  # noqa
        pass
    return out


def find_blender(cfg):
    """返回 ('exe', 路径) 或 ('python', sys.executable)；找不到返回 (None, 提示)。"""
    want = cfg.get("blender", "auto")
    if want == "python":
        return ("python", sys.executable) if _has_bpy() else (None, "当前 Python 没装 bpy 模块")
    if want and want != "auto":
        if os.path.isfile(want):
            return "exe", want
        return None, "config.json 里的 blender 路径不存在：%s" % want
    exe = shutil.which("blender")
    if exe:
        return "exe", exe
    cands = []
    if os.name == "nt":
        cands += _from_registry()
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")]
        for d in "CDEFG":
            roots.append(d + r":\Program Files")
        for r in filter(None, roots):
            cands += glob.glob(os.path.join(r, "Blender Foundation", "Blender*", "blender.exe"))
        for d in "CDEFG":
            for steam in (r":\Program Files (x86)\Steam", r":\Steam", r":\SteamLibrary"):
                cands += glob.glob(d + steam + r"\steamapps\common\Blender\blender.exe")
    elif sys.platform == "darwin":
        cands += glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
    else:
        cands += glob.glob("/opt/blender*/blender") + glob.glob(os.path.expanduser("~/blender*/blender"))
    cands = sorted(set(cands), key=_version_key, reverse=True)
    if cands:
        return "exe", cands[0]
    if _has_bpy():
        return "python", sys.executable
    return None, ("没找到 Blender。装好 Blender 后再试，或者在 config.json 里写："
                  '{"blender": "C:\\\\Program Files\\\\Blender Foundation\\\\Blender 4.5\\\\blender.exe"}')


def run(cfg, mode, target, *args, timeout=None):
    """运行 runner.py，返回它输出的结果字典。"""
    kind, exe = find_blender(cfg)
    if kind is None:
        return {"ok": False, "error": {"type": "NoBlender", "msg": exe}}
    extra = [str(a) for a in args]
    if mode in ("build", "view", "section"):
        extra += ["--res", str(cfg["render_res"]), "--samples", str(cfg["render_samples"]),
                  "--device", cfg["render_device"]]
    if kind == "exe":
        cmd = [exe, "--background", "--factory-startup", "--python", RUNNER, "--", mode, target] + extra
    else:
        cmd = [exe, RUNNER, mode, target] + extra
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout or cfg["blender_timeout"], env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"type": "Timeout", "msg": "Blender 跑了 %d 秒还没结束，已经停掉。"
                                       "脚本里可能有死循环，或者模型太重（螺纹、布尔太多）" % (timeout or cfg["blender_timeout"])}}
    except OSError as e:
        return {"ok": False, "error": {"type": "NoBlender", "msg": "启动 Blender 失败：%s" % e}}
    out = p.stdout.decode("utf-8", "replace")
    for line in reversed(out.splitlines()):
        if line.startswith("QB_RESULT "):
            try:
                return json.loads(line[10:])
            except ValueError:
                break
    tail = (out[-1200:] + "\n" + p.stderr.decode("utf-8", "replace")[-1200:]).strip()
    return {"ok": False, "error": {"type": "Crash", "msg": "Blender 没有正常返回结果（退出码 %s）" % p.returncode,
                                   "trace": tail}}
