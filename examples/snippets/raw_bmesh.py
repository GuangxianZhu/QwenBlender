# qblib 做不出来的形状：直接用 bmesh 建网格，再交给 qblib 上材质、登记
# 规则：点的坐标用毫米；面要围成封闭的实体；最后 link 到场景里
from qblib import *
import bpy, bmesh, math

bm = bmesh.new()
n, rings = 48, 24
rows = []
for i in range(rings + 1):                         # 一个扭转的方柱：每升高一层转一点
    z = 60 * i / rings
    twist = math.radians(90 * i / rings)
    row = []
    for j in range(4):
        a = twist + math.radians(45 + 90 * j)
        row.append(bm.verts.new((12 * math.cos(a), 12 * math.sin(a), z)))
    rows.append(row)
for i in range(rings):
    for j in range(4):
        k = (j + 1) % 4
        bm.faces.new((rows[i][j], rows[i][k], rows[i + 1][k], rows[i + 1][j]))
bm.faces.new(list(reversed(rows[0])))              # 底面
bm.faces.new(rows[-1])                             # 顶面
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

mesh = bpy.data.meshes.new("Twist")
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("Twist", mesh)
bpy.context.scene.collection.objects.link(obj)     # 不 link 就不算零件

mat(obj, "brass")
part(obj, "TwistBar", cn="麻花方柱", info="用 bmesh 逐层生成。")
