# 带孔的板：四角安装孔 + 中间大孔 + 倒圆角
from qblib import *

plate = rounded_box(80, 50, 5, 6)                 # 80×50，厚 5，四角 R6
for x in (-32, 32):
    for y in (-17, 17):
        hole(plate, 4.5, (x, y, 5))               # 孔口在顶面 z=5，从上往下钻通
hole(plate, 20, (0, 0, 5))                        # 中间 Φ20 大孔
hole(plate, 8, (40, 0, 2.5), axis="x", depth=10)  # 侧面的盲孔：孔口朝 +X，深 10
mat(plate, "aluminum")
part(plate, "Plate", cn="安装板", info="四角 Φ4.5 安装孔。")
