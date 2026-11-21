# 自定义轮廓：画一圈点再拉伸（T 型槽、异形板、支架侧板都这么做）
from qblib import *
import math

# 1) 直线轮廓：T 形截面，沿 Z 拉 60
t_bar = extrude([(-15, 0), (15, 0), (15, 4), (3, 4), (3, 20), (-3, 20), (-3, 4), (-15, 4)], 60)

# 2) 带圆弧的轮廓：用循环算点。这里是一个腰形（两头半圆）
pts = []
for i in range(17):                                # 右半圆
    a = math.radians(-90 + 180 * i / 16)
    pts.append((20 + 8 * math.cos(a), 8 * math.sin(a)))
for i in range(17):                                # 左半圆
    a = math.radians(90 + 180 * i / 16)
    pts.append((-20 + 8 * math.cos(a), 8 * math.sin(a)))
slot_plate = extrude(pts, 3)
at(slot_plate, 0, 40, 0)

# 3) 拉伸方向不是 Z：先沿 Z 拉，再转。绕 X 转 90° 后原来的 +Z 变成 -Y
rib = extrude([(0, 0), (30, 0), (0, 20)], 4)       # 三角形筋板
rot(rib, 90, 0, 0)
at(rib, 0, -40, 0)
