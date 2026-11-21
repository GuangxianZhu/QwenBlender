# -*- coding: utf-8 -*-
"""demo.json 校验测试（不需要 Blender）：python tests/test_page.py"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from qb import page  # noqa: E402

PARTS = [{"name": n} for n in ("Crank", "Rod", "Piston", "PistonPin", "Cylinder")]
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

    c = copy.deepcopy(GOOD); c["steps"][2]["anim"].append({"part": "Crank", "type": "spinn", "speed": 3})
    assert any("spinn" in e and "spin" in e for e in errs(c)), errs(c)
    print("test_page 通过")


if __name__ == "__main__":
    main()
