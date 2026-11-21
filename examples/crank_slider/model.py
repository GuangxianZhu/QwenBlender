# 曲柄滑块机构：曲柄转一圈，活塞在缸筒里上下走一个来回。机构在 XZ 平面里运动，转动轴沿 Y
from qblib import *
import math

R = 15            # 曲柄半径（曲柄销到主轴中心的距离）
L = 60            # 连杆长度（两个销孔的中心距）
BORE = 30         # 缸径
PIN = 6           # 销子直径

crank_pin = (R, 0, 0)                               # 初始位置：曲柄销在 +X 方向
piston_pin = (0, 0, math.sqrt(L * L - R * R))       # 活塞销在主轴正上方，高度由勾股定理算出

# 曲柄 = 主轴 + 曲柄盘 + 曲柄销，合成一个零件。圆柱默认沿 Z，转 90° 让它沿 Y
shaft = cylinder(10, 30)
rot(shaft, 90, 0, 0)                                # 沿 Z 的圆柱绕 X 转 90° 后朝 -Y 伸出去
at(shaft, 0, -3, 0)                                 # 占 y -33 ~ -3
disc = cylinder(2 * R + 14, 6)
rot(disc, 90, 0, 0)
at(disc, 0, -3, 0)                                  # 占 y -9 ~ -3
pin = cylinder(PIN, 8)
rot(pin, 90, 0, 0)
at(pin, R, 5, 0)                                    # 占 y -3 ~ 5，穿过连杆大头
crank = join([disc, shaft, pin])
mat(crank, "dark_steel")
part(crank, "Crank", cn="曲柄", info="主轴带着曲柄盘转，盘上偏心 15 mm 的地方有一根曲柄销。", explode=(0, -40, 0))

# 连杆：两头各一个销孔，厚 4，在 y -2 ~ 2
rod = link_bar(crank_pin, piston_pin, 14, 4, hole_d=PIN + 0.2)
mat(rod, "aluminum")
part(rod, "Rod", cn="连杆", info="两头各一个孔：大头套在曲柄销上，小头套在活塞销上。长 60 mm。", explode=(0, -18, 0))

# 活塞：底部开一条槽让连杆小头伸进去，侧面打销孔
PH = 26
piston = cylinder(BORE, PH)
at(piston, 0, 0, piston_pin[2] - 10)
slot = box(20, 5, 20)
at(slot, 0, 0, piston_pin[2] - 12)
cut(piston, slot)
hole(piston, PIN + 0.2, (0, BORE / 2, piston_pin[2]), axis="y")
mat(piston, "aluminum")
part(piston, "Piston", cn="活塞", info="只能在缸筒里上下滑。连杆推它、拉它。", explode=(0, 0, 45))

wrist = cylinder(PIN, 24)
rot(wrist, 90, 0, 0)
at(wrist, 0, 12, piston_pin[2])                     # 占 y -12 ~ 12
mat(wrist, "steel")
part(wrist, "PistonPin", cn="活塞销", info="把连杆小头和活塞连在一起。", explode=(0, 40, 45))

# 缸筒：活塞走到最高和最低都还在里面
liner = tube(BORE + 10, BORE + 0.3, 62)
at(liner, 0, 0, 36)
mat(liner, "glass")
part(liner, "Cylinder", cn="缸筒", info="给活塞导向，让它只能沿直线走。", explode=(0, 0, 90))
