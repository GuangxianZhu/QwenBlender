# 镜像和阵列：对称件做一半，重复件做一个
from qblib import *

rail = box(100, 10, 8)
at(rail, 0, 20, 0)
rail_r = mirror_copy(rail, "y")                    # 关于 XZ 平面镜像到 y=-20 那一侧

post = cylinder(6, 30)
at(post, -40, 20, 8)
posts = array_linear(post, 5, dx=20)               # 沿 X 每隔 20 一个，共 5 个（含原件）
posts += [mirror_copy(p, "y") for p in posts]

frame = join([rail, rail_r] + posts)               # 合成一个零件（只是放在一起，不做布尔）
mat(frame, "steel")
part(frame, "Frame", cn="护栏", info="两根横梁加 10 根立柱。")
