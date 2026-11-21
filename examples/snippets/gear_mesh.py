# 齿轮对齿：用 mesh() 摆位置和转角，不用自己算相位（直齿、斜齿、内齿圈都行）
from qblib import *

# 一对直齿轮：先摆好一个，另一个 mesh 上去。angle 是它在第一个齿轮的哪个方向
g1 = spur_gear(2, 20, 10, bore=8)
g2 = spur_gear(2, 40, 10, bore=8)
mesh(g2, g1, angle=0)                              # g2 放到 g1 的 +X 方向，中心距 60

# 一对斜齿轮：螺旋角一正一负
h1 = helical_gear(2, 18, 12, 20, bore=6)
at(h1, 0, 120, 0)
h2 = helical_gear(2, 36, 12, -20, bore=8)
mesh(h2, h1, angle=90)

# 行星轮系：太阳轮 → 3 个行星轮 → 内齿圈。内齿圈齿数 = 太阳轮齿数 + 2 × 行星轮齿数
sun = spur_gear(2, 18, 10, bore=8)
at(sun, 200, 0, 0)
planets = []
for i in range(3):
    p = spur_gear(2, 18, 10, bore=6)
    mesh(p, sun, angle=120 * i)
    planets.append(p)
ring = ring_gear(2, 54, 10, 124)
at(ring, 200, 0, 0)                                # 内齿圈和太阳轮同心
mesh(ring, planets[0])                             # 只转内齿圈，让它和行星轮对上齿
