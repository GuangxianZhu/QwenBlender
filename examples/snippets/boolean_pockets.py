# 布尔：挖槽、开窗、合并。刀具要比工件多伸出去一点，别让两个面正好重合
from qblib import *

body = box(60, 40, 20)

pocket = rounded_box(40, 24, 12, 4)                # 顶面的圆角凹槽，深 10
at(pocket, 0, 0, 10)                               # 底在 z=10，顶在 z=22，比工件顶面高出 2
cut(body, pocket)

window = box(20, 50, 6)                            # 侧面的通槽：沿 Y 方向比工件长 10
at(window, 0, 0, 2)
cut(body, window)

boss = cylinder(12, 8)                             # 加一个凸台：往工件里埋 1，再合并
at(boss, 22, 12, 19)
union(body, boss)

bevel(body, 0.6, segments=2)                       # 最后统一倒小圆角
mat(body, "aluminum")
part(body, "Body", cn="壳体")
