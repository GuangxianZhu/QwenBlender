# 连杆机构的零件：link_bar 按两个销孔的位置直接生成杆，原点在第一个销孔
from qblib import *

# 四连杆（在 XZ 平面里动，销子沿 Y）：A、D 是机架上的两个固定铰点
A, B, C, D = (0, 0, 0), (0, 0, 20), (60, 0, 45), (70, 0, 0)
crank = link_bar(A, B, 10, 3, hole_d=4)            # 曲柄 AB，长 20
coupler = link_bar(B, C, 10, 3, hole_d=4)          # 连杆 BC
rocker = link_bar(D, C, 10, 3, hole_d=4)           # 摇杆 DC
move(coupler, 0, 3, 0)                             # 三根杆沿 Y 错开一个板厚，互相不打架
move(rocker, 0, 6, 0)
base = box(100, 14, 6)
at(base, 35, 3, -11)
for o, n, cn in ((crank, "Crank", "曲柄"), (coupler, "Coupler", "连杆"), (rocker, "Rocker", "摇杆"), (base, "Base", "机架")):
    part(o, n, cn=cn)
# demo.json 里：{"type": "four_bar", "crank": "Crank", "coupler": "Coupler", "rocker": "Rocker",
#               "a": [0,0,0], "b": [0,0,20], "c": [60,0,45], "d": [70,0,0], "axis": "y", "speed": "rpm * 6"}
