# 轴、轴承、轴承座：用 stack / center_on 对位，不心算坐标
from qblib import *

housing = box(50, 40, 30)
bore = cylinder(22, 12)                            # 轴承孔 Φ22 深 12
rot(bore, 0, 90, 0)                                # 圆柱默认沿 Z，绕 Y 转 90° 变成沿 X
center_on(bore, housing, "yz")
beside(bore, housing, "+x", gap=-12)               # 从 +X 面往里沉 12
cut(housing, bore)
through = cylinder(10, 60)                         # 轴的通孔 Φ10
rot(through, 0, 90, 0)
center_on(through, housing, "xyz")
cut(housing, through)
mat(housing, "cast_iron")
part(housing, "Housing", cn="轴承座")

brg = bearing(8, 22, 7)
rot(brg, 0, 90, 0)                                 # 轴承轴线也转到 X
center_on(brg, housing, "yz")
beside(brg, housing, "+x", gap=-12)                # 贴到孔底
mat(brg, "steel")
part(brg, "Bearing", cn="轴承 608")

shaft = cylinder(8, 80)
rot(shaft, 0, 90, 0)
center_on(shaft, housing, "xyz")
mat(shaft, "stainless")
part(shaft, "Shaft", cn="轴")
allow_overlap(shaft, brg)                          # 轴和轴承内圈是紧配合，声明一下
