# -*- coding: utf-8 -*-
"""机构计算器：杆长、齿数这些数先算清楚再建模。纯 Python，不需要 Blender。

每个函数返回一段中文文字：先给结论，再给数字，最后说这些数怎么用。
"""
import math

KINDS = ("four_bar", "crank_slider", "gear", "worm", "belt", "planetary", "screw")


class CalcError(ValueError):
    pass


def _pos(a, *keys):
    out = []
    for k in keys:
        v = a.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise CalcError("参数 %s 必须是大于 0 的数，现在是 %r" % (k, v))
        out.append(float(v))
    return out


def _opt(a, key, default=None, lo=None):
    v = a.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (lo is not None and v < lo):
        raise CalcError("参数 %s 要是%s数，现在是 %r" % (key, "不小于 %g 的" % lo if lo is not None else "", v))
    return float(v)


def _acos(x):
    return math.degrees(math.acos(max(-1.0, min(1.0, x))))


def _g(x, nd=1):
    return "%g" % round(x, nd)


# ------------------------------------------------------------------ 四连杆

def four_bar_numbers(a, b, c, d):
    """曲柄 a、连杆 b、摇杆 c、机架 d。返回 dict；曲柄转不了整圈时 ok=False。"""
    lens = sorted([a, b, c, d])
    grashof = lens[0] + lens[3] <= lens[1] + lens[2] + 1e-9
    out = {"grashof": grashof, "crank_shortest": abs(lens[0] - a) < 1e-9}
    out["ok"] = grashof and out["crank_shortest"]
    if not out["ok"]:
        return out
    # 两个极限位置：曲柄和连杆拉成一条直线。摇杆和机架的夹角（在摇杆轴 D 处，从 D→A 方向量起）
    far = _acos((c * c + d * d - (b + a) ** 2) / (2 * c * d))
    near = _acos((c * c + d * d - (b - a) ** 2) / (2 * c * d))
    out["rocker_min"], out["rocker_max"] = min(near, far), max(near, far)
    out["swing"] = abs(far - near)
    # 这两个位置上曲柄的方向（在曲柄轴 A 处，从 A→D 方向量起）
    th_far = _acos((d * d + (b + a) ** 2 - c * c) / (2 * d * (b + a)))
    th_near = _acos((d * d + (b - a) ** 2 - c * c) / (2 * d * (b - a))) + 180.0
    go = (th_near - th_far) % 360.0
    out["go"], out["back"] = go, 360.0 - go
    out["time_ratio"] = max(go, 360.0 - go) / min(go, 360.0 - go)
    # 传动角：连杆和摇杆的夹角，离 90° 越近越省力
    m1 = _acos((b * b + c * c - (d - a) ** 2) / (2 * b * c))
    m2 = _acos((b * b + c * c - (d + a) ** 2) / (2 * b * c))
    out["mu_min"] = min(m1, 180 - m1, m2, 180 - m2)
    return out


def four_bar(a):
    if a.get("want_swing") is not None:
        return four_bar_design(a)
    crank, coupler, rocker, frame = _pos(a, "crank", "coupler", "rocker", "frame")
    r = four_bar_numbers(crank, coupler, rocker, frame)
    head = "四连杆：曲柄 %s、连杆 %s、摇杆 %s、机架 %s（机架 = 两个固定转轴之间的距离）" % (
        _g(crank), _g(coupler), _g(rocker), _g(frame))
    if not r["ok"]:
        lens = sorted([crank, coupler, rocker, frame])
        why = ("最短 + 最长 = %s，大于另外两根之和 %s" % (_g(lens[0] + lens[3]), _g(lens[1] + lens[2])) if not r["grashof"]
               else "最短的那根不是曲柄")
        return "\n".join([
            "结论：这组杆长曲柄转不了整圈（%s）。" % why, head,
            "要求：曲柄是四根里最短的，而且 最短 + 最长 ≤ 另外两根之和。",
            "下一步：改杆长再算一次；想按摆角反推杆长，就用 calc(kind=\"four_bar\", crank=曲柄长, want_swing=摆角)。"])
    lines = ["结论：曲柄能转整圈，摇杆来回摆 %s°。" % _g(r["swing"]), head,
             "摇杆和机架的夹角在 %s° ~ %s° 之间变（在摇杆轴处，从指向曲柄轴的方向量起）。" % (_g(r["rocker_min"]), _g(r["rocker_max"])),
             "曲柄转 %s° 摇杆摆过去，再转 %s° 摆回来（快慢比 %s）。" % (_g(r["go"]), _g(r["back"]), _g(r["time_ratio"], 2)),
             "最小传动角 %s°%s。" % (_g(r["mu_min"]), "，偏小，实物会发涩，最好大于 40°" if r["mu_min"] < 40 else "")]
    arm = _opt(a, "arm", lo=0)
    if arm:
        lines.append("摇杆轴上固定一根长 %s 的臂：末端走过的弧长 %s，弦长 %s。" % (
            _g(arm), _g(arm * math.radians(r["swing"])), _g(2 * arm * math.sin(math.radians(r["swing"]) / 2))))
    lines.append("下一步：网页里写摆角就用这个数；要配玻璃、罩子这类零件，位置和大小等 check_page 报出「扫过的范围」再定。")
    return "\n".join(lines)


def four_bar_design(a):
    crank, want = _pos(a, "crank", "want_swing")
    if want >= 170:
        raise CalcError("want_swing（想要的摆角）要小于 170°，现在是 %r" % want)
    rocker = crank / math.sin(math.radians(want) / 2)        # 来回一样快（没有急回）时：曲柄 = 摇杆 × sin(摆角 / 2)
    rows = []
    for k in (2.5, 3.0, 3.5, 4.0, 5.0):
        coupler = round(crank * k, 1)
        f2 = coupler ** 2 + rocker ** 2 - crank ** 2
        if f2 <= 0:
            continue
        frame = math.sqrt(f2)
        r = four_bar_numbers(crank, coupler, rocker, frame)
        if r["ok"]:
            rows.append((r["mu_min"], coupler, frame, r))
    if not rows:
        return "结论：曲柄 %s 配不出摆角 %s° 的曲柄摇杆机构。\n下一步：把摆角改小，或者换曲柄长度再算。" % (_g(crank), _g(want))
    rows.sort(reverse=True)
    lines = ["结论：曲柄 %s、摆角 %s° —— 摇杆取 %s，下面几组连杆和机架都行（传动角大的排前面）。" % (_g(crank), _g(want), _g(rocker, 2)),
             "这几组都是来回一样快的（曲柄转 180° 摆过去，再转 180° 摆回来）。"]
    for mu, coupler, frame, r in rows[:4]:
        lines.append("  连杆 %s  机架 %s  → 摆角 %s°，最小传动角 %s°" % (_g(coupler), _g(frame, 2), _g(r["swing"]), _g(mu)))
    lines.append("下一步：挑一组，把四个数写成 model.py 开头的变量；铰点坐标按这些长度算，或者再 calc 一次核对。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 曲柄滑块

def crank_slider_numbers(r, L, e=0.0):
    out = {"ok": L > r + abs(e) + 1e-9}
    if not out["ok"]:
        return out
    far = math.sqrt((L + r) ** 2 - e * e)
    near = math.sqrt((L - r) ** 2 - e * e)
    out["far"], out["near"], out["stroke"] = far, near, far - near
    th1 = math.degrees(math.asin(e / (L + r))) if e else 0.0
    th2 = 180.0 + (math.degrees(math.asin(e / (L - r))) if e else 0.0)
    go = (th2 - th1) % 360.0
    out["go"], out["back"] = go, 360.0 - go
    out["rod_angle"] = math.degrees(math.asin((r + abs(e)) / L))
    return out


def crank_slider(a):
    crank, rod = _pos(a, "crank", "rod")
    e = _opt(a, "offset", 0.0) or 0.0
    r = crank_slider_numbers(crank, rod, e)
    head = "曲柄滑块：曲柄半径 %s、连杆 %s、偏距 %s（偏距 = 滑块走的直线离曲柄轴多远）" % (_g(crank), _g(rod), _g(e))
    if not r["ok"]:
        return "\n".join(["结论：连杆太短，曲柄转不了整圈。", head,
                          "要求：连杆长度 > 曲柄半径 + 偏距 = %s。" % _g(crank + abs(e)),
                          "下一步：把连杆加长（一般取曲柄半径的 3~5 倍）再算。"])
    lines = ["结论：曲柄能转整圈，滑块行程 %s mm。" % _g(r["stroke"], 2), head,
             "滑块上的销子离曲柄轴最远 %s、最近 %s（沿滑动方向量）。" % (_g(r["far"], 2), _g(r["near"], 2)),
             "连杆最多歪 %s°%s。" % (_g(r["rod_angle"]), "，偏大，滑块会被侧向顶得厉害，连杆最好再长一些" if r["rod_angle"] > 25 else "")]
    if e:
        lines.append("曲柄转 %s° 滑块走过去，再转 %s° 走回来。" % (_g(r["go"]), _g(r["back"])))
    lines.append("下一步：导轨、缸筒的长度要盖住「最近 ~ 最远」这一段再加滑块自己的长度；网页里写行程就用这个数。")
    return "\n".join(lines)


# ------------------------------------------------------------------ 传动

def _teeth(a, key):
    v = a.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 3:
        raise CalcError("参数 %s 是齿数，要是不小于 3 的整数，现在是 %r" % (key, v))
    return int(v)


def gear(a):
    z1, z2 = _teeth(a, "z1"), _teeth(a, "z2")
    internal = bool(a.get("internal"))
    m = _opt(a, "module", lo=0)
    ratio = z2 / z1
    lines = ["结论：从动轮转速 = 主动轮转速 × %d / %d = 主动轮的 %s 倍，转向%s。" % (
        z1, z2, _g(z1 / z2, 4), "相同（内啮合）" if internal else "相反"),
        "传动比 %s : 1（主动轮转 %s 圈，从动轮转 1 圈）。" % (_g(ratio, 3), _g(ratio, 3)),
        "demo.json 里：从动轮 speed = \"%s主动轮的 speed * %d / %d\"。" % ("" if internal else "-", z1, z2)]
    if m:
        lines.append("模数 %s：分度圆直径 %s 和 %s，中心距 %s。" % (
            _g(m), _g(m * z1), _g(m * z2), _g(m * abs(z2 - z1) / 2 if internal else m * (z1 + z2) / 2)))
    lines.append("下一步：位置和对齿交给 mesh()；转向要是写反了，check_page 会报「动起来以后穿模」。")
    return "\n".join(lines)


def worm(a):
    z = _teeth(a, "teeth")
    starts = a.get("starts", 1)
    if isinstance(starts, bool) or not isinstance(starts, (int, float)) or starts != int(starts) or starts < 1:
        raise CalcError("参数 starts 是蜗杆头数，要是不小于 1 的整数，现在是 %r" % (starts,))
    starts = int(starts)
    lines = ["结论：减速比 %s : 1 —— 蜗杆转 %s 圈，蜗轮转 1 圈。" % (_g(z / starts, 3), _g(z / starts, 3)),
             "蜗杆每转一圈，蜗轮转过 %d 个齿（%s°）。" % (starts, _g(360.0 * starts / z, 2)),
             "demo.json 里：蜗轮 speed = \"±蜗杆的 speed * %d / %d\"。" % (starts, z),
             "下一步：正负号先写一个，check_page 报「动起来以后穿模」就取负；位置和对齿交给 mesh_worm()。"]
    m = _opt(a, "module", lo=0)
    if m:
        q = _opt(a, "q", 10.0, lo=1) or 10.0
        lines.insert(2, "模数 %s、直径系数 q=%s：蜗杆分度圆直径 %s，蜗轮分度圆直径 %s，中心距 %s。" % (
            _g(m), _g(q), _g(m * q), _g(m * z), _g(m * (q + z) / 2)))
    return "\n".join(lines)


def belt(a):
    d1, d2 = _pos(a, "d1", "d2")
    lines = ["结论：从动轮转速 = 主动轮转速 × %s / %s = 主动轮的 %s 倍，转向相同。" % (_g(d1), _g(d2), _g(d1 / d2, 4)),
             "demo.json 里：从动轮 speed = \"主动轮的 speed * %s / %s\"。" % (_g(d1), _g(d2))]
    c = _opt(a, "center", lo=0)
    if c:
        if c <= abs(d2 - d1) / 2:
            raise CalcError("中心距 center=%s 太小，两个轮子套在一起了，至少要大于 %s" % (_g(c), _g(abs(d2 - d1) / 2)))
        al = math.asin((d2 - d1) / (2 * c))
        length = 2 * c * math.cos(al) + math.pi * (d1 + d2) / 2 + al * (d2 - d1)
        lines.append("中心距 %s：皮带长约 %s，小轮包角 %s°。" % (
            _g(c), _g(length), _g(180 - 2 * abs(math.degrees(al)))))
    lines.append("下一步：皮带用 belt(轮1, 轮2) 自动绕上去，不用自己算切点。")
    return "\n".join(lines)


def planetary(a):
    zs, zr = _teeth(a, "sun"), _teeth(a, "ring")
    if zr <= zs:
        raise CalcError("内齿圈齿数 ring=%d 要大于太阳轮齿数 sun=%d" % (zr, zs))
    if (zr - zs) % 2:
        raise CalcError("ring - sun = %d 是奇数，行星轮齿数不是整数。两个齿数要同奇同偶" % (zr - zs))
    zp = (zr - zs) // 2
    n = int(a.get("planets", 3) or 3)
    lines = ["结论：内齿圈固定、太阳轮输入、行星架输出时，减速比 %s : 1。" % _g(1 + zr / zs, 3),
             "行星轮齿数 = (%d - %d) / 2 = %d。" % (zr, zs, zp),
             "太阳轮转速记作 1：行星架 %s（同向），行星轮绕自己的轴 %s（反向）。" % (_g(zs / (zs + zr), 4), _g(-(zs / (zs + zr)) * zr / zp, 4)),
             "demo.json 里：行星架 speed = \"太阳轮的 speed * %d / %d\"；行星轮写两条 spin："
             "一条 pivot 写太阳轮中心、speed 同行星架，一条绕自己、speed = \"-行星架的 speed * %d / %d\"。" % (zs, zs + zr, zr, zp),
             "%d 个行星轮%s均匀分布（要求 (sun + ring) / 个数 是整数）。" % (n, "可以" if (zs + zr) % n == 0 else "不能")]
    m = _opt(a, "module", lo=0)
    if m:
        lines.append("模数 %s：太阳轮到行星轮的中心距 %s，内齿圈分度圆直径 %s。" % (_g(m), _g(m * (zs + zp) / 2), _g(m * zr)))
    lines.append("下一步：太阳轮和行星轮用 mesh() 对齿，内齿圈用 ring_gear + mesh()。")
    return "\n".join(lines)


def screw(a):
    pitch, = _pos(a, "pitch")
    lines = []
    turns, travel = _opt(a, "turns", lo=0), _opt(a, "travel", lo=0)
    if turns:
        lines.append("结论：转 %s 圈走 %s mm。" % (_g(turns, 3), _g(turns * pitch, 3)))
    elif travel:
        lines.append("结论：走 %s mm 要转 %s 圈。" % (_g(travel, 3), _g(travel / pitch, 3)))
    else:
        raise CalcError("screw 除了 pitch（螺距），还要给 turns（圈数）或 travel（要走的距离）其中一个")
    lines.append("螺距 %s：每转一圈走 %s mm。" % (_g(pitch, 3), _g(pitch, 3)))
    lines.append("下一步：demo.json 里用 screw 动画，turns 和 pitch 就填这两个数。")
    return "\n".join(lines)


HELP = """calc 能算的（kind 和要给的数）：
  four_bar      crank coupler rocker frame（可选 arm：摇杆轴上那根臂的长度）→ 能不能转整圈、摆角、极限位置、传动角
  four_bar      crank want_swing → 按想要的摆角反推摇杆、连杆、机架的长度
  crank_slider  crank rod（可选 offset）→ 行程、最远最近位置、连杆最大倾角
  gear          z1 z2（可选 module、internal=true）→ 速比、转向、中心距
  worm          teeth（可选 starts、module、q）→ 减速比、中心距
  belt          d1 d2（可选 center）→ 速比、皮带长度
  planetary     sun ring（可选 planets、module）→ 行星轮齿数、减速比、各自的转速
  screw         pitch 加 turns 或 travel → 走多远、转几圈"""


def run(args):
    """args 是工具传进来的 dict。返回文字。"""
    kind = str(args.get("kind", "")).strip().lower()
    fn = {"four_bar": four_bar, "crank_slider": crank_slider, "gear": gear, "worm": worm, "belt": belt,
          "planetary": planetary, "screw": screw}.get(kind)
    if fn is None:
        return "没有 %r 这种计算。\n%s" % (args.get("kind"), HELP)
    try:
        return fn(args)
    except CalcError as e:
        return "算不了：%s\n%s" % (e, HELP)
