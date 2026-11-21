# 齿轮减速：20 齿小齿轮带 40 齿大齿轮，装在底板的两根轴上
from qblib import *

M = 2                 # 模数
Z1, Z2 = 20, 40       # 齿数
W = 10                # 齿宽
SHAFT = 8             # 轴径
DIST = M * (Z1 + Z2) / 2      # 中心距 = 60
BASE_T = 6            # 底板厚
GAP = 4               # 齿轮底面离底板的高度（垫套的高度）

# 底板：盖住两根轴，四周留边
base = rounded_box(DIST + 70, 100, BASE_T, 6)
at(base, DIST / 2, 0, 0)
mat(base, "gray_plastic")
part(base, "Base", cn="底板", info="固定两根轴，保证中心距正好是 60 mm。", explode=(0, 0, -30))

# 两根轴：立在底板上
shaft_h = GAP + W + 6
s1 = cylinder(SHAFT, shaft_h)
stack(s1, base)
at(s1, 0, 0, BASE_T)
mat(s1, "stainless")
part(s1, "ShaftA", cn="主动轴", info="小齿轮的轴。", explode=(0, 0, -12))

s2 = cylinder(SHAFT, shaft_h)
at(s2, DIST, 0, BASE_T)
mat(s2, "stainless")
part(s2, "ShaftB", cn="从动轴", info="大齿轮的轴。", explode=(0, 0, -12))

# 垫套：把齿轮垫高，不蹭底板
sp1 = tube(14, SHAFT, GAP)
at(sp1, 0, 0, BASE_T)
mat(sp1, "brass")
part(sp1, "SpacerA", cn="垫套 A", info="垫在小齿轮下面。", explode=(0, 0, 8))

sp2 = tube(14, SHAFT, GAP)
at(sp2, DIST, 0, BASE_T)
mat(sp2, "brass")
part(sp2, "SpacerB", cn="垫套 B", info="垫在大齿轮下面。", explode=(0, 0, 8))

# 小齿轮：0 度方向是一个齿，正对大齿轮
g1 = spur_gear(M, Z1, W, bore=SHAFT)
at(g1, 0, 0, BASE_T + GAP)
mat(g1, "orange")
part(g1, "GearA", cn="小齿轮（20 齿）", info="主动轮。分度圆直径 = 模数 × 齿数 = 40 mm。", explode=(0, 0, 34))

# 大齿轮：转半个齿，让齿槽对着小齿轮的齿
g2 = spur_gear(M, Z2, W, bore=SHAFT)
rot(g2, 0, 0, 180 / Z2)
at(g2, DIST, 0, BASE_T + GAP)
mat(g2, "blue")
part(g2, "GearB", cn="大齿轮（40 齿）", info="从动轮。分度圆直径 80 mm，齿数是小齿轮的 2 倍，所以转得慢一半。", explode=(0, 0, 34))
