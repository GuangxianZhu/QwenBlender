# 轴、轴承、轴承座：轴用 shaft_through 穿过去（孔自动打好），轴承用 on_axis 套到轴上，不用算旋转角
from qblib import *

housing = box(50, 40, 30)                          # 轴承座，x -25~25  y -20~20  z 0~30
mat(housing, "cast_iron")
part(housing, "Housing", cn="轴承座")

# 轴沿 X 穿过轴承座，两头各伸出 15：孔径 = 轴径 + 0.2
shaft = shaft_through(housing, (-40, 0, 15), (40, 0, 15), 8)
mat(shaft, "stainless")
part(shaft, "Shaft", cn="轴")

# 轴承孔 Φ22 深 7：从 +X 面往里沉。孔是横的，axis 写 "x"
hole(housing, 22, (25, 0, 15), axis="x", depth=7)

brg = bearing(8, 22, 7)                            # 内径等于轴径，自带的孔正好套在轴上
on_axis(brg, shaft, pos=40 + 25 - 3.5)             # 轴的起点在 x=-40，轴承中心要到 x=21.5，离起点 61.5
mat(brg, "steel")
part(brg, "Bearing", cn="轴承 608")

gear = spur_gear(2, 20, 8, bore=8)                 # 齿轮也一样；pos 不写就套在轴的正中间
on_axis(gear, shaft, pos=8)                        # 这里放在离轴的起点 8 mm 的地方
mat(gear, "brass")
part(gear, "Gear", cn="齿轮")
