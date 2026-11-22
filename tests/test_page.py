# -*- coding: utf-8 -*-
"""demo.json 校验测试（不需要 Blender）：python tests/test_page.py"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qb import page, tools  # noqa: E402

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

    c = copy.deepcopy(GOOD); c["steps"][2]["anim"].append({"part": "Crank", "type": "spinn", "speed": 3})
    assert any("spinn" in e and "spin" in e for e in errs(c)), errs(c)
    print("test_page 通过")


if __name__ == "__main__":
    main()
