# 连杆机构的零件：link_bar 做杆，pin_joint 做铰点（打孔 + 销子一步完成），shaft_through 做固定的转轴
from qblib import *

# 四连杆（在 XZ 平面里动，销子沿 Y）：A、D 是机架上的两个固定铰点，B、C 是会动的铰点
A, B, C, D = (0, 0, 0), (0, 0, 20), (60, 0, 45), (70, 0, 0)
base = box(100, 6, 14)                             # 机架：一块立着的板，y -9 ~ -3
at(base, 35, -6, -7)
crank = link_bar(A, B, 10, 4)                      # 曲柄 AB，长 20，y -2 ~ 2（不用自己打孔）
rocker = link_bar(D, C, 10, 4)                     # 摇杆 DC，和曲柄在同一层
coupler = link_bar(B, C, 10, 4)                    # 连杆 BC
move(coupler, 0, 4, 0)                             # 连杆沿 Y 错开一个板厚，y 2 ~ 6，和另外两根不打架

pin_b = pin_joint(crank, coupler, B, 4)            # 铰点 B：两根杆各打一个孔，再穿一根销子
pin_c = pin_joint(coupler, rocker, C, 4)           # 铰点 C
shaft_a = shaft_through([base, crank], (0, -9, 0), (0, 2, 0), 5)      # 固定转轴 A：从机架里伸出来，穿过曲柄
shaft_d = shaft_through([base, rocker], (70, -9, 0), (70, 2, 0), 5)   # 固定转轴 D

for o, n, cn in ((base, "Base", "机架"), (crank, "Crank", "曲柄"), (coupler, "Coupler", "连杆"), (rocker, "Rocker", "摇杆"),
                 (pin_b, "PinB", "销 B"), (pin_c, "PinC", "销 C"), (shaft_a, "ShaftA", "转轴 A"), (shaft_d, "ShaftD", "转轴 D")):
    part(o, n, cn=cn)
# demo.json 里铰点直接写销子和轴的名字；销子写进它跟着动的那一组：
# {"type": "four_bar", "crank": ["Crank", "PinB"], "coupler": "Coupler", "rocker": ["Rocker", "PinC"],
#  "a": "ShaftA", "b": "PinB", "c": "PinC", "d": "ShaftD", "axis": "y", "speed": "rpm * 6"}
# 一根杆要从某点指向另一点（比如斜撑、摇杆上固定的长臂）：aim(零件, 起点, 终点, axis="x")，不用算旋转角
