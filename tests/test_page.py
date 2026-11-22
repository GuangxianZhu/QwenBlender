# -*- coding: utf-8 -*-
"""demo.json 校验测试（不需要 Blender）：python tests/test_page.py"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qb import calc, page, tools  # noqa: E402

PARTS = [{"name": n, "center": c} for n, c in (("Crank", [0, -12, 0]), ("Rod", [7.5, 0, 29]), ("Piston", [0, 0, 61]),
                                              ("PistonPin", [0, 0, 58.09]), ("Cylinder", [10, 0, 5]))]
GOOD = json.load(open(os.path.join(ROOT, "examples", "crank_slider", "demo.json"), encoding="utf-8"))


def errs(cfg, parts=PARTS):
    return page.validate(cfg, parts)[0]


def main():
    assert errs(GOOD) == [], errs(GOOD)
    link = lambda c: c["steps"][2]["anim"][0]

    c = copy.deepcopy(GOOD); link(c)["rod"] = "Rodd"
    assert any("Rodd" in e and "Rod" in e for e in errs(c)), errs(c)                     # 零件名写错
    c = copy.deepcopy(GOOD); del link(c)["slider_pin"]
    assert any("slider_pin" in e for e in errs(c)), errs(c)                              # 缺字段
    c = copy.deepcopy(GOOD); link(c)["slider_pin"] = [10, 0, 5]
    assert any("转不了整圈" in e for e in errs(c)), errs(c)                                # 连杆比曲柄半径还短
    c = copy.deepcopy(GOOD); link(c)["angle"] = "rpm"
    assert any("只写一个" in e for e in errs(c)), errs(c)                                  # speed 和 angle 都写了
    c = copy.deepcopy(GOOD); c["steps"][2]["readouts"][1]["expr"] = "m_poss"
    assert any("m_poss" in e for e in errs(c)), errs(c)                                  # 变量名写错
    c = copy.deepcopy(GOOD); link(c)["slide"] = "y"
    assert any("同一个方向" in e for e in errs(c)), errs(c)                                # 滑动方向和转轴一样

    fb = {"title": "t", "params": [{"id": "ang", "min": 0, "max": 60, "value": 0}],
          "steps": [{"title": "s", "text": "x", "anim": [
              {"type": "four_bar", "id": "f", "crank": "Crank", "coupler": "Rod", "rocker": "Piston",
               "a": [0, 0, 0], "b": [0, 0, 20], "c": [60, 0, 45], "d": [70, 0, 0], "axis": "y", "speed": 60}],
              "readouts": [{"label": "摇杆", "expr": "f_rocker"}]}]}
    assert errs(fb) == [], errs(fb)                                                      # 曲柄摇杆：能转整圈
    c = copy.deepcopy(fb); c["steps"][0]["anim"][0]["b"] = [0, 0, 80]
    assert any("转不了整圈" in e for e in errs(c)), errs(c)                                # 曲柄太长
    c["steps"][0]["anim"][0].pop("speed"); c["steps"][0]["anim"][0]["angle"] = "ang"
    assert errs(c) == [], errs(c)                                                        # 改成用滑条给角度就可以

    # 铰点、pivot 可以直接写零件名
    assert link(GOOD)["slider_pin"] == "PistonPin" and link(page.resolve_points(GOOD, PARTS))["slider_pin"] == [0, 0, 58.09]
    assert link(GOOD)["slider_pin"] == "PistonPin"                                       # 原来的配置不动
    c = copy.deepcopy(GOOD); link(c)["slider_pin"] = "PistonPinn"
    assert any("PistonPinn" in e and "PistonPin" in e for e in errs(c)), errs(c)         # 名字写错
    c = copy.deepcopy(GOOD); link(c)["slider_pin"] = "Cylinder"
    assert any("转不了整圈" in e for e in errs(c)), errs(c)                                # 按零件中心算出来连杆太短
    c = copy.deepcopy(GOOD); link(c)["hollow"] = True
    c["steps"][2]["anim"].append({"part": "Crank", "type": "spin", "speed": 3, "pivot": "PistonPin", "hollow": True})
    e, w = page.validate(c, PARTS)
    assert e == [] and not any("hollow" in x for x in w), (e, w)

    # 网页里写的摆角、行程，要和算出来的一致
    tn = lambda text, rg, parts=(): tools.text_number_problems({"steps": [{"title": "s", "text": text}]}, list(parts), [rg])
    assert tn("摇臂在 56° 到 113° 之间摆，摆角约 57°。", {"swing": [67.8]})
    assert not tn("摆角约 68°，初始摆角 0°。", {"swing": [67.8]}) and not tn("摆角从 -5.9° 到 +61.9°。", {"swing": [67.8]})
    assert not tn("摆角 51° ~ 119°", {"swing": [67.8]}) and not tn("曲柄转一圈，转速 10 转/分", {"swing": [67.8]})
    assert tn("活塞的行程是 30 毫米", {"stroke": [39.8]}) and not tn("行程 40 mm", {"stroke": [39.8]})
    assert tn("x", {"swing": [67.8]}, [{"name": "Rocker", "info": "摆角约 57°"}])
    assert tools.text_number_problems({"steps": [{"title": "s", "text": "x", "readouts": [
        {"label": "摆角范围", "expr": "57", "unit": "°"}, {"label": "摆角", "expr": "f_rocker", "unit": "°"}]}]}, [], [{"swing": [67.8]}])

    # 机构计算器：和逐点扫出来的结果对得上
    import math

    def sweep(a, b, cc, d):
        angs = []
        for i in range(3600):
            th = math.radians(i / 10)
            ex, ey = a * math.cos(th) - d, a * math.sin(th)
            e = math.hypot(ex, ey)
            angs.append(math.degrees(math.atan2(ey, ex) - math.acos((cc * cc + e * e - b * b) / (2 * cc * e))) % 360)
        return max(angs) - min(angs)

    for L in ((20, 75, 45, 60), (20, 70, 40, 60), (20, 50, 25, 50), (20, 75, 60, 40)):
        r = calc.four_bar_numbers(*L)
        assert r["ok"] and abs(r["swing"] - sweep(*L)) < 0.05, (L, r["swing"], sweep(*L))
        assert abs(r["go"] + r["back"] - 360) < 1e-6 and 0 < r["mu_min"] <= 90
    assert not calc.four_bar_numbers(30, 40, 25, 60)["ok"] and "转不了整圈" in calc.run({"kind": "four_bar", "crank": 30, "coupler": 40, "rocker": 25, "frame": 60})
    t = calc.run({"kind": "four_bar", "crank": 20, "want_swing": 90})
    assert "摇杆取 28.28" in t and "摆角 90°" in t, t
    r = calc.crank_slider_numbers(15, 60)
    assert r["ok"] and abs(r["stroke"] - 30) < 1e-9 and abs(calc.crank_slider_numbers(10, math.hypot(50, 23), 23)["stroke"] - 22.11) < 0.01
    assert "转不了整圈" in calc.run({"kind": "crank_slider", "crank": 20, "rod": 15})
    assert "转向相反" in calc.run({"kind": "gear", "z1": 20, "z2": 40}) and "转向相同" in calc.run({"kind": "gear", "z1": 20, "z2": 60, "internal": True})
    assert "减速比 30 : 1" in calc.run({"kind": "worm", "teeth": 30}) and "中心距 40" in calc.run({"kind": "worm", "teeth": 30, "module": 2})
    assert "减速比 4 : 1" in calc.run({"kind": "planetary", "sun": 18, "ring": 54}) and "奇数" in calc.run({"kind": "planetary", "sun": 18, "ring": 55})
    assert "8 圈" in calc.run({"kind": "screw", "pitch": 1.25, "travel": 10}) and "0.3333" in calc.run({"kind": "belt", "d1": 30, "d2": 90})
    assert "z2" in calc.run({"kind": "gear", "z1": 20}) and "没有" in calc.run({"kind": "cam"})

    # 前后两次问题的对比：数字变了还算同一个问题
    fixed, fresh = tools.compare_issues(["穿模：A 和 B 互相扎进去了，最深约 2.00 mm，最深的地方在 (1, 2, 3) 附近", "法线反了：C 的面朝里"],
                                        ["穿模：A 和 B 互相扎进去了，最深约 1.20 mm，最深的地方在 (1, 2, 4) 附近", "穿模：A 和 D 互相扎进去了，最深约 3 mm"])
    assert fixed == ["法线反了：C 的面朝里"] and len(fresh) == 1 and "A 和 D" in fresh[0], (fixed, fresh)

    c = copy.deepcopy(GOOD); c["steps"][2]["anim"].append({"part": "Crank", "type": "spinn", "speed": 3})
    assert any("spinn" in e and "spin" in e for e in errs(c)), errs(c)
    print("test_page 通过")


if __name__ == "__main__":
    main()
