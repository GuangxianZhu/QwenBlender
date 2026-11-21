# -*- coding: utf-8 -*-
"""用无头浏览器打开 out/index.html：收集报错、跑页面自检、截图。"""
import os
import pathlib

ARGS = ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--hide-scrollbars", "--mute-audio"]


def _launch(p, cfg):
    want = cfg.get("browser", "auto")
    tried = []
    if want and want != "auto":
        return p.chromium.launch(executable_path=want, headless=True, args=ARGS)
    for kw in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
        try:
            return p.chromium.launch(headless=True, args=ARGS, **kw)
        except Exception as e:  # noqa
            tried.append(str(e).splitlines()[0][:120])
    for exe in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if os.path.exists(exe):
            return p.chromium.launch(executable_path=exe, headless=True, args=ARGS)
    raise RuntimeError("没找到能用的浏览器（Edge / Chrome）。" + " | ".join(tried))


def check(job, cfg):
    """返回 {'ok', 'errors', 'warnings', 'images', 'info'}。"""
    html = os.path.join(job, "out", "index.html")
    if not os.path.exists(html):
        return {"ok": False, "errors": ["还没有 out/index.html，先 build_page"], "warnings": [], "images": []}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "errors": ["没装 playwright（用 启动.bat 启动会自动装好）"], "warnings": [], "images": []}
    url = pathlib.Path(html).resolve().as_uri()
    out = os.path.join(job, "out")
    errors, warnings, images, info = [], [], [], {}
    try:
        with sync_playwright() as p:
            browser = _launch(p, cfg)
            try:
                for tag, vw, vh in (("desktop", 1280, 800), ("mobile", 390, 844)):
                    page = browser.new_page(viewport={"width": vw, "height": vh})
                    logs = []
                    page.on("console", lambda m, logs=logs: logs.append(m.text) if m.type == "error" else None)
                    page.on("pageerror", lambda e, logs=logs: logs.append(str(e)))
                    page.goto(url)
                    try:
                        page.wait_for_function("window.__qb && (window.__qb.ready || window.__qb.errors.length > 0)",
                                               timeout=60000)
                    except Exception:
                        errors.append("[%s] 页面 60 秒内没有加载完" % tag)
                    page.wait_for_timeout(300)
                    for m in logs:
                        if "GPU stall" in m or "GL Driver Message" in m:
                            continue
                        errors.append("[%s] 浏览器控制台报错：%s" % (tag, m[:300]))
                    ready = page.evaluate("!!(window.__qb && window.__qb.ready)")
                    if not ready:
                        for m in page.evaluate("(window.__qb && window.__qb.errors) || []"):
                            errors.append("[%s] %s" % (tag, m))
                        page.screenshot(path=os.path.join(out, "page_%s.png" % tag))
                        images.append("page_%s.png" % tag)
                        page.close()
                        continue
                    if tag == "desktop":
                        st = page.evaluate("window.__qb.selftest()")
                        info = {"steps": st.get("steps"), "parts": st.get("parts"), "coverage": st.get("coverage")}
                        for m in st.get("errors", []):
                            errors.append(m)
                        for i, names in (st.get("moved") or {}).items():
                            warnings.append("第 %d 步的动画没有让这些零件动起来：%s（速度或位移算出来是 0？）" % (
                                int(i) + 1, "、".join(names)))
                        for i, cov in enumerate(st.get("coverage") or []):
                            if cov < 0.015:
                                errors.append("第 %d 步画面里几乎看不到模型（占画面 %.1f%%）：检查 hide / view / section" % (
                                    i + 1, cov * 100))
                        page.evaluate("window.__qb.manual(true); window.__qb.goStep(0, true); window.__qb.tick(0.05)")
                        page.screenshot(path=os.path.join(out, "page_desktop.png"))
                        images.append("page_desktop.png")
                        n = st.get("steps") or 0
                        if n > 1:
                            page.evaluate("window.__qb.goStep(%d, true); for (var i=0;i<24;i++) window.__qb.tick(0.05)" % (n - 1))
                            page.screenshot(path=os.path.join(out, "page_last.png"))
                            images.append("page_last.png")
                    else:
                        page.evaluate("window.__qb.manual(true); window.__qb.goStep(0, true); window.__qb.tick(0.05)")
                        m = page.evaluate("""(() => { const s = document.getElementById('stage');
                            return {stage: s.clientHeight, vh: innerHeight,
                                    over: document.documentElement.scrollWidth > innerWidth + 1,
                                    cov: window.__qb.coverage(), errs: window.__qb.errors.slice()}; })()""")
                        if m["over"]:
                            errors.append("[mobile] 手机上页面横向溢出了")
                        if m["stage"] < 0.3 * m["vh"]:
                            warnings.append("[mobile] 手机上 3D 画面只剩 %d 像素高，讲解文字太长了，缩短一些" % m["stage"])
                        for e in m["errs"]:
                            if e not in errors:
                                errors.append(e)
                        page.screenshot(path=os.path.join(out, "page_mobile.png"))
                        images.append("page_mobile.png")
                    page.close()
            finally:
                browser.close()
    except Exception as e:  # noqa
        errors.append("浏览器检查没跑起来：%s" % str(e).splitlines()[0][:300])
    seen, uniq = set(), []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return {"ok": not uniq, "errors": uniq, "warnings": warnings, "images": images, "info": info}


def check_plain(html, out_dir, cfg, prefix="page"):
    """检查任意一个网页（不是用骨架生成的也行）：控制台报错、有没有画布、截图。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "errors": ["没装 playwright"], "images": [], "info": {}}
    url = pathlib.Path(html).resolve().as_uri()
    errors, images, info = [], [], {}
    try:
        with sync_playwright() as p:
            browser = _launch(p, cfg)
            try:
                for tag, vw, vh in (("desktop", 1280, 800), ("mobile", 390, 844)):
                    page = browser.new_page(viewport={"width": vw, "height": vh})
                    logs = []
                    page.on("console", lambda m, logs=logs: logs.append(m.text) if m.type == "error" else None)
                    page.on("pageerror", lambda e, logs=logs: logs.append(str(e)))
                    page.on("requestfailed", lambda r, logs=logs: logs.append("加载失败：" + r.url[:120]))
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30000)
                    except Exception as e:  # noqa
                        errors.append("[%s] 页面没加载完：%s" % (tag, str(e).splitlines()[0][:160]))
                    page.wait_for_timeout(2500)
                    for m in logs:
                        if "GPU stall" in m or "GL Driver Message" in m:
                            continue
                        errors.append("[%s] %s" % (tag, m[:300]))
                    m = page.evaluate("""(() => { const c = [...document.querySelectorAll('canvas')];
                        return {canvas: c.length, big: c.filter(x => x.clientWidth > 100 && x.clientHeight > 100).length,
                                text: document.body ? document.body.innerText.length : 0,
                                over: document.documentElement.scrollWidth > innerWidth + 1}; })()""")
                    info[tag] = m
                    if m["big"] == 0:
                        errors.append("[%s] 页面上没有 3D 画布" % tag)
                    if tag == "mobile" and m["over"]:
                        errors.append("[mobile] 手机上页面横向溢出了")
                    name = "%s_%s.png" % (prefix, tag)
                    page.screenshot(path=os.path.join(out_dir, name))
                    images.append(name)
                    page.close()
            finally:
                browser.close()
    except Exception as e:  # noqa
        errors.append("浏览器检查没跑起来：%s" % str(e).splitlines()[0][:300])
    uniq = list(dict.fromkeys(errors))
    return {"ok": not uniq, "errors": uniq, "images": images, "info": info}
