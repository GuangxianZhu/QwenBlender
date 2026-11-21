# -*- coding: utf-8 -*-
"""零件库测试：python tests/test_lib.py（需要能找到 Blender，或者当前 Python 装了 bpy）。"""
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
    assert any("穿模" in i for i in r["issues"]), r
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
    r = build(cfg, "from qblib import *\nb = box(40, 40, 20)\nhole(b, 8, (0, 0, 0), axis='z', depth=20)\n", "nohole")
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

    # 5) 出错信息带行号
    r = build(cfg, "from qblib import *\na = box(10, 10, 10)\nb = cylinder(-5, 10)\n", "err")
    assert not r["ok"] and r["error"]["line"] == 3 and "d" in r["error"]["msg"], r
    r = build(cfg, "from qblib import *\na = box(10, 10, 10)\nc = hexbolt(8, 20)\n", "err2")
    assert not r["ok"] and r["error"]["type"] == "NameError" and r["error"]["line"] == 3
    print("报错定位：正确")
    print("\ntest_lib 全部通过")


if __name__ == "__main__":
    main()
