# 蜗轮蜗杆：蜗杆放平（轴线沿 X），蜗轮轴线竖直，mesh_worm 负责中心距和对齿
from qblib import *

M, TEETH = 2, 30                                    # 传动比 = 齿数 / 头数 = 30
w = worm(M, 70)                                     # 模数 2，长 70，单头，q=10 → 分度圆直径 20
rot(w, 0, 90, 0)                                    # 默认沿 Z，绕 Y 转 90° 变成沿 X
at(w, -35, 0, 40)                                   # 转完以后原点在左端面中心
mat(w, "steel")
part(w, "Worm", cn="蜗杆", info="转一圈，蜗轮只转过一个齿。")

wheel = worm_wheel(M, TEETH, 14, bore=10)           # module、starts、q 要和蜗杆一样
mesh_worm(wheel, w, side="+y")                      # 蜗轮放到蜗杆的 +Y 侧，中心距 = (20 + 60) / 2 = 40
mat(wheel, "brass")
part(wheel, "WormWheel", cn="蜗轮", info="30 齿。")
# 网页里的转速：蜗轮 speed = 蜗杆 speed / 30（蜗杆绕 x 转，蜗轮绕 z 转）
