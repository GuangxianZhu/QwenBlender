# -*- coding: utf-8 -*-
"""零件库测试：python tests/test_lib.py（需要能找到 Blender，或者当前 Python 装了 bpy）。"""
import json
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qb import blender, config  # noqa: E402


def build(cfg, src, name):
    d = os.path.join(tempfile.gettempdir(), "qb_test_" + name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    with open(os.path.join(d, "model.py"), "w", encoding="utf-8") as f:
        f.write(src)
    return blender.run(cfg, "build", d, "--no-render")


def main():
    cfg = config.load()
    # 1) 每个函数都能跑，每个零件都封闭、体积为正
    r = build(cfg, open(os.path.join(ROOT, "tests", "lib_all_model.py"), encoding="utf-8").read(), "all")
    assert r.get("ok"), r.get("error")
    bad = [p["name"] for p in r["parts"] if not p["closed"] or p["volume"] <= 0]
    assert not bad, "没封闭的零件：%s" % bad
    assert not [i for i in r["issues"] if "破面" in i or "法线" in i], r["issues"]
    print("全部函数：%d 个零件，都是封闭实体" % len(r["parts"]))

    # 2) 尺寸是准的
    r = build(cfg, "from qblib import *\nb = box(20, 30, 10)\nc = cylinder(10, 40)\nstack(c, b)\n"
                   "t = tube(30, 20, 5)\nbeside(t, b, '+x', gap=3)\n", "dims")
    p = {x["name"]: x for x in r["parts"]}
    assert p["Box_1"]["size"] == [20.0, 30.0, 10.0] and abs(p["Box_1"]["volume"] - 6000) < 1
    assert p["Cylinder_1"]["min"][2] == 10.0 and p["Cylinder_1"]["max"][2] == 50.0
    assert abs(p["Tube_1"]["min"][0] - 13.0) < 1e-3
    assert "Cylinder_1" in p["Box_1"]["touches"] and p["Tube_1"]["touches"] == []
    assert any("悬空" in w and "Tube_1" in w for w in r["warnings"]), r["warnings"]
    print("尺寸、堆叠、贴靠、悬空检查：正确")

    # 3) 穿模能查出来，深度大致对；声明过的不算
    src = "from qblib import *\na = box(20, 20, 20)\nb = box(10, 10, 10)\nat(b, 12, 0, 5)\n"
    r = build(cfg, src, "pen")
    assert any("穿模" in i and "最深的地方在" in i for i in r["issues"]), r
    depth = r["pairs"][0]["penetration"]
    assert 2.5 <= depth <= 3.5, r["pairs"]
    r = build(cfg, src.replace("12, 0, 5", "14.5, 0, 5") + "allow_overlap(a, b)\n", "pen2")    # 只压进 0.5 mm 的配合
    assert not r["issues"] and any("已声明" in w for w in r["warnings"]), (r["issues"], r["warnings"])
    # 光杆螺栓直接插进没打孔的板：两边的顶点都不在对方里面，要靠面上的采样点才能发现
    r = build(cfg, "from qblib import *\np = rounded_box(40, 40, 6, 4)\nb = hex_bolt(8, 30, thread=False)\nat(b, 0, 0, 6)\n", "pen3")
    assert any("穿模" in i for i in r["issues"]), r["issues"]
    r = build(cfg, "from qblib import *\np = box(60, 60, 2)\nc = cylinder(3, 40)\nat(c, 10, 7, -20)\n", "pen4")
    assert any("穿模" in i for i in r["issues"]), r["issues"]
    print("穿模检查：正确（实际扎进 3 mm，量出来 %.2f mm；杆穿板也能发现）" % depth)

    # 4) 螺栓拧进螺母：螺纹对得上，不穿模，互相接触
    for d, L in ((8, 30), (5, 20), (12, 40)):
        r = build(cfg, "from qblib import *\nb = hex_bolt(%d, %d)\nrot(b, 30, 20, 0)\nat(b, 5, 6, 7)\n"
                       "n = nut(%d)\nscrew_on(n, b, grip=%d)\nn2 = nut(%d)\nscrew_on(n2, b, grip=1.3)\n"
                       % (d, L, d, L // 2, d), "thread%d" % d)
        assert r.get("ok") and not r["issues"], (d, r.get("issues"), r.get("error"))
        p = {x["name"]: x for x in r["parts"]}
        assert "Nut_1" in p["Bolt_1"]["touches"] and "Nut_2" in p["Bolt_1"]["touches"], p["Bolt_1"]["touches"]
    print("螺栓和螺母的螺纹：对得上，不穿模")

    # 凹轮廓拉伸：体积要等于轮廓面积 × 高（C 形：60×90 减去 40×50 的开口，厚 20）
    r = build(cfg, "from qblib import *\nc = extrude([(0,0),(60,0),(60,20),(20,20),(20,70),(60,70),(60,90),(0,90)], 20)\n", "concave")
    assert abs(r["parts"][0]["volume"] - (60 * 90 - 40 * 50) * 20) < 1, r["parts"][0]["volume"]
    # 没钻到零件的孔要报错；声明了 allow_overlap 但其实是实体穿实体，照样算穿模
    # 盲孔的方向写反了也能钻进去（从底面往上、从侧面往里）；pos 根本不在零件上才报错
    r = build(cfg, "from qblib import *\nb = box(40, 40, 20)\nhole(b, 8, (0, 0, 0), axis='z', depth=10)\n"
                   "hole(b, 6, (20, 0, 10), axis='-x', depth=8)\nhole(b, 6, (-20, 10, 10), axis='-x', depth=8)\n", "flip")
    assert r.get("ok") and abs(r["parts"][0]["volume"] - (32000 - 3.14159 * 16 * 10 - 2 * 3.14159 * 9 * 8)) < 30, r
    r = build(cfg, "from qblib import *\nb = box(40, 40, 20)\nhole(b, 8, (0, 0, 60), axis='z', depth=20)\n", "nohole")
    assert not r["ok"] and "没钻到材料" in r["error"]["msg"] and r["error"]["line"] == 3, r
    r = build(cfg, "from qblib import *\nb = box(40, 40, 20)\nc = cylinder(8, 60)\nat(c, 0, 0, -20)\nallow_overlap(b, c)\n", "fakefit")
    assert any("allow_overlap" in i for i in r["issues"]), r["issues"]
    print("凹轮廓、空钻、滥用 allow_overlap：都能查出来")

    # 行星轮系：太阳轮 18、行星轮 18×3、内齿圈 54，相位对好以后不穿模，而且互相接触
    r = build(cfg, "from qblib import *\nimport math\nM, ZS, ZP, ZR, W = 2, 18, 18, 54, 10\n"
                   "ring = ring_gear(M, ZR, W, 124)\nsun = spur_gear(M, ZS, W, bore=8)\nrot(sun, 0, 0, 180 / ZS)\n"
                   "a = M * (ZS + ZP) / 2\np = spur_gear(M, ZP, W, bore=6)\nat(p, a, 0, 0)\nps = array_circular(p, 3)\n", "planet")
    assert r.get("ok") and not r["issues"], (r.get("issues"), r.get("error"))
    p = {x["name"]: x for x in r["parts"]}
    assert len(p["RingGear_1"]["touches"]) == 3 and len(p["Gear_1"]["touches"]) == 3, (p["RingGear_1"]["touches"], p["Gear_1"]["touches"])
    r = build(cfg, "from qblib import *\nring = ring_gear(2, 54, 10, 124)\nsun = spur_gear(2, 18, 10)\n"
                   "p = spur_gear(2, 18, 10)\nat(p, 36, 0, 0)\n", "planet_bad")      # 太阳轮没转半个齿
    assert any("穿模" in i for i in r["issues"]), r["issues"]
    print("行星轮系：相位对了不穿模，没对会被查出来")

    # join 出来的零件（几个壳面贴面）：轴从它的孔里穿过，不能误报穿模
    r = build(cfg, "from qblib import *\nplate = cylinder(84, 4)\nat(plate, 0, 0, 13)\nhole(plate, 12.4, (0, 0, 17))\n"
                   "boss = cylinder(16, 4)\nat(boss, 0, 0, 17)\nhole(boss, 12.4, (0, 0, 21))\n"
                   "pin = cylinder(8, 13)\nat(pin, 36, 0, 0)\ncarrier = join([pin, plate, boss])\n"
                   "shaft = cylinder(8, 26)\ntube12 = tube(12, 8.4, 41)\nat(tube12, 0, 0, -20)\n"
                   "g = spur_gear(2, 18, 12, bore=12.4)\n", "shells")
    assert r.get("ok") and not r["issues"], r.get("issues")
    r = build(cfg, "from qblib import *\na = join([box(20, 20, 5), at(box(20, 20, 5), 0, 0, 5)])\nc = cylinder(6, 30)\nat(c, 0, 0, -10)\n", "shells2")
    assert any("穿模" in i for i in r["issues"]), r["issues"]          # 真穿进 join 件里的照样要报
    print("面贴面的 join 零件：孔里穿轴不误报，真穿模照样报")

    # mesh()：任意起始角、任意方向、不同高度，直齿、斜齿、内齿圈都要对上；蜗轮蜗杆、皮带也不穿模
    r = build(cfg, "from qblib import *\n"
                   "g1 = helical_gear(2, 20, 12, 15); rot(g1, 0, 0, 7); g2 = helical_gear(2, 30, 12, -15); mesh(g2, g1, angle=40)\n"
                   "s1 = spur_gear(2, 18, 10); at(s1, 200, 0, 3); rot(s1, 0, 0, 13); s2 = spur_gear(2, 27, 10); mesh(s2, s1, angle=200)\n"
                   "sun = spur_gear(2, 18, 10); at(sun, 0, 300, 0); rot(sun, 0, 0, 3)\n"
                   "ps = [mesh(spur_gear(2, 18, 10), sun, angle=120 * i + 20) for i in range(3)]\n"
                   "ring = ring_gear(2, 54, 10, 124); at(ring, 0, 300, 0); mesh(ring, ps[0])\n"
                   "r2 = ring_gear(2, 40, 8, 96); at(r2, 300, 300, 0); rot(r2, 0, 0, 5); p2 = spur_gear(2, 12, 8); mesh(p2, r2, angle=70)\n"
                   "w = worm(2, 60); rot(w, 0, 90, 0); at(w, -230, 0, 40); ww = worm_wheel(2, 30, 14, bore=8); mesh_worm(ww, w)\n"
                   "w2 = worm(3, 80, starts=2, q=8); rot(w2, 0, 90, 0); at(w2, -230, 300, 40)\n"
                   "ww2 = worm_wheel(3, 24, 20, starts=2, q=8); mesh_worm(ww2, w2, side='-y')\n"
                   "pa = pulley(30, 12, bore=8); at(pa, 0, -200, 0); pb = pulley(90, 12); at(pb, 110, -170, 0); bl = belt(pa, pb)\n", "mesh")
    assert r.get("ok") and not r["issues"], (r.get("issues"), r.get("error"))
    p = {x["name"]: x for x in r["parts"]}
    assert p["HelicalGear_2"]["touches"] == ["HelicalGear_1"] and len(p["RingGear_1"]["touches"]) == 3
    assert p["Gear_7"]["touches"] == ["RingGear_2"] and p["WormWheel_1"]["touches"] == ["Worm_1"]
    assert p["WormWheel_2"]["touches"] == ["Worm_2"] and sorted(p["Belt_1"]["touches"]) == ["Pulley_1", "Pulley_2"]
    r = build(cfg, "from qblib import *\ng1 = helical_gear(2, 20, 12, 15)\ng2 = helical_gear(2, 30, 12, 15)\nmesh(g2, g1)\n", "mesh_bad")
    assert not r["ok"] and "方向相反" in r["error"]["msg"] and r["error"]["line"] == 4, r.get("error")
    print("自动对齿 mesh / mesh_worm、皮带：都不穿模，参数配不上会报错")

    # 转过方向的带孔零件：孔里穿销子不能误报（连杆）
    r = build(cfg, "from qblib import *\nrod = link_bar((15, 0, 0), (0, 0, 58), 14, 4, hole_d=6.2)\n"
                   "pin = cylinder(6, 8)\nrot(pin, 90, 0, 0)\nat(pin, 15, 4, 0)\n", "rodpin")
    assert r.get("ok") and not r["issues"], r.get("issues")
    print("转过方向的带孔零件：不误报")

    # 运动检查：转向反了、速比错了、连杆撞到别的零件都要报；写对了不报
    def motion(src, anim, name, params=None):
        r = build(cfg, src, name)
        assert r.get("ok") and not r["issues"], (r.get("issues"), r.get("error"))
        d = os.path.join(tempfile.gettempdir(), "qb_test_" + name)
        json.dump({"title": "t", "params": params or [], "steps": [{"title": "转", "text": "x", "anim": anim}]},
                  open(os.path.join(d, "demo.json"), "w", encoding="utf-8"), ensure_ascii=False)
        return blender.run(cfg, "motion", d)

    gears = "from qblib import *\na = part(spur_gear(2, 20, 10), 'A')\nb = part(spur_gear(2, 40, 10), 'B')\nmesh(b, a)\n"
    spin = lambda sb: [{"part": "A", "type": "spin", "axis": "z", "speed": 60}, {"part": "B", "type": "spin", "axis": "z", "speed": sb}]
    assert motion(gears, spin(-30), "mo_ok")["ok"]
    r = motion(gears, spin(30), "mo_dir")
    assert not r["ok"] and "A" in r["problems"][0] and "穿模" in r["problems"][0], r
    assert not motion(gears, spin(-40), "mo_ratio")["ok"]
    wsrc = ("from qblib import *\nw = part(worm(2, 60), 'W'); rot(w, 0, 90, 0); at(w, -30, 0, 40)\n"
            "g = part(worm_wheel(2, 30, 14, bore=8), 'G'); mesh_worm(g, w)\n")
    wspin = lambda sg: [{"part": "W", "type": "spin", "axis": "x", "speed": 360}, {"part": "G", "type": "spin", "axis": "z", "speed": sg, "hollow": True}]
    rr = [motion(wsrc, wspin(sg), "mo_worm%d" % i)["ok"] for i, sg in enumerate((12, -12))]
    assert sorted(rr) == [False, True], rr                                                # 蜗轮只有一个转向是对的
    fsrc = ("from qblib import *\n"
            "cr = part(link_bar((0, 0, 0), (0, 0, 20), 10, 4, hole_d=5.2), 'Crank')\n"
            "co = part(link_bar((0, 0, 20), (60, 0, 45), 10, 4, hole_d=5.2), 'Coupler'); move(co, 0, 4, 0)\n"
            "ro = part(link_bar((70, 0, 0), (60, 0, 45), 10, 4, hole_d=5.2), 'Rocker')\n"
            "for i, (x, z) in enumerate([(0, 20), (60, 45)]):\n"
            "    p = part(cylinder(5, 8), 'Pin%d' % i); rot(p, 90, 0, 0); at(p, x, 6, z)\n"
            "")
    four = {"type": "four_bar", "crank": ["Crank", "Pin0"], "coupler": "Coupler", "rocker": ["Rocker", "Pin1"],
            "a": [0, 0, 0], "b": [0, 0, 20], "c": [60, 0, 45], "d": [70, 0, 0], "axis": "y", "hollow": True}
    r = motion(fsrc, [dict(four, speed=90)], "mo_four")
    assert r["ok"], r                                                                     # 销子一直在孔里，杆子互相不撞
    r = motion(fsrc + "blk = part(box(10, 4, 10), 'Block'); at(blk, 25, 0, -5)\nallow_float(blk)\n", [dict(four, speed=90)], "mo_hit")
    assert not r["ok"] and any("Block" in x for x in r["problems"]), r                    # 路上有挡块要报
    r = motion(fsrc, [dict(four, c=[60, 0, 30], speed=90)], "mo_wrongpt")
    assert not r["ok"], r                                                                 # 铰点写得和模型对不上，销子会扎进杆里
    r = motion(fsrc + "blk = part(box(10, 4, 10), 'Block'); at(blk, 25, 0, -5)\nallow_float(blk)\n", [dict(four, angle="ang")], "mo_sweep",
               params=[{"id": "ang", "min": 0, "max": 360, "value": 0}])
    assert not r["ok"] and "ang=" in r["problems"][0], r                                  # 角度由滑条给时，把滑条扫一遍
    # 运动范围、缺销子、缺轴、贴着的零件离开
    jsrc = ("from qblib import *\n"
            "base = part(at(box(100, 6, 14), 35, -6, -7), 'Base')\n"
            "cr = part(link_bar((0, 0, 0), (0, 0, 20), 10, 4), 'Crank')\n"
            "ro = part(link_bar((70, 0, 0), (60, 0, 45), 10, 4), 'Rocker')\n"
            "co = part(move(link_bar((0, 0, 20), (60, 0, 45), 10, 4), 0, 4, 0), 'Coupler')\n"
            "pb = part(pin_joint(cr, co, (0, 0, 20), 4), 'PinB')\n%s"
            "sa = part(shaft_through([base, cr], (0, -9, 0), (0, 2, 0), 5), 'ShaftA')\n%s")
    pin_c = "pc = part(pin_joint(co, ro, (60, 0, 45), 4), 'PinC')\n"
    shaft_d = "sd = part(shaft_through([base, ro], (70, -9, 0), (70, 2, 0), 5), 'ShaftD')\n"
    jb = {"type": "four_bar", "crank": ["Crank", "PinB"], "coupler": "Coupler", "rocker": ["Rocker", "PinC"],
          "a": "ShaftA", "b": "PinB", "c": "PinC", "d": "ShaftD", "axis": "y", "speed": 90}
    r = motion(jsrc % (pin_c, shaft_d), [jb], "mo_j_ok")
    assert r["ok"] and not r["warnings"], r
    sw = r["ranges"][0]["swing"][0]
    A_, D_ = 20.0, 70.0
    ref = lambda ac: math.degrees(math.acos((D_ * D_ + (10 ** 2 + 45 ** 2) - ac * ac) / (2 * D_ * math.hypot(10, 45))))
    L_ = math.hypot(60, 25)
    assert abs(sw - (ref(L_ + A_) - ref(L_ - A_))) < 0.3, (sw, ref(L_ + A_) - ref(L_ - A_))          # 摆角和手算的一致
    assert any("Rocker" in ln and "扫过" in ln for ln in r["ranges"][0]["lines"]), r["ranges"]
    r = motion(jsrc % ("", shaft_d), [dict(jb, rocker="Rocker", c=[60, 0, 45])], "mo_j_nopin")
    assert not r["ok"] and any("没有销子" in x and "铰点 c" in x for x in r["problems"]), r
    r = motion(jsrc % (pin_c, "hole(ro, 5.2, (70, -2, 0), axis='y')\nallow_float(base)\n"), [dict(jb, d=[70, 0, 0])], "mo_j_noshaft")
    assert not r["ok"] and any("转轴那里是空的" in x and "Rocker" in x for x in r["problems"]), r
    r = motion(jsrc % (pin_c, "hole(ro, 5.2, (70, -2, 0), axis='y')\nallow_float(base)\n"), [dict(jb, d=[70, 0, 0], hollow=True)], "mo_j_hollow")
    assert r["ok"], r
    r = motion(jsrc % (pin_c, shaft_d), [dict(jb, b=[30, 0, 60])], "mo_j_offpt")
    assert not r["ok"] and any("不在" in x and "铰点 b" in x for x in r["problems"]), r
    gsrc = "from qblib import *\ng = part(spur_gear(2, 20, 8, bore=8), 'G')\nbase = part(at(box(60, 60, 4), 0, 0, -4), 'Base')\n%s"
    gs = [{"part": "G", "type": "spin", "axis": "z", "speed": 60}]
    r = motion(gsrc % "", gs, "mo_g_empty")
    assert not r["ok"] and any("轴线上是空的" in x for x in r["problems"]), r
    assert motion(gsrc % "", [dict(gs[0], hollow=True)], "mo_g_hollow")["ok"]
    assert motion(gsrc % "s = part(at(cylinder(8, 20), 0, 0, 0), 'S')\n", gs, "mo_g_shaft")["ok"]
    ssrc = ("from qblib import *\nrail = part(box(%d, 10, 4), 'Rail')\nsl = part(at(box(20, 10, 6), 0, 0, 4), 'Slider')\n"
            "cr = part(at(rot(cylinder(30, 4), 90, 0, 0), -60, -5, 30), 'Disc')\nrod = part(link_bar((-50, -11, 30), (0, -11, 7), 6, 4), 'Rod')\n"
            "p1 = part(pin_joint(cr, rod, (-50, 0, 30), 3), 'P1')\np2 = part(pin_joint(rod, sl, (0, 0, 7), 3), 'P2')\n"
            "ax = part(shaft_through(cr, (-60, -9, 30), (-60, 6, 30), 6), 'Axle')\nallow_float(rail)\n")
    sa = [{"type": "crank_slider", "crank": ["Disc", "P1", "Axle"], "rod": "Rod", "slider": ["Slider", "P2"], "center": "Axle",
           "crank_pin": "P1", "slider_pin": "P2", "axis": "y", "slide": "x", "speed": 90}]
    r = motion(ssrc % 200, sa, "mo_s_ok")
    rl, e_ = math.hypot(50, 23), 23.0
    want = math.sqrt((rl + 10) ** 2 - e_ * e_) - math.sqrt((rl - 10) ** 2 - e_ * e_)           # 偏置曲柄滑块的行程
    assert r["ok"] and abs(r["ranges"][0]["stroke"][0] - want) < 0.3, (r, want)
    r = motion(ssrc % 24, sa, "mo_s_short")
    assert any("探到外面" in x and "Slider" in x for x in r["warnings"]) or any("离开" in x for x in r["problems"]), r
    # 在动的零件被不透明的零件挡住，看不到它动
    vsrc = ("from qblib import *\ncyl = part(tube(30, 22, 30), 'Cyl')\nmat(cyl, 'steel')\npis = part(at(cylinder(21.6, 14), 0, 0, 8), 'Piston')\n"
            "cap = part(at(cylinder(30, 3), 0, 0, 30), 'Cap')\nfloor = part(at(box(40, 40, 3), 0, 0, -3), 'Floor')\n")
    va = [{"part": "Piston", "type": "spin", "axis": "z", "speed": 60}]

    def motion_step(src, step, name):
        r = build(cfg, src, name)
        assert r.get("ok") and not r["issues"], (r.get("issues"), r.get("error"))
        d = os.path.join(tempfile.gettempdir(), "qb_test_" + name)
        json.dump({"title": "t", "steps": [dict({"title": "转", "text": "x"}, **step)]}, open(os.path.join(d, "demo.json"), "w", encoding="utf-8"), ensure_ascii=False)
        return blender.run(cfg, "motion", d)

    r = motion_step(vsrc, {"anim": va, "view": "front"}, "mo_v_hid")
    assert not r["ok"] and any("Piston 在动" in x and "ghost" in x for x in r["problems"]), r
    assert motion_step(vsrc, {"anim": va, "view": "front", "ghost": ["Cyl"]}, "mo_v_ghost")["ok"]
    assert motion_step(vsrc, {"anim": va, "view": "front", "highlight": ["Piston"]}, "mo_v_hl")["ok"]
    print("运动检查：转向、速比、连杆铰点、挡路的零件、缺销子、缺轴、滑出导轨、被挡住看不到都能查出来，摆角和行程算得对")

    # 对轴摆放、铰接：位置算对，孔打好，报错说清楚
    near = lambda a, b, tol=0.05: all(abs(x - y) <= tol for x, y in zip(a, b))
    r = build(cfg, "from qblib import *\n"
                   "s = part(shaft_through(part(box(30, 10, 30), 'Block'), (0, -20, 15), (0, 20, 15), 8), 'Shaft')\n"
                   "b = part(on_axis(bearing(8, 22, 7), s, pos=32), 'Brg')\n"
                   "g = part(on_axis(spur_gear(2, 20, 6, bore=8), s), 'Gear')\n"
                   "move(g, 0, -14, 0)\n"
                   "r1 = part(aim(cylinder(6, 50), (40, 0, 0), (40, 30, 40)), 'Rod')\nallow_float(r1)\n", "axis")
    p = {x["name"]: x for x in r["parts"]}
    assert r.get("ok") and not r["issues"], r["issues"]
    assert near(p["Shaft"]["size"], [8, 40, 8]) and near(p["Brg"]["center"], [0, 12, 15]) and near(p["Brg"]["size"], [22, 7, 22]), (p["Shaft"], p["Brg"])
    assert near(p["Gear"]["center"], [0, -14, 15], 0.01) and "Shaft" in p["Block"]["touches"] and "Shaft" in p["Brg"]["touches"], p
    assert near(p["Rod"]["min"], [37, -2.4, -1.8], 0.1) and near(p["Rod"]["max"], [43, 32.4, 41.8], 0.1), p["Rod"]
    assert [j["name"] for j in r["joints"]] == ["Shaft"] and r["joints"][0]["parts"] == ["Block"], r["joints"]
    r = build(cfg, "from qblib import *\n"
                   "a = part(link_bar((0, 0, 0), (40, 0, 0), 12, 4), 'A')\n"
                   "b = part(move(link_bar((40, 0, 0), (60, 0, 30), 12, 4), 0, 4, 0), 'B')\n"
                   "pin = part(pin_joint(a, b, (40, 0, 0), 5), 'Pin')\n", "pinj")
    p = {x["name"]: x for x in r["parts"]}
    assert r.get("ok") and not r["issues"], r["issues"]
    assert near(p["Pin"]["size"], [5, 8, 5]) and near(p["Pin"]["center"], [40, 2, 0]) and set(p["Pin"]["touches"]) == {"A", "B"}, p["Pin"]
    assert r["joints"][0]["kind"] == "pin" and r["joints"][0]["parts"] == ["A", "B"] and near(r["joints"][0]["point"], [40, 2, 0])
    for src, word in (("pin_joint(box(10, 10, 10), at(box(10, 10, 10), 50, 0, 0), (0, 0, 5), 4)", "周围没有材料"),
                      ("shaft_through(box(10, 10, 10), (30, -20, 5), (30, 20, 5), 4)", "没有穿过"),
                      ("shaft_through(box(10, 10, 10), (0, 0, 5), (0, 0, 5), 4)", "p1 和 p2 重合"),
                      ("pin_joint(box(10, 10, 10), box(9, 9, 9), (0, 0, 5), 4, clearance=-1)", "clearance"),
                      ("aim(box(10, 10, 10), (1, 2, 3), (1, 2, 3))", "p_from 和 p_to 重合"),
                      ("on_axis(box(10, 10, 10), cylinder(8, 40), pos=60)", "0 ~ 40"),
                      ("on_axis(box(10, 10, 10), ((0, 0, 0), 'x'))", "必须写 pos"),
                      ("on_axis(box(10, 10, 10), link_bar((0, 0, 0), (40, 0, 0), 10, 4))", "不在它的正中间")):
        r = build(cfg, "from qblib import *\n" + src + "\n", "axerr")
        assert not r.get("ok") and word in r["error"]["msg"], (src, r.get("error"))
    print("对轴摆放和铰接：aim / on_axis / pin_joint / shaft_through 位置、打孔、报错都对")

    # 穿模怎么改：放偏了的给出挪法，整个穿过去的提示打孔；被挡住看不到的零件写成文字
    hsrc = ("from qblib import *\nbase = part(box(60, 40, 6), 'Base')\nblk = part(at(box(20, 20, 20), 0, 0, 4), 'Block')\n"
            "rod = part(at(rot(cylinder(8, 80), 0, 90, 0), -40, 0, 16), 'Rod')\n"
            "cyl = part(at(tube(30, 22, 30), 100, 0, 0), 'Cyl')\nmat(cyl, '%s')\npis = part(at(cylinder(21.6, 14), 100, 0, 8), 'Piston')\n"
            "cap = part(at(cylinder(30, 3), 100, 0, 30), 'Cap')\nmat(cap, '%s')\nfloor = part(at(box(40, 40, 3), 100, 0, -3), 'Floor')\n")
    r = build(cfg, hsrc % ("steel", "steel"), "hint")
    i1 = [x for x in r["issues"] if "Base" in x and "Block" in x][0]
    assert "改法" in i1 and "Block 往 +z 挪 2.0" in i1, i1
    i2 = [x for x in r["issues"] if "Block" in x and "Rod" in x][0]
    assert "分不开" in i2 and "给 Block 打孔" in i2, i2
    assert any("Piston 在四个视图里都看不到" in x and "ghost" in x for x in r["hidden"]), r["hidden"]
    r = build(cfg, hsrc % ("glass", "glass"), "hint2")
    assert not any("Piston" in x for x in r["hidden"]), r["hidden"]                       # 透明的缸筒不算挡
    print("改法提示和遮挡报告：正确")

    # 不用 qblib、直接写 bpy 的脚本：改 location / rotation_euler、设了父子关系的，位置都要算对
    r = build(cfg, "import bpy, bmesh\n"
                   "def cube(name, loc, parent=None):\n"
                   "    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=10); me = bpy.data.meshes.new(name); bm.to_mesh(me)\n"
                   "    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)\n"
                   "    o.location = loc; o.parent = parent; return o\n"
                   "a = cube('A', (100, 0, 0)); a.rotation_euler = (0, 0, 1.5707963)\nb = cube('B', (20, 0, 0), a)\n", "rawbpy")
    p = {x["name"]: x for x in r["parts"]}
    assert r.get("ok") and abs(p["A"]["center"][0] - 100) < 0.01, p["A"]
    assert abs(p["B"]["center"][0] - 100) < 0.01 and abs(p["B"]["center"][1] - 20) < 0.01, p["B"]
    raw = open(os.path.join(tempfile.gettempdir(), "qb_test_rawbpy", "out", "model.glb"), "rb").read()
    n = int.from_bytes(raw[12:16], "little")
    nb = [x for x in json.loads(raw[20:20 + n])["nodes"] if x.get("name") == "B"][0]["translation"]
    assert abs(nb[0] - 100) < 0.01 and abs(abs(nb[2]) - 20) < 0.01, nb                    # 导出的网页模型里也在对的位置
    print("直接写 bpy 的脚本：位置和父子关系都算对")

    # 5) 出错信息带行号
    r = build(cfg, "from qblib import *\na = box(10, 10, 10)\nb = cylinder(-5, 10)\n", "err")
    assert not r["ok"] and r["error"]["line"] == 3 and "d" in r["error"]["msg"], r
    r = build(cfg, "from qblib import *\na = box(10, 10, 10)\nc = hexbolt(8, 20)\n", "err2")
    assert not r["ok"] and r["error"]["type"] == "NameError" and r["error"]["line"] == 3
    print("报错定位：正确")
    print("\ntest_lib 全部通过")


if __name__ == "__main__":
    main()
