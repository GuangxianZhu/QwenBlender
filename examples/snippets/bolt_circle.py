# 圆周阵列：一圈螺栓、螺钉沉进盖板
from qblib import *
import math

cover = cylinder(60, 6)
holes_circle(cover, 4.5, 46, 6)                    # 分布圆 Φ46 上 6 个 Φ4.5 通孔
mat(cover, "aluminum")
part(cover, "Cover", cn="端盖")

for i in range(6):
    a = math.radians(60 * i)
    s = socket_screw(4, 12, thread=False)          # 零件多的时候用光杆，快
    at(s, 23 * math.cos(a), 23 * math.sin(a), 6)   # 螺钉头的下表面压在盖板顶面 z=6
    mat(s, "dark_steel")
    part(s, "Screw%d" % (i + 1), cn="螺钉 %d" % (i + 1))
# 另一种写法：做一个，再 array_circular(s, 6) 复制一圈（复制出来的要分别 part() 登记）
