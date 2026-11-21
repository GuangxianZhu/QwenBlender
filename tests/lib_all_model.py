# 把 qblib 的每个函数都跑一遍。test_lib.py 用它来检查：每个零件都是封闭实体。
from qblib import *

objs = []
makers = [
    lambda: box(20, 30, 10), lambda: rounded_box(30, 20, 8, 4), lambda: cylinder(20, 15),
    lambda: cone(20, 8, 15), lambda: cone(20, 0, 15), lambda: tube(20, 12, 15),
    lambda: sphere(20), lambda: torus(30, 4), lambda: prism(6, 17, 8),
    lambda: extrude([(0, 0), (20, 0), (20, 5), (5, 5), (5, 20), (0, 20)], 6),
    lambda: revolve([(0, 0), (10, 0), (10, 5), (4, 12), (0, 12)]),
    lambda: pipe([(0, 0, 0), (0, 0, 30), (30, 0, 30), (30, 20, 30)], 8, d_in=6, bend_r=8),
    lambda: pipe([(0, 0, 0), (0, 0, 30), (20, 0, 30)], 6, bend_r=6),
    lambda: spring(16, 2, 5, 6),
    lambda: hex_bolt(8, 30), lambda: hex_bolt(6, 20, thread=False), lambda: hex_bolt(10, 50, thread_len=20),
    lambda: hex_bolt(3, 8), lambda: hex_bolt(20, 60),
    lambda: socket_screw(5, 16), lambda: socket_screw(3, 8, thread=False),
    lambda: nut(8), lambda: nut(6, thread=False), lambda: nut(20), lambda: washer(8.4, 16, 1.6),
    lambda: threaded_rod(6, 25),
    lambda: spur_gear(2, 20, 10, bore=8), lambda: spur_gear(1, 12, 5), lambda: spur_gear(3, 40, 12, bore=20),
    lambda: ring_gear(2, 54, 10, 124), lambda: ring_gear(1, 30, 6, 40),
    lambda: bearing(8, 22, 7), lambda: bearing(20, 47, 14), lambda: flange(60, 30, 8, 46, 6, 6),
    lambda: l_bracket(20, 30, 25, 3),
    lambda: bevel(box(20, 20, 10), 2), lambda: chamfer(cylinder(20, 10), 1.5),
    lambda: hole(box(30, 30, 10), 8, (0, 0, 10)), lambda: hole(box(30, 30, 10), 6, (15, 0, 5), axis="x", depth=12),
    lambda: holes_circle(cylinder(50, 6), 5, 36, 8),
    lambda: union(box(20, 20, 10), at(cylinder(10, 20), 5, 5, 0)),
    lambda: intersect(box(20, 20, 20), at(sphere(26), 0, 0, 10)),
    lambda: cut(box(30, 30, 10), at(box(30, 10, 10), 0, 0, 5)),          # 刀具的面和工件的面重合
    lambda: mirror_copy(at(l_bracket(10, 20, 15, 2), 5, 0, 0), "x"),
    lambda: join([box(10, 10, 5), at(box(10, 10, 5), 20, 0, 0)]),
    lambda: cut(hex_bolt(8, 20), at(box(20, 2, 4), 0, 0, 3)),
    lambda: rot(cylinder(10, 30), 90, 0, 0), lambda: rot_about(box(10, 10, 10), "z", 45, (5, 5, 0)),
    lambda: stack(box(10, 10, 5), box(20, 20, 5)), lambda: beside(box(10, 10, 5), box(20, 20, 5), "-x", gap=2),
    lambda: center_on(sphere(8), box(20, 20, 20), "xyz"),
    lambda: array_circular(at(cylinder(4, 10), 15, 0, 0), 5)[-1], lambda: array_linear(box(5, 5, 5), 3, dx=8)[-1],
    lambda: color(box(10, 10, 10), "#ff8800", metal=0.2, rough=0.4),
    lambda: mat(box(10, 10, 10), "glass"),
]
for i, mk in enumerate(makers):
    o = mk()
    move(o, (i % 8) * 150, (i // 8) * 150, 0)
print("made", len(makers))
