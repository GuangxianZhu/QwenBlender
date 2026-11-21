# 皮带传动：两个皮带轮摆好，belt() 自己绕上去
from qblib import *

small = pulley(30, 12, bore=8, belt_d=5)            # d 是皮带中心线的直径，传动比按它算
big = pulley(90, 12, bore=12, belt_d=5)
at(big, 120, 0, 0)                                  # 两个轮子高度一样，皮带才不歪
b = belt(small, big)                                # 粗细、位置都从皮带轮上读
mat(small, "aluminum"); mat(big, "aluminum"); mat(b, "rubber")
part(small, "PulleySmall", cn="小皮带轮"); part(big, "PulleyBig", cn="大皮带轮"); part(b, "Belt", cn="皮带")
# 减速比 = 90 / 30 = 3，两个轮子转向相同。网页里大轮 speed = 小轮 speed / 3
# 要把整套立起来（轴线水平）：三个零件一起 rot_about(obj, "x", 90, (0, 0, 0))
