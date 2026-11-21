# 钣金折弯件：从侧面画板厚中心线的折线，给板宽和板厚
from qblib import *

# Z 形支架：底边 40 → 立边 30 → 顶边 30，板宽 25，厚 2
br = bent_plate([(0, 0), (40, 0), (40, 30), (70, 30)], 25, 2)
hole(br, 5, (15, 0, 1))                             # 底边上的安装孔：底边顶面在 z = 板厚 / 2 = 1
hole(br, 5, (58, 0, 31))                            # 顶边上的孔：顶面在 z = 30 + 1
mat(br, "zinc")
part(br, "Bracket", cn="Z 形支架")

# U 形槽：开口朝上
u = bent_plate([(0, 30), (0, 0), (50, 0), (50, 30)], 40, 1.5, bend_r=3)
move(u, 0, 60, 0)
mat(u, "stainless")
part(u, "Channel", cn="U 形槽")
