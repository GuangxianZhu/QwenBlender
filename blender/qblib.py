# -*- coding: utf-8 -*-
"""qblib —— 参数化零件库（在 Blender 里运行）

约定
- 单位：毫米；角度：度；Z 轴朝上。
- 基本体的原点在「底面中心」，向 +Z 生长（球、圆环的原点在中心）。
- 螺栓/螺钉的原点在「头部下表面中心」，杆朝 -Z（放在被压紧的表面上即可）。
- 每个函数返回一个 Blender 物体；最后留在场景里的网格物体就是零件。
- 用 part() 给零件起英文名、中文名和说明，网页演示会用到。

model.py 里直接写：
    from qblib import *
"""
import math

import bpy
import bmesh  # noqa: E402  (bpy 要先导入)
from mathutils import Euler, Matrix, Vector

__all__ = [
    # 基本体
    "box", "rounded_box", "cylinder", "cone", "tube", "sphere", "torus", "prism",
    "extrude", "revolve", "pipe", "spring",
    # 机械件
    "hex_bolt", "socket_screw", "nut", "screw_on", "washer", "threaded_rod", "spur_gear", "ring_gear", "helical_gear", "worm", "worm_wheel",
    "mesh", "mesh_worm", "pulley", "belt", "bent_plate", "link_bar",
    "bearing", "flange", "l_bracket",
    # 加工
    "union", "cut", "intersect", "hole", "holes_circle", "bevel", "chamfer",
    # 摆放
    "at", "move", "rot", "rot_about", "stack", "beside", "center_on",
    "copy", "mirror_copy", "array_circular", "array_linear", "join", "delete",
    # 信息
    "bbox", "part", "mat", "color", "allow_overlap", "allow_float",
    "MATERIALS",
]

# ---------------------------------------------------------------- 内部工具

_counter = {}


def _auto_name(base):
    _counter[base] = _counter.get(base, 0) + 1
    return "%s_%d" % (base, _counter[base])


def _update():
    bpy.context.view_layer.update()


def _smooth(mesh, angle=35.0):
    """按角度平滑着色（兼容不同 Blender 版本）。"""
    if not mesh.polygons:
        return
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if hasattr(mesh, "set_sharp_from_angle"):
        mesh.set_sharp_from_angle(angle=math.radians(angle))
    elif hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(angle)
    mesh.update()


def _finish(bm, name, base, smooth=35.0):
    """bmesh → 物体，放进场景。"""
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name or _auto_name(base))
    bm.to_mesh(mesh)
    bm.free()
    _smooth(mesh, smooth)
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    _update()
    return obj


def _check_pos(**kw):
    for k, v in kw.items():
        if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ValueError("参数 %s 必须是大于 0 的数，现在是 %r" % (k, v))


def _segs(d, segments=None):
    if segments:
        return max(8, int(segments))
    return int(min(128, max(32, round(d * 0.75) * 4)))


def _ring(bm, r, z, n, phase=0.0):
    return [bm.verts.new((r * math.cos(phase + 2 * math.pi * i / n),
                          r * math.sin(phase + 2 * math.pi * i / n), z)) for i in range(n)]


def _bridge(bm, a, b):
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))


def _cap(bm, ring, flip=False):
    vs = list(reversed(ring)) if flip else list(ring)
    bm.faces.new(vs)


def _poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
        s += x1 * y2 - x2 * y1
    return s / 2


def _apply_modifier(obj, mod):
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.remove(mod)
    old = obj.data
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    _update()


def _clean_mesh(mesh):
    """合并重合点、去掉退化面，返回开口边的数量。"""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    bad = sum(1 for e in bm.edges if not e.is_manifold)
    bm.to_mesh(mesh)
    bm.free()
    return bad


def _boolean(a, b, op):
    if a is None or b is None:
        raise ValueError("布尔运算的物体不能是 None")
    if a is b:
        raise ValueError("布尔运算的两个物体是同一个：%s" % a.name)
    if len(a.data.polygons) == 0 or len(b.data.polygons) == 0:
        raise ValueError("布尔运算的物体没有面：%s / %s" % (a.name, b.name))
    _update()
    loc0 = b.location.copy()
    best = None
    # 两个物体的点、边正好重合时，结果偶尔会破面：换求解器，或者把刀具挪 0.0002 mm 再试，取第一个封闭的结果
    n1, n2 = (1.3e-4, 0.7e-4, 1.1e-4), (-2.1e-4, 1.9e-4, -0.6e-4)
    for solver, nudge in (("EXACT", None), ("MANIFOLD", None), ("EXACT", n1), ("MANIFOLD", n1), ("EXACT", n2)):
        m = a.modifiers.new("qb_bool", "BOOLEAN")
        m.operation = op
        m.object = b
        try:
            m.solver = solver
        except TypeError:           # 老版本没有 MANIFOLD 求解器
            a.modifiers.remove(m)
            continue
        b.location = loc0 + Vector(nudge) if nudge else loc0
        _update()
        dg = bpy.context.evaluated_depsgraph_get()
        res = bpy.data.meshes.new_from_object(a.evaluated_get(dg))
        a.modifiers.remove(m)
        bad = _clean_mesh(res) if len(res.polygons) else 10 ** 9
        if best is None or bad < best[0]:
            if best is not None:
                bpy.data.meshes.remove(best[1])
            best = (bad, res)
        else:
            bpy.data.meshes.remove(res)
        if bad == 0:
            break
    b.location = loc0
    _update()
    if best is None or len(best[1].polygons) == 0:
        if best is not None:
            bpy.data.meshes.remove(best[1])
        raise ValueError("布尔运算后 %s 变成空的了（两个物体可能没有重叠，或者被完全切掉）" % a.name)
    old = a.data
    best[1].name = old.name
    a.data = best[1]
    if old.users == 0:
        bpy.data.meshes.remove(old)
    _smooth(a.data)
    _update()
    return a


def _as_vec3(v, what="向量"):
    try:
        x, y, z = (float(c) for c in v)
    except Exception:
        raise ValueError("%s 要写成 (x, y, z) 三个数，现在是 %r" % (what, v))
    return Vector((x, y, z))


_AXES = {"x": Vector((1, 0, 0)), "y": Vector((0, 1, 0)), "z": Vector((0, 0, 1)),
         "+x": Vector((1, 0, 0)), "+y": Vector((0, 1, 0)), "+z": Vector((0, 0, 1)),
         "-x": Vector((-1, 0, 0)), "-y": Vector((0, -1, 0)), "-z": Vector((0, 0, -1))}


def _axis(a):
    if isinstance(a, str):
        k = a.lower().strip()
        if k not in _AXES:
            raise ValueError("轴要写 'x' 'y' 'z'（可带 + -），现在是 %r" % a)
        return _AXES[k].copy()
    return _as_vec3(a, "轴").normalized()


def _align_z_to(axis):
    """把 +Z 转到 axis 方向的旋转矩阵。"""
    return Vector((0, 0, 1)).rotation_difference(_axis(axis)).to_matrix().to_4x4()


# ---------------------------------------------------------------- 基本体

def box(sx, sy, sz, name=None):
    """长方体。sx×sy 是底面，sz 是高。原点在底面中心。"""
    _check_pos(sx=sx, sy=sy, sz=sz)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, sz / 2), verts=bm.verts)
    return _finish(bm, name, "Box")


def rounded_box(sx, sy, sz, r, name=None):
    """四个竖棱倒圆角的长方体（俯视是圆角矩形）。r 是圆角半径。"""
    _check_pos(sx=sx, sy=sy, sz=sz, r=r)
    r = min(r, sx / 2 - 1e-3, sy / 2 - 1e-3)
    pts = []
    n = 8
    for cx, cy, a0 in ((sx / 2 - r, sy / 2 - r, 0), (-sx / 2 + r, sy / 2 - r, 90),
                       (-sx / 2 + r, -sy / 2 + r, 180), (sx / 2 - r, -sy / 2 + r, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return extrude(pts, sz, name=name or _auto_name("RoundedBox"))


def cylinder(d, h, name=None, segments=None):
    """圆柱。d 直径，h 高。轴线沿 Z，原点在底面圆心。"""
    _check_pos(d=d, h=h)
    return cone(d, d, h, name=name or _auto_name("Cylinder"), segments=segments)


def cone(d1, d2, h, name=None, segments=None):
    """圆台/圆锥。d1 底面直径，d2 顶面直径（0 就是尖的），h 高。"""
    _check_pos(h=h)
    if d1 < 0 or d2 < 0 or (d1 <= 0 and d2 <= 0):
        raise ValueError("cone 的直径不能是负数，且不能两个都是 0")
    n = _segs(max(d1, d2), segments)
    bm = bmesh.new()
    if d1 > 0:
        a = _ring(bm, d1 / 2, 0, n)
        _cap(bm, a, flip=True)
    else:
        a = None
        va = bm.verts.new((0, 0, 0))
    if d2 > 0:
        b = _ring(bm, d2 / 2, h, n)
        _cap(bm, b)
    else:
        b = None
        vb = bm.verts.new((0, 0, h))
    if a and b:
        _bridge(bm, a, b)
    elif a:
        for i in range(n):
            bm.faces.new((a[i], a[(i + 1) % n], vb))
    else:
        for i in range(n):
            bm.faces.new((va, b[(i + 1) % n], b[i]))
    return _finish(bm, name, "Cone")


def tube(d_out, d_in, h, name=None, segments=None):
    """空心圆管。d_out 外径，d_in 内径，h 高。"""
    _check_pos(d_out=d_out, d_in=d_in, h=h)
    if d_in >= d_out:
        raise ValueError("tube 的内径 d_in=%s 必须小于外径 d_out=%s" % (d_in, d_out))
    n = _segs(d_out, segments)
    bm = bmesh.new()
    o0, o1 = _ring(bm, d_out / 2, 0, n), _ring(bm, d_out / 2, h, n)
    i0, i1 = _ring(bm, d_in / 2, 0, n), _ring(bm, d_in / 2, h, n)
    _bridge(bm, o0, o1)
    _bridge(bm, i1, i0)
    _bridge(bm, o1, i1)
    _bridge(bm, i0, o0)
    return _finish(bm, name, "Tube")


def sphere(d, name=None, segments=None):
    """球。d 直径。原点在球心。"""
    _check_pos(d=d)
    n = _segs(d, segments)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=n, v_segments=max(8, n // 2), radius=d / 2)
    return _finish(bm, name, "Sphere", smooth=180)


def torus(d_major, d_minor, name=None):
    """圆环（O 形圈）。d_major 是环中心线的直径，d_minor 是线径。原点在中心，躺在 XY 面。"""
    _check_pos(d_major=d_major, d_minor=d_minor)
    n, m = _segs(d_major), max(12, _segs(d_minor) // 2)
    bm = bmesh.new()
    rings = []
    for i in range(n):
        a = 2 * math.pi * i / n
        ring = []
        for j in range(m):
            b = 2 * math.pi * j / m
            rr = d_major / 2 + d_minor / 2 * math.cos(b)
            ring.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), d_minor / 2 * math.sin(b))))
        rings.append(ring)
    for i in range(n):
        _bridge(bm, rings[i], rings[(i + 1) % n])
    return _finish(bm, name, "Torus", smooth=180)


def prism(n, af, h, name=None):
    """正 n 边形棱柱。af 是「对边距」（扳手开口尺寸），h 高。n=6 就是六角。"""
    _check_pos(af=af, h=h)
    if int(n) < 3:
        raise ValueError("prism 的边数 n 至少是 3")
    n = int(n)
    r = af / 2 / math.cos(math.pi / n)
    pts = [(r * math.cos(2 * math.pi * i / n + math.pi / n), r * math.sin(2 * math.pi * i / n + math.pi / n))
           for i in range(n)]
    return extrude(pts, h, name=name or _auto_name("Prism"))


def extrude(points_xy, h, name=None):
    """把一个平面轮廓沿 Z 拉伸成实体。points_xy = [(x, y), ...] 按顺序围一圈，不要自交。"""
    _check_pos(h=h)
    pts = [(float(p[0]), float(p[1])) for p in points_xy]
    if len(pts) >= 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("extrude 的轮廓至少要 3 个点")
    if abs(_poly_area(pts)) < 1e-9:
        raise ValueError("extrude 的轮廓面积是 0（点共线了）")
    if _poly_area(pts) < 0:
        pts.reverse()
    bm = bmesh.new()
    a = [bm.verts.new((x, y, 0)) for x, y in pts]
    b = [bm.verts.new((x, y, h)) for x, y in pts]
    _cap(bm, a, flip=True)
    _cap(bm, b)
    _bridge(bm, a, b)
    bm.normal_update()          # 凹多边形要先有法线，三角化才不会把凹进去的地方填上
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    return _finish(bm, name, "Extrude")


def revolve(points_rz, name=None, segments=None):
    """车削体：把 (r, z) 轮廓绕 Z 轴转一圈。points_rz = [(半径, 高度), ...] 围成封闭轮廓，r 不能为负。"""
    pts = [(float(p[0]), float(p[1])) for p in points_rz]
    if len(pts) >= 2 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("revolve 的轮廓至少要 3 个点")
    if any(r < -1e-9 for r, _ in pts):
        raise ValueError("revolve 的半径 r 不能是负数")
    n = _segs(2 * max(r for r, _ in pts), segments)
    bm = bmesh.new()
    rings = []
    for r, z in pts:
        if r < 1e-6:
            rings.append(bm.verts.new((0, 0, z)))
        else:
            rings.append(_ring(bm, r, z, n))
    for k in range(len(pts)):
        a, b = rings[k], rings[(k + 1) % len(pts)]
        a_pole, b_pole = not isinstance(a, list), not isinstance(b, list)
        if a_pole and b_pole:
            continue
        for i in range(n):
            j = (i + 1) % n
            if a_pole:
                bm.faces.new((a, b[j], b[i]))
            elif b_pole:
                bm.faces.new((a[i], a[j], b))
            else:
                bm.faces.new((a[i], a[j], b[j], b[i]))
    return _finish(bm, name, "Revolve")


def _fillet_path(points, bend_r, steps=10):
    pts = [_as_vec3(p, "路径点") for p in points]
    if len(pts) < 2:
        raise ValueError("路径至少要 2 个点")
    if bend_r <= 0 or len(pts) == 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        u, v = (p0 - p1), (p2 - p1)
        lu, lv = u.length, v.length
        if lu < 1e-6 or lv < 1e-6:
            continue
        u.normalize()
        v.normalize()
        ang = u.angle(v)
        if ang > math.pi - 1e-3 or ang < 1e-3:
            out.append(p1)
            continue
        t = bend_r / math.tan(ang / 2)
        t = min(t, lu * 0.49, lv * 0.49)
        r = t * math.tan(ang / 2)
        a, b = p1 + u * t, p1 + v * t
        c = p1 + (u + v).normalized() * (r / math.sin(ang / 2))
        va, vb = a - c, b - c
        sweep = va.angle(vb)
        axis = va.cross(vb).normalized()
        for k in range(steps + 1):
            out.append(c + Matrix.Rotation(sweep * k / steps, 3, axis) @ va)
    out.append(pts[-1])
    return out


def _sweep(path, radii, n, closed=False):
    """沿路径扫掠若干同心圆环。radii: [外半径] 或 [外半径, 内半径]。closed=True 时路径首尾相接（皮带）。"""
    bm = bmesh.new()
    tangents = []
    for i in range(len(path)):
        if closed:
            a, b = path[i - 1], path[(i + 1) % len(path)]
        else:
            a = path[max(i - 1, 0)]
            b = path[min(i + 1, len(path) - 1)]
        tangents.append((b - a).normalized())
    t0 = tangents[0]
    ref = Vector((0, 0, 1)) if abs(t0.z) < 0.9 else Vector((1, 0, 0))
    nrm = (ref - t0 * ref.dot(t0)).normalized()
    layers = [[] for _ in radii]
    prev_t = t0
    for p, t in zip(path, tangents):
        q = prev_t.rotation_difference(t)
        nrm = (q @ nrm)
        nrm = (nrm - t * nrm.dot(t)).normalized()
        bn = t.cross(nrm)
        for li, r in enumerate(radii):
            layers[li].append([bm.verts.new(p + (nrm * math.cos(2 * math.pi * k / n) +
                                                 bn * math.sin(2 * math.pi * k / n)) * r) for k in range(n)])
        prev_t = t
    for li, rings in enumerate(layers):
        for i in range(len(rings) - (0 if closed else 1)):
            j = (i + 1) % len(rings)
            if li == 0:
                _bridge(bm, rings[i], rings[j])
            else:
                _bridge(bm, rings[j], rings[i])
    if closed:
        return bm
    if len(radii) == 1:
        _cap(bm, layers[0][0], flip=True)
        _cap(bm, layers[0][-1])
    else:
        _bridge(bm, layers[1][0], layers[0][0])
        _bridge(bm, layers[0][-1], layers[1][-1])
    return bm


def pipe(points, d, d_in=0, bend_r=0, name=None):
    """沿折线走的圆管/圆棒。points = [(x,y,z), ...]；d 外径；d_in 内径（0 就是实心）；bend_r 拐弯处的弯曲半径。
    这是唯一用世界坐标直接给点的基本体，原点在 (0,0,0)。"""
    _check_pos(d=d)
    if d_in < 0 or d_in >= d:
        raise ValueError("pipe 的内径 d_in=%s 必须在 0 和外径 d=%s 之间" % (d_in, d))
    path = _fillet_path(points, bend_r)
    for i in range(len(path) - 1):
        if (path[i + 1] - path[i]).length < 1e-6:
            raise ValueError("pipe 的路径里有两个重合的点")
    radii = [d / 2] + ([d_in / 2] if d_in > 0 else [])
    bm = _sweep(path, radii, _segs(d))
    return _finish(bm, name, "Pipe", smooth=50)


def spring(d_coil, d_wire, pitch, turns, name=None):
    """压缩弹簧。d_coil 中径，d_wire 线径，pitch 节距，turns 圈数。轴线沿 Z，原点在底部中心。"""
    _check_pos(d_coil=d_coil, d_wire=d_wire, pitch=pitch, turns=turns)
    steps = max(8, int(turns * 32))
    path = [Vector((d_coil / 2 * math.cos(2 * math.pi * turns * i / steps),
                    d_coil / 2 * math.sin(2 * math.pi * turns * i / steps),
                    d_wire / 2 + pitch * turns * i / steps)) for i in range(steps + 1)]
    bm = _sweep(path, [d_wire / 2], 12)
    return _finish(bm, name, "Spring", smooth=180)


# ---------------------------------------------------------------- 螺纹和紧固件

_COARSE_PITCH = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5,
                 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0, 30: 3.5}
_HEX_AF = {1.6: 3.2, 2: 4, 2.5: 5, 3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18, 14: 21,
           16: 24, 20: 30, 24: 36, 30: 46}


def _pitch_for(d, pitch):
    if pitch:
        return float(pitch)
    key = min(_COARSE_PITCH, key=lambda k: abs(k - d))
    return _COARSE_PITCH[key] * (d / key)


def _af_for(d, af):
    if af:
        return float(af)
    key = min(_HEX_AF, key=lambda k: abs(k - d))
    return _HEX_AF[key] * (d / key)


def _stack_bm(rings, n, closed=False):
    """把一串「环」连成实体。每个环是 (z, r)：r 是数字，或者 r(θ) 函数。
    相邻环之间连三角面；closed=True 时最后一环接回第一环（做螺母这种环形截面），否则两端封口。"""
    bm = bmesh.new()
    rows = []
    for z, r in rings:
        row = []
        for j in range(n):
            th = 2 * math.pi * j / n
            if isinstance(r, list):          # 这一环自己给出每个点的 (半径, 角度)
                rr, th = r[j]
            else:
                rr = r(th) if callable(r) else r
            row.append(bm.verts.new((rr * math.cos(th), rr * math.sin(th), z)))
        rows.append(row)
    pairs = list(zip(rows[:-1], rows[1:]))
    if closed:
        pairs.append((rows[-1], rows[0]))
    for a, b in pairs:
        for j in range(n):
            k = (j + 1) % n
            bm.faces.new((a[j], a[k], b[k]))
            bm.faces.new((a[j], b[k], b[j]))
    if not closed:
        _cap(bm, rows[0], flip=True)
        _cap(bm, rows[-1])
    return bm


def _thread_r(d, pitch, grow=0.0):
    """螺纹表面半径函数 r(z, θ, fade)。相位：z=0、θ=0 处是牙底。"""
    depth = 0.6134 * pitch
    R = d / 2 + grow

    def f(z, th, fade=1.0):
        fr = (z / pitch - th / (2 * math.pi)) % 1.0
        tri = 1 - abs(2 * fr - 1)
        prof = min(1.0, max(0.0, (tri - 0.125) / 0.75))
        return R - depth * (1 - prof) * fade
    return f, depth, R


def _hex_ring(af, rho, n):
    """六角形被半径 rho 的圆削过之后的一圈点（rho 很大就是纯六角）。θ=0 是一个角。
    每条边上的点按「角 / 圆弧 / 交界 / 平面 / 平面 / 交界 / 圆弧」固定分工，
    这样上下两环连起来，平面上的面严格共面，倒角的边界是准的。"""
    a = af / 2
    rc = a / math.cos(math.radians(30))
    m = n // 6
    if rho >= rc:
        ph = 30.0
    elif rho <= a:
        ph = 0.0
    else:
        ph = math.degrees(math.acos(a / rho))
    a_l = (m - 5) // 2
    a_r = m - 5 - a_l
    local = [-30.0]
    local += [-30.0 + (30.0 - ph) * (k + 1) / (a_l + 1) for k in range(a_l)]
    local += [-ph, -ph / 3, ph / 3, ph]
    local += [ph + (30.0 - ph) * (k + 1) / (a_r + 1) for k in range(a_r)]
    out = []
    for sct in range(6):
        for f in local:
            r = min(a / math.cos(math.radians(f)), rho)
            out.append((r, math.radians(60.0 * sct + 30.0 + f)))
    return out


def _hex_corner_r(af):
    return af / 2 / math.cos(math.radians(30))


def _hex_segs(d):
    return int(max(48, 12 * math.ceil(_segs(d) / 12)))


def _zs(z0, z1, step):
    k = max(1, int(math.ceil((z1 - z0) / step - 1e-9)))
    return [z0 + (z1 - z0) * i / k for i in range(k + 1)]


def _shank_rings(d, length, pitch, thread, thread_len):
    """螺杆的环（z 从杆尖 -length 到 0）。"""
    tr, depth, R = _thread_r(d, pitch)
    rings = []
    if not thread:
        c = min(0.1 * d, length * 0.3)
        return [(-length, R - c), (-length + c, R), (0.0, R)]
    tl = min(length, thread_len) if thread_len else length
    step = max(pitch / 8, tl / 400)
    for zt in _zs(0.0, tl, step):
        e0 = min(1.0, zt / (0.75 * pitch))
        e1 = min(1.0, max(0.0, (tl - zt) / (0.75 * pitch)))
        fade = min(e0, e1)
        fade = fade * fade * (3 - 2 * fade)
        rings.append((zt - length, (lambda th, zt=zt, fade=fade: min(tr(zt, th, fade), R - depth + zt))))
    if tl < length - 1e-6:
        rings.append((0.0, R))
    return rings


def threaded_rod(d, length, pitch=None, name=None):
    """全螺纹的螺杆。d 公称直径（如 8 表示 M8），length 长度，pitch 螺距（不写就用粗牙标准值）。
    原点在底面中心，向 +Z。"""
    _check_pos(d=d, length=length)
    rings = [(z + length, r) for z, r in _shank_rings(d, length, _pitch_for(d, pitch), True, None)]
    return _finish(_stack_bm(rings, _hex_segs(d)), name, "ThreadedRod", smooth=50)


def _bolt(kind, d, length, pitch, head_h, af, thread, thread_len, name):
    _check_pos(d=d, length=length)
    pitch = _pitch_for(d, pitch)
    R = d / 2
    rings = _shank_rings(d, length, pitch, thread, thread_len)
    n = _hex_segs(d)
    big = 1e9
    if kind == "hex":
        af = _af_for(d, af)
        h = head_h or round(0.65 * d, 2)
        rc = _hex_corner_r(af)
        c = min(h * 0.25, (rc - af / 2) * 1.2)
        if af / 2 <= R:
            raise ValueError("hex_bolt 的对边距 af=%s 太小，比杆径 %s 还小" % (af, d))
        rings.append((0.0, _hex_ring(af, af / 2 * 1.03, n)))             # 头部下表面的小台阶
        rings.append((min(0.03 * af, h * 0.15), _hex_ring(af, big, n)))
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            rings.append((h - c + c * t, _hex_ring(af, rc - c * t, n)))
    else:
        hd = af or 1.5 * d
        h = head_h or d
        if hd <= d:
            raise ValueError("socket_screw 的头部直径 head_d=%s 必须大于杆径 %s" % (hd, d))
        bv = min(0.06 * d, 0.5)
        s_af = 0.8 * d if _hex_corner_r(0.8 * d) < hd / 2 - 2 * bv else (hd / 2 - 2 * bv) * 1.6
        depth = h * 0.55
        rings += [(0.0, hd / 2 - bv), (bv, hd / 2), (h - bv, hd / 2), (h, hd / 2 - bv),
                  (h, _hex_ring(s_af, big, n)), (h - depth, _hex_ring(s_af, big, n)),
                  (h - depth - 0.25 * s_af, 0.02 * d)]
    bm = _stack_bm(rings, n)
    obj = _finish(bm, name, "Bolt", smooth=25)
    obj["qb_kind"] = "bolt"
    obj["qb_d"] = float(d)
    obj["qb_pitch"] = float(pitch)
    obj["qb_length"] = float(length)
    return obj


def hex_bolt(d, length, pitch=None, head_h=None, af=None, thread=True, thread_len=None, name=None):
    """六角头螺栓。d 公称直径（8 = M8），length 杆长（不含头）。
    pitch 螺距、head_h 头高、af 对边距不写就用标准值。thread=False 画光杆（零件多时更快）。
    thread_len 螺纹长度（不写就是全螺纹）。原点在头部下表面中心，杆朝 -Z。"""
    return _bolt("hex", d, length, pitch, head_h, af, thread, thread_len, name)


def socket_screw(d, length, pitch=None, head_h=None, head_d=None, thread=True, thread_len=None, name=None):
    """内六角圆柱头螺钉。参数同 hex_bolt，head_d 是头部直径（默认 1.5d）。原点在头部下表面中心，杆朝 -Z。"""
    return _bolt("socket", d, length, pitch, head_h, head_d, thread, thread_len, name)


def nut(d, h=None, af=None, pitch=None, thread=True, name=None):
    """六角螺母。d 公称直径（8 = M8），h 厚度（默认 0.8d），af 对边距。
    thread=True 带内螺纹（和同规格螺栓的螺纹留 0.1 mm 间隙）。原点在底面中心，向 +Z。"""
    _check_pos(d=d)
    h = h or round(0.8 * d, 2)
    af = _af_for(d, af)
    pitch = _pitch_for(d, pitch)
    rc = _hex_corner_r(af)
    if af / 2 <= d / 2 + 0.3:
        raise ValueError("nut 的对边距 af=%s 太小，包不住 M%g 的孔" % (af, d))
    c = min(h * 0.2, (rc - af / 2) * 1.2)
    tr, depth, R = _thread_r(d, pitch, grow=0.1)
    n = _hex_segs(d)
    if thread:
        bore = lambda z: (lambda th, z=z: tr(z, th))
        zs = _zs(0.0, h, max(pitch / 8, h / 200))
    else:
        bore = lambda z: R
        zs = [0.0, h]
    rings = [(c * t, _hex_ring(af, rc - c * (1 - t), n)) for t in (0.0, 0.33, 0.67, 1.0)]
    rings += [(h - c + c * t, _hex_ring(af, rc - c * t, n)) for t in (0.0, 0.33, 0.67, 1.0)]
    rings += [(z, bore(z)) for z in reversed(zs)]
    obj = _finish(_stack_bm(rings, n, closed=True), name, "Nut", smooth=25)
    obj["qb_kind"] = "nut"
    obj["qb_d"] = float(d)
    obj["qb_pitch"] = float(pitch)
    obj["qb_h"] = float(h)
    return obj


def screw_on(nut_obj, bolt_obj, grip):
    """把螺母拧到螺栓上并对好牙。grip 是被夹紧的总厚度（螺栓头下表面到螺母顶面的距离）。
    螺栓朝哪个方向都可以。两者要是同规格（直径和螺距一样）。"""
    for o, kind in ((nut_obj, "nut"), (bolt_obj, "bolt")):
        if o.get("qb_kind") != kind:
            raise ValueError("screw_on(螺母, 螺栓, grip)：第一个要是 nut()，第二个要是 hex_bolt()/socket_screw()")
    if abs(nut_obj["qb_d"] - bolt_obj["qb_d"]) > 1e-6 or abs(nut_obj["qb_pitch"] - bolt_obj["qb_pitch"]) > 1e-6:
        raise ValueError("screw_on：螺母 M%g×%g 和螺栓 M%g×%g 规格不一样" % (
            nut_obj["qb_d"], nut_obj["qb_pitch"], bolt_obj["qb_d"], bolt_obj["qb_pitch"]))
    h, length, pitch = nut_obj["qb_h"], bolt_obj["qb_length"], bolt_obj["qb_pitch"]
    if grip < 0 or grip + h > length + 1e-6:
        raise ValueError("screw_on：夹紧厚度 grip=%g 加螺母厚 %g 超过了螺栓杆长 %g" % (grip, h, length))
    turn = ((length - grip - h) / pitch) % 1.0
    _update()
    nut_obj.matrix_world = (bolt_obj.matrix_world @ Matrix.Translation((0, 0, -(grip + h)))
                            @ Matrix.Rotation(2 * math.pi * turn, 4, "Z"))
    _update()
    return nut_obj


def washer(d_in, d_out, t, name=None):
    """平垫圈。d_in 内径，d_out 外径，t 厚度。原点在底面中心。"""
    return tube(d_out, d_in, t, name=name or _auto_name("Washer"))


# ---------------------------------------------------------------- 齿轮、轴承、法兰、角码

def _gear_profile(m, z, pa_deg, ra, rf, bl):
    """渐开线齿轮的轮廓点。ra 齿顶圆半径，rf 齿根圆半径，bl 齿侧间隙（负数就是把齿加厚）。0 度方向是一个齿的中心。"""
    pa = math.radians(pa_deg)
    r = m * z / 2
    rb = r * math.cos(pa)
    inv = lambda a: math.tan(a) - a
    half0 = math.pi / (2 * z) + inv(pa) - bl / (2 * r)
    flank = []
    k = 8
    r_start = max(rb, rf)
    for i in range(k + 1):
        rho = r_start + (ra - r_start) * i / k
        alpha = math.acos(min(1.0, rb / rho))
        flank.append((rho, max(half0 - inv(alpha), 0.02 * math.pi / z)))
    pts = []
    for t in range(z):
        c = 2 * math.pi * t / z
        gap = math.pi / z
        a_root = flank[0][1]
        if rf < r_start - 1e-6:
            pts.append((rf * math.cos(c - a_root), rf * math.sin(c - a_root)))
        for rho, a in flank:
            pts.append((rho * math.cos(c - a), rho * math.sin(c - a)))
        for rho, a in reversed(flank):
            pts.append((rho * math.cos(c + a), rho * math.sin(c + a)))
        if rf < r_start - 1e-6:
            pts.append((rf * math.cos(c + a_root), rf * math.sin(c + a_root)))
        mid = c + gap
        pts.append((rf * math.cos(mid), rf * math.sin(mid)))
    return pts


def spur_gear(module, teeth, width, bore=0, pressure_angle=20, backlash=None, name=None):
    """直齿圆柱齿轮（渐开线齿形）。module 模数，teeth 齿数，width 齿宽，bore 中心孔直径。
    分度圆直径 = module × teeth；两个齿轮的中心距 = module × (齿数1 + 齿数2) / 2。
    原点在底面中心。0 度方向（+X）是一个齿的中心；要和另一个齿轮啮合，把其中一个转半个齿：rot(g, 0, 0, 180 / 齿数)。
    backlash 是齿侧间隙（毫米，默认 0.04 × 模数），让两个齿轮不会互相扎进去。"""
    _check_pos(module=module, width=width)
    z = int(teeth)
    if z < 6:
        raise ValueError("spur_gear 的齿数 teeth 至少是 6，现在是 %r" % (teeth,))
    m = float(module)
    r = m * z / 2
    rf = max(r - 1.25 * m, 0.2 * r)
    bl = 0.04 * m if backlash is None else float(backlash)
    obj = extrude(_gear_profile(m, z, pressure_angle, r + m, rf, bl), width, name=name or _auto_name("Gear"))
    if bore and bore > 0:
        if bore >= 2 * rf:
            raise ValueError("spur_gear 的中心孔 bore=%s 比齿根圆 %.2f 还大" % (bore, 2 * rf))
        c = cylinder(bore, width + 2, name=_auto_name("_bore"))
        at(c, 0, 0, -1)
        cut(obj, c)
    obj["qb_kind"] = "gear"
    obj["qb_module"] = m
    obj["qb_teeth"] = z
    return obj


def ring_gear(module, teeth, width, d_out, pressure_angle=20, backlash=None, name=None):
    """内齿圈（齿朝里的齿轮，行星减速器的外圈）。module 模数，teeth 齿数，width 齿宽，d_out 外径。
    分度圆直径 = module × teeth。里面的齿轮和它啮合时，中心距 = module × (内齿圈齿数 - 小齿轮齿数) / 2。
    原点在底面中心。0 度方向（+X）是一个齿槽的中心：一个齿轮放在 +X 方向、自己 0 度的齿朝 +X，正好插进这个齿槽。
    行星减速器要求：内齿圈齿数 = 太阳轮齿数 + 2 × 行星轮齿数。"""
    _check_pos(module=module, width=width, d_out=d_out)
    z = int(teeth)
    if z < 12:
        raise ValueError("ring_gear 的齿数 teeth 至少是 12，现在是 %r" % (teeth,))
    m = float(module)
    r = m * z / 2
    if d_out <= 2 * (r + 1.25 * m) + 1:
        raise ValueError("ring_gear 的外径 d_out=%s 太小：齿根圆直径就有 %.1f，外径至少要 %.1f" % (
            d_out, 2 * (r + 1.25 * m), 2 * (r + 1.25 * m) + 2))
    bl = 0.04 * m if backlash is None else float(backlash)
    obj = cylinder(d_out, width, name=name or _auto_name("RingGear"))
    # 刀具是一个「加厚了齿、齿顶更高」的外齿轮：它的齿切出内齿圈的齿槽
    cutter = extrude(_gear_profile(m, z, pressure_angle, r + 1.25 * m, r - m, -bl), width + 2, name=_auto_name("_ringcut"))
    at(cutter, 0, 0, -1)
    cut(obj, cutter)
    obj["qb_kind"] = "ring_gear"
    obj["qb_module"] = m
    obj["qb_teeth"] = z
    return obj


def _extrude_twist(pts, h, twist, name, base):
    """把轮廓沿 Z 拉伸，同时一层一层地转（斜齿轮用）。twist 是从底到顶一共转过的弧度。"""
    if _poly_area(pts) < 0:
        pts = list(reversed(pts))
    steps = max(2, int(math.ceil(abs(twist) / math.radians(4))), int(math.ceil(h / 3.0)))
    bm = bmesh.new()
    rows = []
    for k in range(steps + 1):
        a = twist * k / steps
        ca, sa = math.cos(a), math.sin(a)
        rows.append([bm.verts.new((x * ca - y * sa, x * sa + y * ca, h * k / steps)) for x, y in pts])
    n = len(pts)
    for r0, r1 in zip(rows[:-1], rows[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((r0[i], r0[j], r1[j]))
            bm.faces.new((r0[i], r1[j], r1[i]))
    _cap(bm, rows[0], flip=True)
    _cap(bm, rows[-1])
    bm.normal_update()
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    return _finish(bm, name, base)


def helical_gear(module, teeth, width, helix_angle=15, bore=0, pressure_angle=20, backlash=None, name=None):
    """斜齿圆柱齿轮。module 模数（端面），teeth 齿数，width 齿宽，helix_angle 螺旋角（度），bore 中心孔直径。
    一对啮合的斜齿轮螺旋角大小相等、方向相反：一个写 15，另一个写 -15。中心距和直齿轮一样 = module × (齿数1 + 齿数2) / 2。
    原点在底面中心。对齿用 mesh(g2, g1)。"""
    _check_pos(module=module, width=width)
    z = int(teeth)
    if z < 6:
        raise ValueError("helical_gear 的齿数 teeth 至少是 6，现在是 %r" % (teeth,))
    if abs(helix_angle) > 45:
        raise ValueError("helical_gear 的螺旋角 helix_angle 要在 -45 ~ 45 度之间，现在是 %r" % (helix_angle,))
    m = float(module)
    r = m * z / 2
    rf = max(r - 1.25 * m, 0.2 * r)
    bl = 0.04 * m if backlash is None else float(backlash)
    tau = math.tan(math.radians(helix_angle)) / r              # 每升高 1 mm 转过的弧度
    obj = _extrude_twist(_gear_profile(m, z, pressure_angle, r + m, rf, bl), width, tau * width,
                         name or _auto_name("HelicalGear"), "HelicalGear")
    if bore and bore > 0:
        if bore >= 2 * rf:
            raise ValueError("helical_gear 的中心孔 bore=%s 比齿根圆 %.2f 还大" % (bore, 2 * rf))
        c = cylinder(bore, width + 2, name=_auto_name("_bore"))
        at(c, 0, 0, -1)
        cut(obj, c)
    obj["qb_kind"] = "gear"
    obj["qb_module"] = m
    obj["qb_teeth"] = z
    obj["qb_twist"] = tau
    return obj


def worm(module, length, starts=1, q=10, backlash=None, name=None):
    """蜗杆（右旋）。module 模数，length 长度，starts 头数，q 直径系数（分度圆直径 = q × module，默认 10）。
    轴线沿 Z，原点在底面中心。转一圈，蜗轮转过 starts 个齿。配套的蜗轮用 worm_wheel，用 mesh_worm 摆位置和对齿。"""
    _check_pos(module=module, length=length, q=q)
    st = int(starts)
    if st < 1 or st > 4:
        raise ValueError("worm 的头数 starts 要在 1 ~ 4 之间，现在是 %r" % (starts,))
    m = float(module)
    rp = q * m / 2
    if rp - 1.2 * m < 0.5 * m:
        raise ValueError("worm 的直径系数 q=%s 太小，蜗杆芯部没有了，q 至少取 6" % q)
    px = math.pi * m                       # 轴向齿距
    bl = 0.08 * m if backlash is None else float(backlash)
    half = px / 4 - bl / 2                 # 分度线上的半齿厚
    tan_a = math.tan(math.radians(20))

    def rfun(zz):
        def f(th):
            fr = (zz / px - st * th / (2 * math.pi)) / st
            fr = (fr * st) % 1.0
            u = abs(fr - 0.5) * px
            return min(rp + m, max(rp - 1.2 * m, rp + (half - u) / tan_a))
        return f
    rings = [(zz, rfun(zz)) for zz in _zs(0.0, length, max(px / 16, length / 400))]
    obj = _finish(_stack_bm(rings, _segs(2 * rp + 2 * m)), name, "Worm", smooth=40)
    obj["qb_kind"] = "worm"
    obj["qb_module"] = m
    obj["qb_starts"] = st
    obj["qb_d"] = 2 * rp
    obj["qb_length"] = float(length)
    return obj


def worm_wheel(module, teeth, width, starts=1, q=10, bore=0, name=None):
    """蜗轮，和 worm(module, …, starts, q) 配套（module、starts、q 要写成一样的）。teeth 齿数，width 齿宽，bore 中心孔直径。
    分度圆直径 = module × teeth。中心距 = (q × module + module × teeth) / 2。传动比 = teeth / starts。
    原点在底面中心。用 mesh_worm(wheel, worm) 摆位置和对齿。"""
    m = float(module)
    lead_angle = math.degrees(math.atan(int(starts) / float(q)))
    obj = helical_gear(m, teeth, width, helix_angle=lead_angle, bore=bore, backlash=0.08 * m,
                       name=name or _auto_name("WormWheel"))
    obj["qb_kind"] = "worm_wheel"
    obj["qb_starts"] = int(starts)
    obj["qb_q"] = float(q)
    return obj


def _z_axis(obj):
    _update()
    return (obj.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()


def _spin_z(obj):
    """物体绕世界 Z 转过的角度（弧度）。只对轴线竖直的物体有意义。"""
    _update()
    x = obj.matrix_world.to_3x3() @ Vector((1, 0, 0))
    return math.atan2(x.y, x.x)


def mesh(g, ref, angle=0):
    """把齿轮 g 放到齿轮 ref 旁边并把齿对好。两个齿轮的轴线都要竖直（沿 Z），模数要一样。
    angle 是 g 在 ref 的哪个方向（度，0 是 +X，90 是 +Y）。g 的高度（z）不变。
    - 两个外齿轮：g 放到中心距 = module × (齿数和) / 2 的位置。
    - ref 是内齿圈：g 放在齿圈里面，中心距 = module × (齿数差) / 2。
    - g 是内齿圈：不挪位置，只转它，让它和已经摆好的 ref 对上齿（ref 要已经在正确的中心距上）。
    斜齿轮也可以（两个的螺旋角要相反）。先 mesh 再整体搬动；搬动以后不要再单独转其中一个。"""
    for o in (g, ref):
        if o.get("qb_kind") not in ("gear", "ring_gear"):
            raise ValueError("mesh(g, ref)：两个都要是 spur_gear / helical_gear / ring_gear 做出来的，%s 不是" % o.name)
        if abs(_z_axis(o).z) < 0.9999:
            raise ValueError("mesh：%s 的轴线不是竖直的。先在轴线竖直的时候 mesh，对好以后再整体转" % o.name)
    kg, kr = g["qb_kind"], ref["qb_kind"]
    if kg == kr == "ring_gear":
        raise ValueError("mesh：两个内齿圈不能互相啮合")
    m = g["qb_module"]
    if abs(m - ref["qb_module"]) > 1e-6:
        raise ValueError("mesh：%s 的模数 %g 和 %s 的模数 %g 不一样，啮合不上" % (g.name, m, ref.name, ref["qb_module"]))
    zg, zr = g["qb_teeth"], ref["qb_teeth"]
    tg, tr = g.get("qb_twist", 0.0), ref.get("qb_twist", 0.0)
    pr = ref.matrix_world.translation.copy()
    pg = g.matrix_world.translation.copy()
    al = math.radians(angle)
    phi_r = _spin_z(ref)

    def set_spin(obj, phi):
        obj.rotation_euler = Euler((0, 0, phi), "XYZ")
        _update()

    if kg == "gear" and kr == "gear":
        if abs(tg * zg + tr * zr) > 1e-6:
            raise ValueError("mesh：一对斜齿轮的螺旋角要大小相等、方向相反（一个 15，另一个 -15）；直齿轮只能配直齿轮")
        a = m * (zg + zr) / 2
        g.location = (pr.x + a * math.cos(al), pr.y + a * math.sin(al), pg.z)
        # 在 ref 底面的高度上对齿：ref 的齿对着 g 的齿槽
        k = (zr / (2 * math.pi)) * (phi_r - al) + 0.5
        phi_g0 = al + math.pi - (2 * math.pi / zg) * k          # g 在 z = ref 底面处应有的齿相位
        set_spin(g, phi_g0 - tg * (pr.z - pg.z))
    elif kr == "ring_gear":
        if abs(tg) > 1e-9:
            raise ValueError("mesh：内齿圈是直齿的，里面只能配直齿轮")
        if zg >= zr:
            raise ValueError("mesh：里面的齿轮齿数 %d 要比内齿圈的齿数 %d 少" % (zg, zr))
        a = m * (zr - zg) / 2
        g.location = (pr.x + a * math.cos(al), pr.y + a * math.sin(al), pg.z)
        set_spin(g, al + (zr / zg) * (phi_r - al))
    else:                                   # g 是内齿圈，ref 是里面的齿轮
        if abs(tr) > 1e-9:
            raise ValueError("mesh：内齿圈是直齿的，里面只能配直齿轮")
        a = m * (zg - zr) / 2
        d = Vector((pr.x - pg.x, pr.y - pg.y))
        if abs(d.length - a) > 0.05:
            raise ValueError("mesh：%s 的中心离内齿圈 %s 的中心 %.2f mm，应该正好是 %g（= 模数 × 齿数差 / 2）。"
                             "先把里面的齿轮摆到正确的中心距上" % (ref.name, g.name, d.length, a))
        al2 = math.atan2(d.y, d.x)
        set_spin(g, al2 + (zr / zg) * (phi_r - al2))
    _update()
    return g


def mesh_worm(wheel, worm_obj, side="+y"):
    """把蜗轮摆到蜗杆旁边并对好齿。要求：蜗杆已经放平，轴线沿 X（rot(worm, 0, 90, 0) 之后）；蜗轮轴线竖直。
    side 是蜗轮在蜗杆的哪一侧：'+y' 或 '-y'。蜗轮的齿宽中面会对准蜗杆轴线的高度。蜗杆的位置不动。"""
    if wheel.get("qb_kind") != "worm_wheel" or worm_obj.get("qb_kind") != "worm":
        raise ValueError("mesh_worm(蜗轮, 蜗杆)：第一个要是 worm_wheel() 做的，第二个要是 worm() 做的")
    if abs(wheel["qb_module"] - worm_obj["qb_module"]) > 1e-6 or wheel["qb_starts"] != worm_obj["qb_starts"]:
        raise ValueError("mesh_worm：蜗轮和蜗杆的 module、starts 要一样")
    if abs(wheel.get("qb_q", 0) * wheel["qb_module"] - worm_obj["qb_d"]) > 1e-6:
        raise ValueError("mesh_worm：蜗轮和蜗杆的 q 要一样")
    ax = _z_axis(worm_obj)
    if abs(abs(ax.x) - 1) > 1e-4:
        raise ValueError("mesh_worm：蜗杆的轴线要沿 X。先 rot(蜗杆, 0, 90, 0) 把它放平")
    if abs(_z_axis(wheel).z) < 0.9999:
        raise ValueError("mesh_worm：蜗轮的轴线要竖直（沿 Z）")
    sg = side.strip().lower()
    if sg not in ("+y", "-y"):
        raise ValueError("mesh_worm 的 side 要写 '+y' 或 '-y'，现在是 %r" % side)
    sgn = 1 if sg == "+y" else -1
    m, zt = wheel["qb_module"], wheel["qb_teeth"]
    a = (worm_obj["qb_d"] + m * zt) / 2
    wb = bbox(worm_obj)
    wheel_w = bbox(wheel)["size"][2]
    cx, cy, cz = wb["center"]
    wheel.location = (cx, cy + sgn * a, cz - wheel_w / 2)
    _update()
    # 对齿：在一个齿距里试着转蜗轮，取扎进去最少的角度（蜗杆的螺旋面没有简单的解析相位）
    from runner import Geo, pair_relation
    gw = Geo(worm_obj)
    pitch = 2 * math.pi / zt
    base = _spin_z(wheel)

    def depth(phi):
        wheel.rotation_euler = Euler((0, 0, phi), "XYZ")
        _update()
        return pair_relation(Geo(wheel), gw)[1]
    best = min(((depth(base + pitch * k / 12), base + pitch * k / 12) for k in range(12)), key=lambda t: t[0])
    for step in (pitch / 36, pitch / 108):
        cand = [(depth(best[1] + s), best[1] + s) for s in (-step, step)]
        best = min(cand + [best], key=lambda t: t[0])
    wheel.rotation_euler = Euler((0, 0, best[1]), "XYZ")
    _update()
    if best[0] > 0.05:
        raise ValueError("mesh_worm：怎么转都还扎进去 %.2f mm，蜗轮和蜗杆的参数配不上" % best[0])
    return wheel


def pulley(d, width, bore=0, belt_d=6, name=None):
    """圆皮带轮。d 是皮带中心线所在的直径（算传动比用它），width 轮宽，bore 中心孔直径，belt_d 皮带的直径。
    传动比 = 大轮 d / 小轮 d。轮缘上有一圈放皮带的圆弧槽。原点在底面中心，轴线沿 Z；皮带的中心线在高度 width / 2。"""
    _check_pos(d=d, width=width, belt_d=belt_d)
    if width < belt_d * 1.4:
        raise ValueError("pulley 的轮宽 width=%s 太窄，至少要是皮带直径 belt_d=%s 的 1.4 倍" % (width, belt_d))
    rb = belt_d / 2
    rg = rb * 1.12                                   # 槽的圆弧比皮带略大，皮带只贴槽底
    ro = d / 2 + rb * 0.5                            # 轮缘外圆
    rc = d / 2 + (rg - rb)                           # 槽圆弧的圆心半径（槽底正好在 d/2 - rb）
    if d / 2 - rb <= max(bore / 2, 0) + 1:
        raise ValueError("pulley 的 d=%s 太小，放不下 belt_d=%s 的槽和 bore=%s 的孔" % (d, belt_d, bore))
    half = math.sqrt(max(rg * rg - (ro - rc) ** 2, 0.0))
    arc = []
    for i in range(13):
        t = -half + 2 * half * i / 12
        arc.append((rc - math.sqrt(max(rg * rg - t * t, 0.0)), width / 2 + t))
    rin = bore / 2 if bore and bore > 0 else 0.0
    prof = [(rin, 0), (ro, 0)] + arc + [(ro, width), (rin, width)]
    obj = revolve(prof, name=name or _auto_name("Pulley"))
    obj["qb_kind"] = "pulley"
    obj["qb_d"] = float(d)
    obj["qb_belt"] = float(belt_d)
    return obj


def belt(p1, p2, name=None):
    """绕在两个皮带轮上的圆皮带（开口传动）。p1、p2 是两个已经摆好位置的 pulley()，轴线都要竖直、槽在同一高度。
    皮带的粗细和位置都从皮带轮上读，不用自己算。"""
    for o in (p1, p2):
        if o.get("qb_kind") != "pulley":
            raise ValueError("belt(p1, p2)：两个都要是 pulley() 做出来的，%s 不是" % o.name)
        if abs(_z_axis(o).z) < 0.9999:
            raise ValueError("belt：皮带轮 %s 的轴线要竖直（沿 Z）。先装好皮带，再把整套一起转" % o.name)
    if abs(p1["qb_belt"] - p2["qb_belt"]) > 1e-6:
        raise ValueError("belt：两个皮带轮的 belt_d 不一样（%g 和 %g）" % (p1["qb_belt"], p2["qb_belt"]))
    b1, b2 = bbox(p1), bbox(p2)
    zc1, zc2 = b1["center"][2], b2["center"][2]
    if abs(zc1 - zc2) > 0.05:
        raise ValueError("belt：两个皮带轮的槽不在同一高度（%.2f 和 %.2f），皮带会歪。把它们的 z 对齐" % (zc1, zc2))
    c1 = Vector((b1["center"][0], b1["center"][1]))
    c2 = Vector((b2["center"][0], b2["center"][1]))
    r1, r2 = p1["qb_d"] / 2, p2["qb_d"] / 2
    dist = (c2 - c1).length
    if dist <= r1 + r2 + p1["qb_belt"]:
        raise ValueError("belt：两个皮带轮离得太近（中心距 %.1f），至少要大于 %.1f" % (dist, r1 + r2 + p1["qb_belt"]))
    base = math.atan2((c2 - c1).y, (c2 - c1).x)
    beta = math.asin((r1 - r2) / dist)               # 外公切线和连心线的夹角
    pts = []
    a0, a1 = base + math.pi / 2 - beta, base + 3 * math.pi / 2 + beta       # 轮 1 上的包角（背对轮 2 的一侧）
    n1 = max(8, int((a1 - a0) / math.radians(3)))
    for i in range(n1 + 1):
        t = a0 + (a1 - a0) * i / n1
        pts.append(Vector((c1.x + r1 * math.cos(t), c1.y + r1 * math.sin(t), zc1)))
    b0, b1a = base - math.pi / 2 + beta, base + math.pi / 2 - beta          # 轮 2 上的包角
    n2 = max(8, int((b1a - b0) / math.radians(3)))
    for i in range(n2 + 1):
        t = b0 + (b1a - b0) * i / n2
        pts.append(Vector((c2.x + r2 * math.cos(t), c2.y + r2 * math.sin(t), zc1)))
    clean = [pts[0]]
    for q in pts[1:]:
        if (q - clean[-1]).length > 1e-4:
            clean.append(q)
    if (clean[0] - clean[-1]).length < 1e-4:
        clean.pop()
    bm = _sweep(clean, [p1["qb_belt"] / 2], 16, closed=True)
    obj = _finish(bm, name, "Belt", smooth=180)
    obj["qb_kind"] = "belt"
    return obj


def bent_plate(points, width, t, bend_r=None, name=None):
    """钣金折弯件。points = [(x, z), ...] 是从侧面看板厚中心线走的折线；width 是板宽（沿 Y，居中）；t 板厚；
    bend_r 折弯内圆角半径（默认等于板厚）。例：bent_plate([(0, 0), (40, 0), (40, 30)], 20, 2) 是一个 L 形支架。
    原点在世界原点（points 里的坐标就是世界坐标的 x 和 z）。"""
    _check_pos(width=width, t=t)
    r_in = t if bend_r is None else float(bend_r)
    if r_in < 0:
        raise ValueError("bent_plate 的 bend_r 不能是负数")
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 2:
        raise ValueError("bent_plate 的 points 至少要 2 个点")
    for i in range(len(pts) - 1):
        if math.dist(pts[i], pts[i + 1]) < 2 * (r_in + t) and len(pts) > 2:
            raise ValueError("bent_plate：第 %d 段只有 %.1f 长，放不下两头的折弯（至少要 %.1f）。把这一段加长，或者把 bend_r 改小"
                             % (i + 1, math.dist(pts[i], pts[i + 1]), 2 * (r_in + t)))
    path = _fillet_path([(x, 0, z) for x, z in pts], r_in + t / 2, steps=8)
    left, right = [], []
    for i, p in enumerate(path):
        a = path[max(i - 1, 0)]
        b = path[min(i + 1, len(path) - 1)]
        tg = (b - a).normalized()
        nrm = Vector((-tg.z, 0, tg.x))
        left.append((p.x + nrm.x * t / 2, p.z + nrm.z * t / 2))
        right.append((p.x - nrm.x * t / 2, p.z - nrm.z * t / 2))
    obj = extrude(left + list(reversed(right)), width, name=name or _auto_name("BentPlate"))
    obj.data.transform(Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Translation((0, 0, -width / 2)))
    obj.data.update()
    _smooth(obj.data)
    _update()
    return obj


def link_bar(p1, p2, width, t, hole_d=0, axis="y", name=None):
    """连杆：两头是半圆的扁杆，两头各一个销孔。p1、p2 是两个销孔中心的世界坐标 (x, y, z)；width 杆宽；t 杆厚；
    hole_d 销孔直径（0 就不打孔）；axis 是销子的方向，也就是机构转动的轴（默认 'y'：机构在 XZ 平面里动）。
    物体的原点在 p1，所以绕原点转就是绕第一个销孔转。"""
    _check_pos(width=width, t=t)
    a, b = _as_vec3(p1, "p1"), _as_vec3(p2, "p2")
    ax = _axis(axis)
    d = b - a
    d = d - ax * d.dot(ax)                    # 只看垂直于销子方向的分量
    length = d.length
    if length < 1e-6:
        raise ValueError("link_bar 的两个销孔 p1、p2 重合了（或者只在销子方向上有差别）")
    if hole_d and hole_d >= width:
        raise ValueError("link_bar 的销孔 hole_d=%s 要比杆宽 width=%s 小" % (hole_d, width))
    r = width / 2
    pts = []
    for i in range(17):
        an = math.radians(-90 + 180 * i / 16)
        pts.append((length + r * math.cos(an), r * math.sin(an)))
    for i in range(17):
        an = math.radians(90 + 180 * i / 16)
        pts.append((r * math.cos(an), r * math.sin(an)))
    obj = extrude(pts, t, name=name or _auto_name("LinkBar"))
    obj.data.transform(Matrix.Translation((0, 0, -t / 2)))
    obj.data.update()
    if hole_d and hole_d > 0:
        for x in (0.0, length):
            c = cylinder(hole_d, t + 2, name=_auto_name("_pin"))
            at(c, x, 0, -t / 2 - 1)
            cut(obj, c)
    xh = d.normalized()
    yh = ax.cross(xh).normalized()
    rot_m = Matrix((xh, yh, ax)).transposed().to_4x4()
    obj.matrix_world = Matrix.Translation(a) @ rot_m
    _update()
    obj["qb_kind"] = "link"
    return obj


def bearing(d_in, d_out, width, balls=None, name=None):
    """深沟球轴承（示意）。d_in 内径，d_out 外径，width 宽度。原点在底面中心。"""
    _check_pos(d_in=d_in, d_out=d_out, width=width)
    if d_in >= d_out:
        raise ValueError("bearing 的内径必须小于外径")
    ri, ro, w = d_in / 2, d_out / 2, float(width)
    th = (ro - ri)
    rm = (ri + ro) / 2
    rball = min(th * 0.3, w * 0.32)
    R = rball * 1.04                       # 沟道圆弧半径，比钢球大一点
    land = rball * 0.55                    # 挡边到球心的径向距离
    half = math.sqrt(R * R - land * land)  # 沟道在轴向的半宽
    arc = [(-half + 2 * half * i / 10) for i in range(11)]
    inner = revolve([(ri, 0), (rm - land, 0)] +
                    [(rm - math.sqrt(max(R * R - t * t, 0)), w / 2 + t) for t in arc] +
                    [(rm - land, w), (ri, w)], name=_auto_name("_inner"))
    outer = revolve([(ro, w), (rm + land, w)] +
                    [(rm + math.sqrt(max(R * R - t * t, 0)), w / 2 + t) for t in reversed(arc)] +
                    [(rm + land, 0), (ro, 0)], name=_auto_name("_outer"))
    n = balls or max(6, int(2 * math.pi * rm / (2.6 * rball)))
    objs = [inner, outer]
    for i in range(n):
        s = sphere(2 * rball, name=_auto_name("_ball"), segments=16)
        a = 2 * math.pi * i / n
        at(s, rm * math.cos(a), rm * math.sin(a), w / 2)
        objs.append(s)
    obj = join(objs, name=name or _auto_name("Bearing"))
    obj["qb_kind"] = "bearing"
    return obj


def flange(d_out, d_in, t, bolt_circle_d, n_holes, hole_d, name=None):
    """法兰盘。d_out 外径，d_in 中心孔直径，t 厚度，bolt_circle_d 螺栓孔分布圆直径，n_holes 孔数，hole_d 孔径。"""
    _check_pos(d_out=d_out, t=t)
    obj = tube(d_out, d_in, t, name=name or _auto_name("Flange")) if d_in > 0 else \
        cylinder(d_out, t, name=name or _auto_name("Flange"))
    if n_holes and hole_d:
        if bolt_circle_d + hole_d >= d_out or bolt_circle_d - hole_d <= d_in:
            raise ValueError("flange 的螺栓孔分布圆 %s 放不下：要在内径 %s 和外径 %s 之间" % (bolt_circle_d, d_in, d_out))
        holes_circle(obj, hole_d, bolt_circle_d, n_holes)
    return obj


def l_bracket(width, a, b, t, name=None):
    """L 形角码。width 宽（沿 Y），a 底边长（沿 X），b 竖边高（沿 Z），t 板厚。
    原点在底面、竖板外侧那条棱的中点：底板朝 +X，竖板在 x=0~t。"""
    _check_pos(width=width, a=a, b=b, t=t)
    if t >= a or t >= b:
        raise ValueError("l_bracket 的板厚 t 必须小于 a 和 b")
    obj = extrude([(0, 0), (a, 0), (a, t), (t, t), (t, b), (0, b)], width, name=name or _auto_name("LBracket"))
    # 轮廓画在 XY 面、沿 Z 拉伸；转成 轮廓在 XZ 面、沿 Y 拉伸
    obj.data.transform(Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Translation((0, 0, -width / 2)))
    obj.data.update()
    _smooth(obj.data)
    _update()
    return obj


# ---------------------------------------------------------------- 加工

def union(a, *others):
    """把 others 并到 a 上（others 会被删掉），返回 a。"""
    for b in others:
        _boolean(a, b, "UNION")
        delete(b)
    return a


def _volume(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    v = abs(bm.calc_volume(signed=True))
    bm.free()
    return v


def cut(a, *cutters, keep=False):
    """从 a 上减掉 cutters（刀具默认用完删掉；keep=True 保留），返回 a。刀具没碰到 a 会报错。"""
    for b in cutters:
        v0 = _volume(a)
        _boolean(a, b, "DIFFERENCE")
        if v0 - _volume(a) < 1e-6 * max(v0, 1.0):
            bb, cb = bbox(a), bbox(b)
            raise ValueError("这一刀什么都没切到：%s（范围 x %g~%g  y %g~%g  z %g~%g）和刀具（范围 x %g~%g  y %g~%g  z %g~%g）没有重叠。"
                             "检查刀具的位置和方向" % (a.name, bb["min"][0], bb["max"][0], bb["min"][1], bb["max"][1],
                                              bb["min"][2], bb["max"][2], cb["min"][0], cb["max"][0], cb["min"][1],
                                              cb["max"][1], cb["min"][2], cb["max"][2]))
        if not keep:
            delete(b)
    return a


def intersect(a, b, keep=False):
    """只保留 a 和 b 重叠的部分，返回 a。"""
    _boolean(a, b, "INTERSECT")
    if not keep:
        delete(b)
    return a


_DRILL_TWIST = Matrix.Rotation(0.3137, 4, "Z")   # 钻头转一个小角度，避免它的棱和工件的棱正好对齐


def hole(obj, d, pos=(0, 0, 0), axis="z", depth=None):
    """在 obj 上打一个圆孔。d 孔径；pos 是孔口中心的世界坐标 (x, y, z)，要落在零件的表面上；
    axis 是孔的方向：'z' 竖着打，'x'、'y' 横着打（带不带正负号都行，往哪边有材料就往哪边钻）。
    depth 是孔深，不写就打通。没钻到零件会报错。"""
    _check_pos(d=d)
    p = _as_vec3(pos, "pos")
    ax = _axis(axis)
    bb = bbox(obj)
    span = Vector(bb["size"]).length + 2
    if depth is None:
        c = cylinder(d, 2 * span, name=_auto_name("_drill"))
        c.matrix_world = Matrix.Translation(p - ax * span) @ _align_z_to(ax) @ _DRILL_TWIST
        _update()
        cut(obj, c)
        return obj
    _check_pos(depth=depth)
    want = math.pi * (d / 2) ** 2 * depth
    v0 = _volume(obj)
    keep = obj.data.copy()
    got_best = 0.0
    for direction in (ax, -ax):                     # 先按写的方向（孔口朝 axis，往反方向钻），不行就反过来
        c = cylinder(d, depth + 1, name=_auto_name("_drill"))
        c.matrix_world = Matrix.Translation(p - direction * depth) @ _align_z_to(direction) @ _DRILL_TWIST
        _update()
        try:
            cut(obj, c)
            got = v0 - _volume(obj)
        except ValueError:
            got = 0.0
        if got >= 0.3 * want:
            bpy.data.meshes.remove(keep)
            return obj
        got_best = max(got_best, got)
        old = obj.data                              # 这个方向没钻到：恢复原样，换个方向再试
        obj.data = keep.copy()
        if old.users == 0:
            bpy.data.meshes.remove(old)
        _update()
    bpy.data.meshes.remove(keep)
    k = max(range(3), key=lambda i: abs(ax[i]))
    raise ValueError(
        "这个孔基本没钻到材料（两个方向都试了，最多只去掉应有体积的 %d%%）。孔口在 pos=(%g, %g, %g)，沿 %s 方向钻 %g 深；"
        "而 %s 的范围是 x %g~%g  y %g~%g  z %g~%g。pos 要落在零件的表面上，孔才钻得进去" % (
            round(100 * got_best / want), p.x, p.y, p.z, "xyz"[k].upper(), depth, obj.name,
            bb["min"][0], bb["max"][0], bb["min"][1], bb["max"][1], bb["min"][2], bb["max"][2]))


def holes_circle(obj, d, circle_d, n, center=(0, 0), axis="z", start_angle=0, depth=None):
    """沿一个圆均布打 n 个孔（法兰螺栓孔那种）。d 孔径，circle_d 分布圆直径，center 圆心。
    只支持 axis='z'（从上往下钻）。"""
    if int(n) < 1:
        raise ValueError("holes_circle 的孔数 n 至少是 1")
    bb = bbox(obj)
    for i in range(int(n)):
        a = math.radians(start_angle) + 2 * math.pi * i / int(n)
        hole(obj, d, (center[0] + circle_d / 2 * math.cos(a), center[1] + circle_d / 2 * math.sin(a), bb["max"][2]),
             axis=axis, depth=depth)
    return obj


def bevel(obj, r, segments=3, angle=30):
    """给所有尖锐的棱倒圆角。r 圆角大小，segments 段数，angle 多少度以上的棱才算尖。"""
    _check_pos(r=r)
    m = obj.modifiers.new("qb_bevel", "BEVEL")
    m.width = r
    m.segments = max(1, int(segments))
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(angle)
    _apply_modifier(obj, m)
    _smooth(obj.data)
    return obj


def chamfer(obj, w, angle=30):
    """给所有尖锐的棱倒斜角，w 是斜角宽度。"""
    return bevel(obj, w, segments=1, angle=angle)


# ---------------------------------------------------------------- 摆放

def at(obj, x, y, z):
    """把物体的原点放到世界坐标 (x, y, z)。"""
    obj.location = _as_vec3((x, y, z), "位置")
    _update()
    return obj


def move(obj, dx=0, dy=0, dz=0):
    """在现在的位置上再平移 (dx, dy, dz)。"""
    obj.location = obj.location + _as_vec3((dx, dy, dz), "位移")
    _update()
    return obj


def rot(obj, rx=0, ry=0, rz=0):
    """绕物体自己的原点转，角度是度，轴是世界坐标的 X/Y/Z（先 X 再 Y 再 Z）。"""
    r = Euler((math.radians(rx), math.radians(ry), math.radians(rz)), "XYZ").to_matrix()
    obj.rotation_euler = (r @ obj.rotation_euler.to_matrix()).to_euler("XYZ")
    _update()
    return obj


def rot_about(obj, axis, angle, pivot=(0, 0, 0)):
    """绕过 pivot 点、方向为 axis 的轴线转 angle 度（位置和朝向一起变）。"""
    p = _as_vec3(pivot, "pivot")
    r = Matrix.Rotation(math.radians(angle), 4, _axis(axis))
    _update()
    obj.matrix_world = Matrix.Translation(p) @ r @ Matrix.Translation(-p) @ obj.matrix_world
    _update()
    return obj


def bbox(obj):
    """物体的世界坐标包围盒：{'min':(x,y,z), 'max':(x,y,z), 'size':(sx,sy,sz), 'center':(x,y,z)}。"""
    _update()
    mw = obj.matrix_world
    if len(obj.data.vertices) == 0:
        raise ValueError("%s 没有顶点" % obj.name)
    import numpy as np
    co = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    m = np.array(mw)
    w = co @ m[:3, :3].T + m[:3, 3]
    lo, hi = w.min(axis=0), w.max(axis=0)
    r = lambda v: tuple(round(float(c), 4) for c in v)
    return {"min": r(lo), "max": r(hi), "size": r(hi - lo), "center": r((lo + hi) / 2)}


def stack(obj, on, gap=0):
    """把 obj 叠到 on 的正上方：XY 中心对齐，obj 的底贴着 on 的顶（gap 是留的缝）。"""
    a, b = bbox(obj), bbox(on)
    return move(obj, b["center"][0] - a["center"][0], b["center"][1] - a["center"][1],
                b["max"][2] + gap - a["min"][2])


def beside(obj, ref, side="+x", gap=0):
    """把 obj 贴到 ref 的某一侧：side 是 '+x' '-x' '+y' '-y' '+z' '-z'，另外两个方向中心对齐。"""
    s = side.lower().strip()
    if s not in ("+x", "-x", "+y", "-y", "+z", "-z"):
        raise ValueError("beside 的 side 要写 '+x' '-x' '+y' '-y' '+z' '-z'，现在是 %r" % side)
    i = "xyz".index(s[1])
    a, b = bbox(obj), bbox(ref)
    d = [b["center"][k] - a["center"][k] for k in range(3)]
    d[i] = (b["max"][i] + gap - a["min"][i]) if s[0] == "+" else (b["min"][i] - gap - a["max"][i])
    return move(obj, *d)


def center_on(obj, ref, axes="xy"):
    """让 obj 的包围盒中心和 ref 在指定的轴上对齐，axes 如 'xy' 'z' 'xyz'。"""
    a, b = bbox(obj), bbox(ref)
    d = [0, 0, 0]
    for ch in axes.lower():
        if ch in "xyz":
            k = "xyz".index(ch)
            d[k] = b["center"][k] - a["center"][k]
    return move(obj, *d)


def copy(obj, name=None):
    """复制一个物体（网格也复制，互不影响）。"""
    o = obj.copy()
    o.data = obj.data.copy()
    o.name = o.data.name = name or _auto_name(obj.name.split(".")[0].rstrip("0123456789_") or "Copy")
    bpy.context.scene.collection.objects.link(o)
    _update()
    return o


def mirror_copy(obj, axis="x", name=None):
    """复制一份并关于过世界原点的平面做镜像。axis='x' 表示关于 YZ 平面（左右镜像）。"""
    o = copy(obj, name)
    k = "xyz".index(axis.lower().strip("+-"))
    s = [1, 1, 1]
    s[k] = -1
    _update()
    mw = Matrix.Diagonal((s[0], s[1], s[2], 1)) @ obj.matrix_world
    o.data.transform(mw)
    o.matrix_world = Matrix.Identity(4)
    o.data.flip_normals()
    o.data.update()
    _smooth(o.data)
    _update()
    return o


def array_circular(obj, n, axis="z", center=(0, 0, 0)):
    """绕过 center 的轴线圆周阵列，一共 n 个（含原件），返回列表。"""
    out = [obj]
    for i in range(1, int(n)):
        o = copy(obj)
        rot_about(o, axis, 360.0 * i / int(n), center)
        out.append(o)
    return out


def array_linear(obj, n, dx=0, dy=0, dz=0):
    """直线阵列，一共 n 个（含原件），相邻间隔 (dx, dy, dz)，返回列表。"""
    out = [obj]
    for i in range(1, int(n)):
        o = copy(obj)
        move(o, dx * i, dy * i, dz * i)
        out.append(o)
    return out


def join(objs, name=None):
    """把几个物体合成一个零件（只是放在一起，不做布尔）。原点用第一个物体的。"""
    objs = [o for o in objs if o is not None]
    if not objs:
        raise ValueError("join 的列表是空的")
    _update()
    base = objs[0]
    inv = base.matrix_world.inverted()
    bm = bmesh.new()
    mats = []
    for o in objs:
        tmp = o.data.copy()
        tmp.transform(inv @ o.matrix_world)
        if (inv @ o.matrix_world).determinant() < 0:
            tmp.flip_normals()
        remap = []
        for mt in tmp.materials:
            if mt not in mats:
                mats.append(mt)
            remap.append(mats.index(mt))
        start = len(bm.faces)
        bm.from_mesh(tmp)
        bm.faces.ensure_lookup_table()
        for f in bm.faces[start:]:
            f.material_index = remap[f.material_index] if f.material_index < len(remap) else 0
        bpy.data.meshes.remove(tmp)
    mesh = bpy.data.meshes.new(name or _auto_name("Joined"))
    bm.to_mesh(mesh)
    bm.free()
    for mt in mats:
        mesh.materials.append(mt)
    _smooth(mesh)
    props = {k: base[k] for k in base.keys() if k.startswith("qb_")}
    old = base.data
    base.data = mesh
    base.name = mesh.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    for k, v in props.items():
        base[k] = v
    for o in objs[1:]:
        delete(o)
    _update()
    return base


def delete(obj):
    """删除物体。"""
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


# ---------------------------------------------------------------- 材质和零件信息

MATERIALS = {
    # 名称: (颜色, 金属度, 粗糙度)
    "steel": ("#8d9197", 1.0, 0.35), "dark_steel": ("#3b3e44", 1.0, 0.45), "stainless": ("#c9ccd1", 1.0, 0.22),
    "aluminum": ("#c8cbd0", 1.0, 0.4), "brass": ("#c9a03c", 1.0, 0.3), "copper": ("#c0683a", 1.0, 0.3),
    "gold": ("#e2b44a", 1.0, 0.25), "zinc": ("#a8b0b8", 1.0, 0.5), "cast_iron": ("#4a4d52", 0.8, 0.7),
    "black_plastic": ("#1c1d20", 0.0, 0.5), "white_plastic": ("#eceae4", 0.0, 0.5),
    "gray_plastic": ("#8a8d92", 0.0, 0.55), "rubber": ("#151515", 0.0, 0.9),
    "red": ("#c8362e", 0.0, 0.45), "orange": ("#e07b25", 0.0, 0.45), "yellow": ("#e3b81f", 0.0, 0.45),
    "green": ("#3f9a52", 0.0, 0.45), "blue": ("#2f6fc4", 0.0, 0.45), "purple": ("#7a4fb5", 0.0, 0.45),
    "pcb": ("#1f6b3a", 0.0, 0.6), "wood": ("#a9793f", 0.0, 0.7), "glass": ("#bfe3ee", 0.0, 0.05),
    "pfa": ("#e9eef0", 0.0, 0.35), "ceramic": ("#f1efe9", 0.0, 0.3),
}


def _hex_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError("颜色要写成 '#rrggbb'，现在是 %r" % h)
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]


def _material(key, rgb_hex, metal, rough, alpha=1.0):
    name = "QB_" + key
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    r, g, b = _hex_rgb(rgb_hex)
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
        if alpha < 1 and "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
    m.diffuse_color = (r, g, b, alpha)
    m.metallic = metal
    m.roughness = rough
    if alpha < 1 and hasattr(m, "blend_method"):
        try:
            m.blend_method = "BLEND"
        except Exception:
            pass
    return m


def _set_mat(obj, m):
    obj.data.materials.clear()
    obj.data.materials.append(m)
    for p in obj.data.polygons:
        p.material_index = 0
    return obj


def mat(obj, preset):
    """给整个零件上预设材质。preset 见 MATERIALS：steel、aluminum、brass、copper、black_plastic、rubber、red、blue、glass……"""
    if preset not in MATERIALS:
        raise ValueError("没有材质 %r。可用的：%s" % (preset, "、".join(MATERIALS)))
    c, me, ro = MATERIALS[preset]
    return _set_mat(obj, _material(preset, c, me, ro, 0.35 if preset == "glass" else 1.0))


def color(obj, rgb_hex, metal=0.0, rough=0.5, alpha=1.0):
    """给整个零件上自定义颜色，如 color(obj, '#ff8800')。metal 金属度 0~1，rough 粗糙度 0~1，alpha 不透明度。"""
    key = "%s_%g_%g_%g" % (rgb_hex.strip().lstrip("#").lower(), metal, rough, alpha)
    return _set_mat(obj, _material(key, rgb_hex, metal, rough, alpha))


def part(obj, name, cn="", info="", group="", explode=None):
    """登记零件信息。name 英文名（字母数字下划线，唯一）；cn 中文名；info 一两句说明；group 分组；
    explode 爆炸图里这个零件飞出去的位移 (dx, dy, dz) 毫米（不写就自动算）。"""
    import re
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name or ""):
        raise ValueError("part 的 name 要用字母开头、只含字母数字下划线，现在是 %r" % name)
    other = bpy.data.objects.get(name)
    if other is not None and other is not obj:
        raise ValueError("零件名 %r 已经被用了，换一个" % name)
    obj.name = name
    obj.data.name = name
    obj["qb_part"] = 1
    obj["cn"] = str(cn)
    obj["info"] = str(info)
    obj["group"] = str(group)
    if explode is not None:
        v = _as_vec3(explode, "explode")
        obj["explode"] = [v.x, v.y, v.z]
    return obj


def _scene_list(key, a, b=None):
    sc = bpy.context.scene
    cur = list(sc.get(key, []))
    cur.append(a.name if b is None else "%s|%s" % tuple(sorted((a.name, b.name))))
    sc[key] = cur


def allow_overlap(a, b):
    """声明 a 和 b 的重叠是故意的，只用于过盈配合、皮带压在轮上这类本来就挤在一起的情况。
    轴穿过板、螺杆穿过臂，应该用 hole() 打孔，不要用它盖住。放在脚本最后调用。"""
    _scene_list("qb_allow_overlap", a, b)


def allow_float(obj):
    """声明这个零件就是不接触别的零件（比如悬浮的示意箭头），检查时不算悬空。放在脚本最后调用。"""
    _scene_list("qb_allow_float", obj)
