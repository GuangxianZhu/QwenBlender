# 法兰连接：两段管子各带一个法兰，中间夹垫片，4 颗螺栓拉紧
from qblib import *
import math

PIPE_D, PIPE_ID = 34, 28      # 管子外径、内径
FL_D, FL_T = 76, 8            # 法兰外径、厚度
BC = 56                       # 螺栓孔分布圆直径
GASKET_T = 2
H1 = 50                       # 下段管子的高度

# 下段管子：立着
pipe_a = pipe([(0, 0, 0), (0, 0, H1)], PIPE_D, d_in=PIPE_ID)
mat(pipe_a, "stainless")
part(pipe_a, "PipeLower", cn="下段管", info="水从这里进来。内径 28 mm。", explode=(0, 0, -30))

# 下法兰：焊在下段管的顶上
fl_a = flange(FL_D, PIPE_ID, FL_T, BC, 4, 6.6)
at(fl_a, 0, 0, H1)
mat(fl_a, "steel")
part(fl_a, "FlangeLower", cn="下法兰", info="焊在管口上的圆盘，上面有 4 个螺栓孔。", explode=(0, 0, -14))

# 垫片：夹在两个法兰中间
gasket = tube(48, PIPE_ID, GASKET_T)
stack(gasket, fl_a)
mat(gasket, "rubber")
part(gasket, "Gasket", cn="垫片", info="软的橡胶圈。被两个法兰压扁后把缝堵死，水就漏不出来。", explode=(0, 0, 0))

# 上法兰
fl_b = flange(FL_D, PIPE_ID, FL_T, BC, 4, 6.6)
stack(fl_b, gasket)
mat(fl_b, "steel")
part(fl_b, "FlangeUpper", cn="上法兰", info="和下法兰一样，面对面装。", explode=(0, 0, 14))

# 上段管子：往上走一段再拐向 +X
z0 = H1 + FL_T + GASKET_T + FL_T
pipe_b = pipe([(0, 0, z0), (0, 0, z0 + 45), (60, 0, z0 + 45)], PIPE_D, d_in=PIPE_ID, bend_r=24)
mat(pipe_b, "stainless")
part(pipe_b, "PipeUpper", cn="上段管", info="带一个 90° 弯头，水拐弯向右流走。", explode=(0, 0, 32))

# 4 颗螺栓：头压在上法兰顶面，杆穿过两个法兰和垫片的位置
GRIP = FL_T + GASKET_T + FL_T
for i in range(4):
    a = math.radians(90 * i)
    x, y = BC / 2 * math.cos(a), BC / 2 * math.sin(a)
    b = hex_bolt(6, 28, thread=False)
    at(b, x, y, z0)
    mat(b, "zinc")
    part(b, "Bolt%d" % (i + 1), cn="螺栓 %d" % (i + 1), info="M6×28。4 颗对角轮流拧紧，法兰才能压得平。", explode=(0, 0, 50))
    n = nut(6, thread=False)
    at(n, x, y, z0 - GRIP - 4.8)
    mat(n, "zinc")
    part(n, "Nut%d" % (i + 1), cn="螺母 %d" % (i + 1), info="在下法兰底面拧紧。", explode=(0, 0, -44))
