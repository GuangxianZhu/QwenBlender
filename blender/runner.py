# -*- coding: utf-8 -*-
"""在 Blender 里执行 model.py，量尺寸、做检查、渲染、导出。

用法（两种都行）：
    blender --background --factory-startup --python runner.py -- build  <任务目录> [选项]
    python runner.py build <任务目录> [选项]          # 装了 bpy 模块的 Python

模式：
    build    执行 model.py → out/report.json、out/sheet.png、out/model.glb、out/parts.json、out/model.blend
    view     读 out/model.blend，按 --az --el [--focus 零件] 渲染一张图 → out/view.png
    section  读 out/model.blend，按 --axis x|y|z --pos 毫米 剖开渲染 → out/section.png
    measure  读 out/model.blend，量一个零件或两个零件之间的关系 → out/measure.json
    index    导出 bpy / bmesh 的 API 索引 → 指定文件
"""
import io
import json
import math
import os
import random
import re
import sys
import time
import traceback

import bpy
import bmesh  # noqa: E402  (bpy 要先导入)
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TOL = 0.05          # 毫米：扎进去不到这么多不算穿模
FIT = 0.25          # 毫米：间隙不超过这么多算接触（轴和孔的间隙配合一般留 0.1 ~ 0.2）
MAX_SAMPLES = 3000  # 每个零件取多少个采样点


# ------------------------------------------------------------------ 场景

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 0.001
    try:
        sc.unit_settings.length_unit = "MILLIMETERS"
    except Exception:
        pass
    return sc


def run_model(path):
    """执行 model.py。返回 (错误信息或 None, 打印输出)。"""
    import qblib
    qblib._counter.clear()
    del qblib._JOINTS[:]
    src = open(path, encoding="utf-8").read()
    buf = io.StringIO()
    old = sys.stdout
    err = None
    try:
        code = compile(src, "model.py", "exec")
        sys.stdout = buf
        exec(code, {"__name__": "__main__", "__file__": path})
    except SyntaxError as e:
        err = {"type": "SyntaxError", "msg": str(e.msg), "line": e.lineno, "src": (e.text or "").strip()}
    except BaseException as e:  # noqa
        tb = traceback.extract_tb(e.__traceback__)
        line, srcline, via = None, "", ""
        for fr in tb:
            if fr.filename == "model.py":
                line = fr.lineno
        if line:
            lines = src.splitlines()
            srcline = lines[line - 1].strip() if 0 < line <= len(lines) else ""
        last = tb[-1] if tb else None
        if last is not None and last.filename != "model.py":
            via = "%s()" % last.name
        err = {"type": type(e).__name__, "msg": str(e), "line": line, "src": srcline, "via": via}
    finally:
        sys.stdout = old
    return err, buf.getvalue()[-2000:]


def part_objects():
    out = []
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and len(o.data.polygons) > 0 and not o.get("qb_helper"):
            out.append(o)
    out.sort(key=lambda o: o.name)
    return out


def default_material(objs):
    """没上材质的零件给一个中灰色，不然在浅色背景上是一片白，看不清形状。"""
    m = None
    for o in objs:
        if any(x is not None for x in o.data.materials):
            continue
        if m is None:
            m = bpy.data.materials.new("QB_default")
            try:
                m.use_nodes = True
            except Exception:
                pass
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (0.35, 0.37, 0.4, 1)
                bsdf.inputs["Roughness"].default_value = 0.55
            m.diffuse_color = (0.35, 0.37, 0.4, 1)
        o.data.materials.clear()
        o.data.materials.append(m)
    # 只设了 diffuse_color（视图颜色）、没接节点颜色的材质：渲染出来是一片白，把视图颜色搬到节点上
    for mt in {x for o in objs for x in o.data.materials if x is not None}:
        try:
            if not mt.node_tree:
                mt.use_nodes = True
            bsdf = next((n for n in mt.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not bsdf or bsdf.inputs["Base Color"].is_linked:
                continue
            base, dc = tuple(bsdf.inputs["Base Color"].default_value), tuple(mt.diffuse_color)
            if all(abs(base[i] - 0.8) < 1e-3 for i in range(3)) and any(abs(dc[i] - 0.8) > 1e-3 for i in range(3)):
                bsdf.inputs["Base Color"].default_value = (dc[0], dc[1], dc[2], 1)
        except Exception:
            pass


def sanitize_names(objs):
    used = set()
    for o in objs:
        n = re.sub(r"[^A-Za-z0-9_]", "_", o.name)
        if not re.match(r"[A-Za-z]", n):
            n = "P_" + n
        base, k = n, 2
        while n in used:
            n = "%s_%d" % (base, k)
            k += 1
        used.add(n)
        if o.name != n:
            o.name = n
            o.data.name = n


# ------------------------------------------------------------------ 尺子

class Geo:
    """一个零件的世界坐标几何数据。"""

    def __init__(self, obj):
        self.obj = obj
        self.name = obj.name
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.transform(obj.matrix_world)
        if obj.matrix_world.determinant() < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
        self.nverts = len(bm.verts)
        self.nfaces = len(bm.faces)
        self.nonmanifold = sum(1 for e in bm.edges if not e.is_manifold)
        self.loose = sum(1 for v in bm.verts if not v.link_faces)
        self.zero_faces = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
        self.volume = bm.calc_volume(signed=True)
        self.area = sum(f.calc_area() for f in bm.faces)
        co = np.array([v.co[:] for v in bm.verts], dtype=np.float64)
        self.lo, self.hi = co.min(axis=0), co.max(axis=0)
        bm.normal_update()          # 带孔的面是凹多边形，三角化之前法线要是对的，不然三角形会盖住孔
        bmesh.ops.triangulate(bm, faces=bm.faces)
        self.tris = len(bm.faces)
        # 采样点：全部顶点 + 按面积在三角形里均匀撒点。
        # 大平面、长圆柱只有很少几个顶点，只看顶点会漏掉「一根杆整个插进一块板」这种情况。
        rnd = random.Random(1234)
        verts = [v.co.copy() for v in bm.verts]
        if len(verts) > MAX_SAMPLES // 2:
            verts = rnd.sample(verts, MAX_SAMPLES // 2)
        budget = MAX_SAMPLES - len(verts)
        areas = [f.calc_area() for f in bm.faces]
        total = sum(areas) or 1.0
        cell = total / budget                     # 平均每个点管多大面积
        pts = verts
        for f, ar in zip(bm.faces, areas):
            k = ar / cell
            n = int(k) + (1 if rnd.random() < k - int(k) else 0)
            if n == 0:
                continue
            p0, p1, p2 = (v.co for v in f.verts)
            if n == 1:
                pts.append((p0 + p1 + p2) / 3)
                continue
            for _ in range(n):
                r1, r2 = math.sqrt(rnd.random()), rnd.random()
                pts.append(p0 * (1 - r1) + p1 * (r1 * (1 - r2)) + p2 * (r1 * r2))
        self.pts = pts
        self.tri = np.array([[v.co[:] for v in f.verts] for f in bm.faces], dtype=np.float64).reshape(-1, 3, 3)
        self.bvh = BVHTree.FromBMesh(bm)
        bm.free()

    @property
    def closed(self):
        return self.nonmanifold == 0 and self.loose == 0

    _DIRS = [Vector(v).normalized() for v in ((0.5377, 0.2713, 0.7982), (-0.3111, 0.8263, 0.4696),
                                               (0.7193, -0.6191, -0.3157))]

    def inside(self, p):
        """点是否在实体内部（网格封闭时才可靠）。
        先用射线奇偶法快速判断（三条射线取多数）；它说「在里面」时再用绕数复核一遍：
        join 出来的零件里，两个壳贴在一起的面是重合的，射线会少数一次，绕数不受影响。"""
        votes = 0
        for d in self._DIRS:
            o = Vector(p)
            n = 0
            for _ in range(128):
                hit = self.bvh.ray_cast(o, d)
                if hit[0] is None:
                    break
                n += 1
                o = hit[0] + d * 1e-4
            votes += n % 2
        if votes < 2:
            return False
        return abs(self.winding(p)) > 0.5

    def winding(self, p):
        """广义绕数：把每个三角形对这个点张的立体角加起来，除以 4π。在实体里面约等于 1，外面约等于 0。"""
        v = self.tri - np.array(p, dtype=np.float64)
        a, b, c = v[:, 0], v[:, 1], v[:, 2]
        la, lb, lc = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1), np.linalg.norm(c, axis=1)
        num = np.einsum("ij,ij->i", a, np.cross(b, c))
        den = la * lb * lc + np.einsum("ij,ij->i", a, b) * lc + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb
        return float(np.sum(2 * np.arctan2(num, den)) / (4 * math.pi))


def bbox_gap(a, b):
    d = np.maximum(0, np.maximum(a.lo - b.hi, b.lo - a.hi))
    return float(np.linalg.norm(d))


LAST_PEN_POINT = [None]      # 最近一次 pair_relation 里扎得最深的那个点（给报告用）


def pair_relation(a, b):
    """返回 (间隙 mm, 穿入深度 mm)。间隙是表面最近距离的估计；穿入深度是一个零件的点扎进另一个内部的最大深度。"""
    gap = float("inf")
    pen = 0.0
    LAST_PEN_POINT[0] = None
    for p_src, q in ((a, b), (b, a)):
        lo, hi = q.lo - FIT, q.hi + FIT
        for p in p_src.pts:
            near = q.bvh.find_nearest(p)
            if near[0] is None:
                continue
            dist = near[3]
            if dist < gap:
                gap = dist
            if dist > TOL and q.closed and lo[0] <= p.x <= hi[0] and lo[1] <= p.y <= hi[1] \
                    and lo[2] <= p.z <= hi[2] and dist > pen and q.inside(p):
                pen = dist
                LAST_PEN_POINT[0] = (p.x, p.y, p.z)
    return gap, pen


def threaded_fit(a, b):
    """a、b 是同规格、同轴的一对螺栓和螺母吗？是的话算「螺纹配合」：接触，不算穿模。
    （螺纹面是离散网格，两边采样位置不同，直接量会有零点零几毫米的假间隙或假干涉。）"""
    oa, ob = a.obj, b.obj
    kinds = {oa.get("qb_kind"), ob.get("qb_kind")}
    if kinds != {"bolt", "nut"}:
        return False
    if abs(oa.get("qb_d", 0) - ob.get("qb_d", 1)) > 1e-6 or abs(oa.get("qb_pitch", 0) - ob.get("qb_pitch", 1)) > 1e-6:
        return False
    bolt, nut_ = (oa, ob) if oa.get("qb_kind") == "bolt" else (ob, oa)
    za = (bolt.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    zb = (nut_.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    if abs(za.dot(zb)) < 0.99996:
        return False
    d = nut_.matrix_world.translation - bolt.matrix_world.translation
    off = (d - za * d.dot(za)).length
    along = -d.dot(za)                      # 螺母底面离螺栓头下表面的距离（沿杆的方向）
    return off < 0.05 and 0 <= along <= bolt.get("qb_length", 0) + 1e-6


def gear_mesh(a, b):
    """a、b 是一对装在正确中心距上的齿轮（或齿轮和内齿圈）吗？是的话它们算接触（齿侧留有间隙，直接量会差一点）。
    穿模照常检查：相位没对上、齿顶到齿，一样会报。"""
    oa, ob = a.obj, b.obj
    ka, kb = oa.get("qb_kind"), ob.get("qb_kind")
    if ka not in ("gear", "ring_gear") or kb not in ("gear", "ring_gear") or (ka == kb == "ring_gear"):
        return False
    m = oa.get("qb_module", 0)
    if abs(m - ob.get("qb_module", -1)) > 1e-6:
        return False
    za = (oa.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    zb = (ob.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    if abs(za.dot(zb)) < 0.9999:
        return False
    d = ob.matrix_world.translation - oa.matrix_world.translation
    dist = (d - za * d.dot(za)).length
    if "ring_gear" in (ka, kb):
        want = m * abs(oa["qb_teeth"] - ob["qb_teeth"]) / 2
    else:
        want = m * (oa["qb_teeth"] + ob["qb_teeth"]) / 2
    return abs(dist - want) < 0.15 and a.lo[2] < b.hi[2] and b.lo[2] < a.hi[2] if abs(za.z) > 0.99 else abs(dist - want) < 0.15


_SIX = (("+x", (1, 0, 0)), ("-x", (-1, 0, 0)), ("+y", (0, 1, 0)), ("-y", (0, -1, 0)), ("+z", (0, 0, 1)), ("-z", (0, 0, -1)))


def _pen_points(src, dst, shift=None):
    """src 的采样点里扎进 dst 内部的那些（shift 给了就先把 src 平移）。"""
    out = []
    lo, hi = dst.lo - FIT, dst.hi + FIT
    for p in src.pts:
        q = p + shift if shift is not None else p
        if not (lo[0] <= q.x <= hi[0] and lo[1] <= q.y <= hi[1] and lo[2] <= q.z <= hi[2]):
            continue
        near = dst.bvh.find_nearest(q)
        if near[0] is not None and near[3] > TOL and dst.inside(q):
            out.append(q)
    return out


def fix_hint(a, b, pen):
    """穿模怎么改。挪一小段就能分开的，给出挪谁、往哪边、挪多少；挪不开的，提示打孔。"""
    if not (a.closed and b.closed):
        return ""
    pa, pb = _pen_points(a, b), _pen_points(b, a)
    if not pa and not pb:
        return ""
    best = None
    for name, e in _SIX:
        e = Vector(e)
        need = 0.0
        for p in pa:                                   # a 往 e 挪：a 扎在 b 里的点要沿 e 走出 b
            hit = b.bvh.ray_cast(p, e)
            need = max(need, hit[3] if hit[0] is not None else 1e9)
        for p in pb:                                   # 等价于 b 扎在 a 里的点沿 -e 走出 a
            hit = a.bvh.ray_cast(p, -e)
            need = max(need, hit[3] if hit[0] is not None else 1e9)
        if best is None or need < best[0]:
            best = (need, name, e)
    need, name, e = best
    small = min(min(a.hi - a.lo), min(b.hi - b.lo))
    if need < 1e8 and need <= max(3.0, 3 * pen) and need <= 0.6 * small:
        sh = e * (need + 0.02)
        if not _pen_points(a, b, sh) and not _pen_points(b, a, -sh):
            other = "-" + name[1] if name[0] == "+" else "+" + name[1]
            first, second = ((a.name, name), (b.name, other)) if abs(a.volume) <= abs(b.volume) else ((b.name, other), (a.name, name))
            return "。改法：把 %s 往 %s 挪 %.2f mm（或者把 %s 往 %s 挪这么多）就不穿了" % (first + (need + 0.02,) + second)
    thin, thick = (a, b) if abs(a.volume) <= abs(b.volume) else (b, a)
    return ("。挪一点分不开，不像是放偏了：如果是 %s 要穿过 %s，给 %s 打孔（hole / shaft_through / pin_joint）；"
            "不是的话检查这两个零件的位置和尺寸" % (thin.name, thick.name, thick.name))


# ------------------------------------------------------------------ 把图变成字

def _alpha(obj):
    """零件材质的不透明度（1 不透明）。"""
    m = obj.active_material
    if m is None:
        return 1.0
    try:
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m.node_tree else None
        if bsdf is not None and not bsdf.inputs["Alpha"].is_linked:
            return float(min(bsdf.inputs["Alpha"].default_value, m.diffuse_color[3]))
    except Exception:
        pass
    return float(m.diffuse_color[3])


def hidden_from(geos, v, subjects=None, blockers=None, n_pts=120):
    """从方向 v（指向相机）看，哪些零件被别的零件挡住了。返回 {零件名: (被挡住的比例, 主要是谁挡的)}。
    只数零件朝向相机那一面的采样点；半透明的零件不算遮挡。"""
    v = Vector(v).normalized()
    names = [g.name for g in geos]
    solid = [g for g in geos if (blockers is None or g.name in blockers) and _alpha(g.obj) >= 0.6]
    out = {}
    for g in geos:
        if subjects is not None and g.name not in subjects:
            continue
        pts = g.pts if len(g.pts) <= n_pts else g.pts[::max(1, len(g.pts) // n_pts)]
        facing = blocked = 0
        who = {}
        for p in pts:
            o = p + v * 1e-3
            if g.bvh.ray_cast(o, v)[0] is not None:        # 背对相机的一面，本来就看不到
                continue
            facing += 1
            for q in solid:
                if q is g:
                    continue
                if q.bvh.ray_cast(o, v)[0] is not None:
                    blocked += 1
                    who[q.name] = who.get(q.name, 0) + 1
                    break
        if facing >= 8:
            out[g.name] = (blocked / facing, max(who, key=who.get) if who else None)
    return out


def view_text(geos):
    """四视图里看不到的零件，写成文字。"""
    if len(geos) < 2:
        return []
    per = [(label.split("  ")[0], hidden_from(geos, view_dir(az, el))) for label, az, el in SHEET_VIEWS]
    lines, always = [], []
    for g in geos:
        hs = [h.get(g.name) for _, h in per]
        if all(x is not None and x[0] >= 0.9 for x in hs):
            always.append((g.name, hs[-1][1]))
    for name, by in always:
        lines.append("%s 在四个视图里都看不到（被 %s 挡住）。要确认它就用 section 剖开；网页里讲它的那一步要把 %s 写进 ghost" % (name, by, by))
    skip = {n for n, _ in always}
    for view, h in per:
        hid = [(n, x[1]) for n, x in h.items() if x[0] >= 0.9 and n not in skip]
        if hid:
            lines.append("%s 视图里看不到：%s" % (view, "、".join("%s（被 %s 挡住）" % (n, by) for n, by in hid[:8])))
    return lines


def r3(v, nd=2):
    return [round(float(c), nd) for c in v]


def measure_all(objs, plan=None):
    sc = bpy.context.scene
    allow_ov = set(sc.get("qb_allow_overlap", []))
    allow_fl = set(sc.get("qb_allow_float", []))
    geos = [Geo(o) for o in objs]
    parts, issues, warns = [], [], []
    for g in geos:
        o = g.obj
        d = {
            "name": g.name, "cn": o.get("cn", ""), "info": o.get("info", ""), "group": o.get("group", ""),
            "registered": bool(o.get("qb_part")),
            "size": r3(g.hi - g.lo), "min": r3(g.lo), "max": r3(g.hi), "center": r3((g.lo + g.hi) / 2),
            "origin": r3(o.matrix_world.translation),
            "volume": round(abs(g.volume), 1), "faces": g.nfaces, "closed": g.closed,
        }
        if "explode" in o.keys():
            d["explode"] = r3(o["explode"])
        parts.append(d)
        if not g.closed:
            issues.append("破面：%s 的网格没封闭（%d 条开口边），体积和穿模检查不可靠。"
                          "常见原因：布尔运算的两个面正好重合，把刀具多伸出去一点" % (g.name, g.nonmanifold))
        elif g.volume < 0:
            issues.append("法线反了：%s 的面朝里" % g.name)
        if g.zero_faces > max(4, g.nfaces // 50):
            warns.append("%s 有 %d 个面积为 0 的面" % (g.name, g.zero_faces))
        if not d["registered"]:
            warns.append("%s 还没用 part() 登记中文名和说明" % g.name)
        if min(d["size"]) < 1e-3:
            issues.append("%s 是扁的（某个方向尺寸为 0）" % g.name)

    # 两两关系
    n = len(geos)
    contact = {g.name: [] for g in geos}
    nearest = {g.name: (None, float("inf")) for g in geos}
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = geos[i], geos[j]
            bg = bbox_gap(a, b)
            if bg > FIT:
                gap, pen = bg, 0.0
            elif threaded_fit(a, b):
                gap, pen = 0.0, 0.0
            else:
                gap, pen = pair_relation(a, b)
                if pen <= TOL and gear_mesh(a, b):
                    gap = 0.0
            for x, y in ((a, b), (b, a)):
                if gap < nearest[x.name][1]:
                    nearest[x.name] = (y.name, gap)
            key = "%s|%s" % tuple(sorted((a.name, b.name)))
            if pen > TOL:
                pairs.append({"a": a.name, "b": b.name, "penetration": round(pen, 2), "allowed": key in allow_ov})
                contact[a.name].append(b.name)
                contact[b.name].append(a.name)
                pt = LAST_PEN_POINT[0]
                where = "，最深的地方在 (%g, %g, %g) 附近" % tuple(round(c, 1) for c in pt) if pt else ""
                if key not in allow_ov:
                    issues.append("穿模：%s 和 %s 互相扎进去了，最深约 %.2f mm%s%s" % (a.name, b.name, pen, where, fix_hint(a, b, pen)))
                elif pen > 1.0:
                    issues.append("穿模：%s 和 %s 用 allow_overlap 声明了重叠，但扎进去约 %.2f mm%s，这不是配合，是实体穿过实体。"
                                  "给被穿过的零件用 hole() 打孔，然后删掉这条 allow_overlap" % (a.name, b.name, pen, where))
                else:
                    warns.append("已声明允许重叠：%s 和 %s（约 %.2f mm）" % (a.name, b.name, pen))
            elif gap <= FIT:
                contact[a.name].append(b.name)
                contact[b.name].append(a.name)

    # 悬空 / 分组
    if n > 1:
        seen, groups = set(), []
        for g in geos:
            if g.name in seen:
                continue
            stack, comp = [g.name], []
            while stack:
                k = stack.pop()
                if k in seen:
                    continue
                seen.add(k)
                comp.append(k)
                stack.extend(contact[k])
            groups.append(sorted(comp))
        for g in geos:
            if not contact[g.name] and g.name not in allow_fl:
                nb, gap = nearest[g.name]
                warns.append("悬空：%s 不接触任何零件（离它最近的是 %s，间隙约 %.2f mm）" % (g.name, nb, gap))
        big = [c for c in groups if len(c) > 1]
        if len(big) > 1:
            warns.append("装配体分成了 %d 组互不接触的零件：%s" % (
                len(big), "；".join("[" + ", ".join(c[:6]) + ("…" if len(c) > 6 else "") + "]" for c in big)))
    for p in parts:
        p["touches"] = sorted(contact[p["name"]])

    # 对照计划
    if plan and plan.get("parts"):
        have = {p["name"]: p for p in parts}
        for pp in plan["parts"]:
            nm = pp.get("name")
            if nm not in have:
                warns.append("计划里的零件 %s 还没做出来" % nm)
                continue
            want = pp.get("size")
            if want and len(want) == 3:
                got = have[nm]["size"]
                bad = [k for k in range(3) if abs(got[k] - want[k]) > max(1.0, 0.15 * abs(want[k]))]
                if bad and sorted(round(x) for x in got) != sorted(round(x) for x in want):
                    warns.append("%s 的尺寸 %s 和计划的 %s 差得比较多" % (nm, got, r3(want)))
        planned = {pp.get("name") for pp in plan["parts"]}
        extra = [p["name"] for p in parts if p["name"] not in planned]
        if extra:
            warns.append("这些零件不在计划里：%s" % "、".join(extra[:8]))

    if geos:
        lo = np.min([g.lo for g in geos], axis=0)
        hi = np.max([g.hi for g in geos], axis=0)
    else:
        lo = hi = np.zeros(3)
    return {"parts": parts, "issues": issues, "warnings": warns, "pairs": pairs,
            "total": {"min": r3(lo), "max": r3(hi), "size": r3(hi - lo)}}, geos


# ------------------------------------------------------------------ 眼睛

def _emit_mat(name, rgb):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1)
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    m.diffuse_color = (rgb[0], rgb[1], rgb[2], 1)
    return m


def _helper(obj):
    obj["qb_helper"] = 1
    try:
        obj.visible_shadow = False
    except Exception:
        pass
    return obj


def setup_render(res, samples, device):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    try:
        sc.cycles.use_denoising = True
    except Exception:
        pass
    sc.cycles.device = "CPU"
    if device == "gpu":
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = kind
                    prefs.get_devices()
                    devs = [d for d in prefs.devices if d.type == kind]
                    if devs:
                        for d in prefs.devices:
                            d.use = d.type == kind
                        sc.cycles.device = "GPU"
                        break
                except Exception:
                    continue
        except Exception:
            pass
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    try:
        sc.view_settings.view_transform = "Standard"
    except Exception:
        pass
    w = bpy.data.worlds.new("QB_World")
    try:
        w.use_nodes = True
    except Exception:
        pass
    bg = next((nd for nd in w.node_tree.nodes if nd.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.78, 0.81, 0.85, 1)
        bg.inputs[1].default_value = 0.9
    sc.world = w
    for name, energy, rot in (("QB_Key", 3.2, (50, 0, 35)), ("QB_Fill", 1.0, (60, 0, -140))):
        ld = bpy.data.lights.new(name, "SUN")
        ld.energy = energy
        ld.angle = math.radians(8)
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = [math.radians(a) for a in rot]
        sc.collection.objects.link(lo)
        _helper(lo)
    cd = bpy.data.cameras.new("QB_Cam")
    cd.type = "ORTHO"
    cam = bpy.data.objects.new("QB_Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    _helper(cam)
    return cam


def view_dir(az, el):
    """相机相对目标的方向。az=0 在 -Y（正前方），az=90 在 +X（右侧）；el 是仰角。"""
    a, e = math.radians(az), math.radians(el)
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def _text(body, size, mat):
    cu = bpy.data.curves.new("QB_Text", "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = "LEFT"
    ob = bpy.data.objects.new("QB_Text", cu)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    return _helper(ob)


def _cyl_between(p0, p1, r, mat):
    v = p1 - p0
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=r, radius2=r, depth=v.length)
    me = bpy.data.meshes.new("QB_Giz")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("QB_Giz", me)
    ob.matrix_world = Matrix.Translation((p0 + p1) / 2) @ Vector((0, 0, 1)).rotation_difference(v.normalized()).to_matrix().to_4x4()
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    return _helper(ob)


def render_view(cam, lo, hi, az, el, label, path, zoom_lo=None, zoom_hi=None, gizmo=True):
    """渲染一张正交视图。lo/hi 是整体包围盒；zoom_lo/zoom_hi 给了就对着那个盒子取景。"""
    sc = bpy.context.scene
    lo, hi = Vector(lo), Vector(hi)
    flo, fhi = (Vector(zoom_lo), Vector(zoom_hi)) if zoom_lo is not None else (lo, hi)
    center = (flo + fhi) / 2
    rad_all = max((hi - lo).length / 2, 1e-3) + (center - (lo + hi) / 2).length
    d = view_dir(az, el)
    cam.location = center + d * (rad_all * 3 + 10)
    # 相机坐标轴直接算出来：右 = 水平方向，上 = 右 × 前。俯视时 +Y 朝屏幕上方
    right = Vector((math.cos(math.radians(az)), math.sin(math.radians(az)), 0.0))
    upv = right.cross(-d).normalized()
    rot = Matrix((right, upv, d)).transposed()
    cam.rotation_euler = rot.to_euler()
    cam.data.clip_start = 0.01
    cam.data.clip_end = rad_all * 8 + 100
    bpy.context.view_layer.update()
    inv = cam.matrix_world.inverted()
    ext = 0.0
    for cx in (flo.x, fhi.x):
        for cy in (flo.y, fhi.y):
            for cz in (flo.z, fhi.z):
                p = inv @ Vector((cx, cy, cz))
                ext = max(ext, abs(p.x), abs(p.y))
    scale = max(ext * 2 * (1.18 if zoom_lo is None else 1.6), 1e-3)
    cam.data.ortho_scale = scale
    black = _emit_mat("QB_Black", (0.02, 0.02, 0.02))
    tmp = []
    t = _text(label, scale * 0.036, black)
    t.matrix_world = cam.matrix_world @ Matrix.Translation((-0.47 * scale, 0.43 * scale, -1.0))
    tmp.append(t)
    if gizmo:
        o = cam.matrix_world @ Vector((-0.39 * scale, -0.37 * scale, -1.0 - 0.1 * scale))
        ln = scale * 0.075
        for axis, rgb, nm in ((Vector((1, 0, 0)), (0.9, 0.08, 0.08), "X"), (Vector((0, 1, 0)), (0.05, 0.6, 0.1), "Y"),
                              (Vector((0, 0, 1)), (0.1, 0.25, 0.95), "Z")):
            m = _emit_mat("QB_Axis" + nm, rgb)
            if abs(axis.dot(d)) < 0.985:
                tmp.append(_cyl_between(o, o + axis * ln, scale * 0.004, m))
            tx = _text(nm, scale * 0.03, m)
            tip = o + axis * ln * 1.18
            tx.matrix_world = Matrix.Translation(tip) @ cam.matrix_world.to_3x3().to_4x4() @ \
                Matrix.Translation((-scale * 0.009, -scale * 0.011, 0))
            tmp.append(tx)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for ob in tmp:
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data and data.users == 0:
            (bpy.data.curves if isinstance(data, bpy.types.Curve) else bpy.data.meshes).remove(data)
    return path


def stitch(paths, out, cols=2):
    imgs = []
    for p in paths:
        im = bpy.data.images.load(p)
        w, h = im.size
        a = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        imgs.append(a.reshape(h, w, 4))
        bpy.data.images.remove(im)
    h, w = imgs[0].shape[:2]
    rows = (len(imgs) + cols - 1) // cols
    gap = 4
    sheet = np.zeros((rows * h + (rows - 1) * gap, cols * w + (cols - 1) * gap, 4), dtype=np.float32)
    sheet[..., :3] = 0.12
    sheet[..., 3] = 1
    for i, a in enumerate(imgs):
        r, c = divmod(i, cols)
        y0 = (rows - 1 - r) * (h + gap)   # 图像数据是自下而上的
        x0 = c * (w + gap)
        sheet[y0:y0 + h, x0:x0 + w] = a
    im = bpy.data.images.new("QB_Sheet", sheet.shape[1], sheet.shape[0], alpha=False)
    im.pixels.foreach_set(sheet.ravel())
    im.filepath_raw = out
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    return out


SHEET_VIEWS = (("FRONT  (camera at -Y)", 0, 0), ("RIGHT  (camera at +X)", 90, 0),
               ("TOP  (camera at +Z, +Y is up)", 0, 90), ("ISO", 35, 28))


def render_sheet(out_dir, lo, hi, res, samples, device):
    cam = setup_render(res, samples, device)
    paths = []
    for i, (label, az, el) in enumerate(SHEET_VIEWS):
        paths.append(render_view(cam, lo, hi, az, el, label,
                                 os.path.join(out_dir, "_v%d.png" % i)))
    sheet = stitch(paths, os.path.join(out_dir, "sheet.png"))
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return sheet


def _mesh_volume(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    v = abs(bm.calc_volume(signed=True))
    bm.free()
    return v


CAP_COLORS = (("红", (0.85, 0.12, 0.1)), ("橙", (0.95, 0.5, 0.05)), ("黄", (0.9, 0.82, 0.1)),
              ("绿", (0.15, 0.65, 0.2)), ("青", (0.1, 0.7, 0.75)), ("蓝", (0.15, 0.3, 0.9)),
              ("紫", (0.55, 0.2, 0.8)), ("粉", (0.95, 0.45, 0.7)), ("棕", (0.5, 0.3, 0.12)),
              ("白", (0.95, 0.95, 0.95)))


def do_section(out_dir, objs, lo, hi, axis, pos, res, samples, device):
    """沿 axis 在 pos 处剖开，去掉坐标更大的那一半，从那一侧看过去。每个被切到的零件，切面用一种颜色。"""
    k = "xyz".index(axis)
    cut_at = pos + 1.37e-3      # 稍微错开一点，避免剖切面正好压在网格的点上
    lo, hi = Vector(lo), Vector(hi)
    big = (hi - lo).length * 2 + 10
    c = (lo + hi) / 2
    c[k] = cut_at + big / 2
    legend = []
    for o in objs:
        zs = [(o.matrix_world @ v.co)[k] for v in o.data.vertices]
        if min(zs) >= cut_at - 1e-6:
            o.hide_render = True
            continue
        if max(zs) <= cut_at + 1e-6:
            continue
        cname, rgb = CAP_COLORS[len(legend) % len(CAP_COLORS)]
        legend.append({"part": o.name, "color": cname})
        cap = _emit_mat("QB_Cap_" + o.name, rgb)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        me = bpy.data.meshes.new("QB_Cutter")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(cap)
        cutter = _helper(bpy.data.objects.new("QB_Cutter", me))
        bpy.context.scene.collection.objects.link(cutter)
        cutter.scale = (big, big, big)
        cutter.location = c
        cutter.hide_render = True
        bpy.context.view_layer.update()
        if not o.data.materials:
            o.data.materials.append(bpy.data.materials.new("QB_Default"))
        m = o.modifiers.new("qb_section", "BOOLEAN")
        m.operation = "DIFFERENCE"
        m.object = cutter
        if hasattr(m, "material_mode"):
            m.material_mode = "TRANSFER"
        # 挑一个结果正常的求解器：切完体积应该在原来的 0.5% ~ 99.9% 之间
        vol0 = _mesh_volume(o.data)
        for alt in ("MANIFOLD", "EXACT", "FLOAT", "FAST"):
            try:
                m.solver = alt
            except TypeError:
                continue
            dg = bpy.context.evaluated_depsgraph_get()
            ev = o.evaluated_get(dg).data
            if len(ev.polygons) and 0.005 * vol0 < _mesh_volume(ev) < 0.999 * vol0:
                break
    cam = setup_render(res, samples, device)
    az, el = {"x": (90, 0), "y": (180, 0), "z": (0, 90)}[axis]
    hi2 = hi.copy()
    hi2[k] = min(hi[k], cut_at)
    label = "SECTION %s=%.1f  (looking toward -%s)" % (axis.upper(), pos, axis.upper())
    path = os.path.join(out_dir, "section.png")
    render_view(cam, lo, hi2 if hi2[k] > lo[k] else hi, az, el, label, path)
    return path, legend


# ------------------------------------------------------------------ 导出

def export_glb(out_dir, objs):
    sc = bpy.context.scene
    root = bpy.data.objects.new("QB_ROOT", None)
    sc.collection.objects.link(root)
    root.scale = (0.001, 0.001, 0.001)
    for o in objs:
        o.parent = root
        o.matrix_parent_inverse = Matrix.Identity(4)
    bpy.context.view_layer.update()
    for o in sc.objects:
        o.select_set(o is root or o in objs)
    path = os.path.join(out_dir, "model.glb")
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_extras=True,
              export_apply=True, export_yup=True, export_animations=False, export_cameras=False,
              export_lights=False)
    for _ in range(6):
        try:
            bpy.ops.export_scene.gltf(**kw)
            break
        except TypeError as e:
            bad = re.search(r'keyword "(\w+)" unrecognized', str(e))
            if not bad or bad.group(1) not in kw:
                raise
            kw.pop(bad.group(1))
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = Matrix.Diagonal((1000, 1000, 1000, 1)) @ mw
    bpy.data.objects.remove(root, do_unlink=True)
    bpy.context.view_layer.update()
    return path


# ------------------------------------------------------------------ 模式

def load_blend(job):
    path = os.path.join(job, "out", "model.blend")
    if not os.path.exists(path):
        raise SystemExit("还没有构建结果，先运行 build")
    bpy.ops.wm.open_mainfile(filepath=path)


def mode_build(job, a):
    t0 = time.time()
    out = os.path.join(job, "out")
    os.makedirs(out, exist_ok=True)
    rep = {"ok": False, "stage": "exec"}
    reset_scene()
    err, printed = run_model(os.path.join(job, "model.py"))
    rep["printed"] = printed
    if err:
        rep["error"] = err
        return rep
    bpy.context.view_layer.update()         # 脚本里直接改 location / rotation_euler 的，要刷新一次才会算进世界坐标
    kids = [(o, o.matrix_world.copy()) for o in bpy.context.scene.objects if o.parent is not None]
    for o, mw in kids:                      # 有父子关系的先拆开、位置保持不变，后面导出时每个零件要单独挂到根节点上
        o.parent = None
        o.matrix_world = mw
    if kids:
        bpy.context.view_layer.update()
    objs = part_objects()
    if not objs:
        rep["error"] = {"type": "Empty", "msg": "脚本跑完了，但场景里一个零件都没有", "line": None, "src": ""}
        return rep
    sanitize_names(objs)
    default_material(objs)
    plan = None
    pp = os.path.join(job, "plan.json")
    if os.path.exists(pp):
        try:
            plan = json.load(open(pp, encoding="utf-8"))
        except Exception:
            plan = None
    rep["stage"] = "measure"
    m, geos = measure_all(objs, plan)
    rep.update(m)
    rep["joints"] = joint_list()
    rep["hidden"] = view_text(geos)
    json.dump(m["parts"], open(os.path.join(out, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "model.blend"), check_existing=False)
    rep["stage"] = "export"
    export_glb(out, objs)
    if not a.get("no_render"):
        rep["stage"] = "render"
        render_sheet(out, m["total"]["min"], m["total"]["max"], a["res"], a["samples"], a["device"])
        rep["image"] = "sheet.png"
    rep["ok"] = True
    rep["stage"] = "done"
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def joint_list():
    """model.py 里用 pin_joint / shaft_through 做出来的销子和轴。"""
    import qblib
    out = []
    for j in qblib._JOINTS:
        try:
            names = [o.name for o in j["parts"]]
            out.append({"kind": j["kind"], "name": j["obj"].name, "parts": names,
                        "point": [round(c, 3) for c in j["point"]], "axis": [round(c, 4) for c in j["axis"]]})
        except ReferenceError:          # 之后被删掉或者并进别的零件了
            continue
    return out


def _total(objs):
    los, his = [], []
    for o in objs:
        co = [o.matrix_world @ v.co for v in o.data.vertices]
        los.append([min(c[k] for c in co) for k in range(3)])
        his.append([max(c[k] for c in co) for k in range(3)])
    return np.min(los, axis=0), np.max(his, axis=0), dict(zip([o.name for o in objs], zip(los, his)))


def mode_view(job, a):
    load_blend(job)
    objs = part_objects()
    lo, hi, per = _total(objs)
    zl = zh = None
    focus = a.get("focus")
    if focus:
        if focus not in per:
            return {"ok": False, "error": {"type": "Name", "msg": "没有叫 %s 的零件。现有：%s" % (
                focus, "、".join(sorted(per)))}}
        zl, zh = per[focus]
    cam = setup_render(a["res"], a["samples"], a["device"])
    el = max(-90.0, min(90.0, a["el"]))
    label = "VIEW az=%g el=%g%s" % (a["az"], a["el"], ("  focus=" + focus) if focus else "")
    render_view(cam, lo, hi, a["az"], el, label, os.path.join(job, "out", "view.png"), zl, zh)
    return {"ok": True, "image": "view.png"}


def mode_section(job, a):
    load_blend(job)
    objs = part_objects()
    lo, hi, _ = _total(objs)
    axis = a["axis"].lower()
    k = "xyz".index(axis)
    pos = a.get("pos")
    if pos is None:
        pos = float((lo[k] + hi[k]) / 2)
    if not (lo[k] < pos < hi[k]):
        return {"ok": False, "error": {"type": "Range", "msg": "剖切位置 %s=%g 在模型外面（模型范围 %.1f ~ %.1f）" % (
            axis, pos, lo[k], hi[k])}}
    _, legend = do_section(os.path.join(job, "out"), objs, lo, hi, axis, pos, a["res"], a["samples"], a["device"])
    return {"ok": True, "image": "section.png", "axis": axis, "pos": round(pos, 2), "legend": legend}


def mode_measure(job, a):
    load_blend(job)
    objs = {o.name: o for o in part_objects()}
    names = [n for n in (a.get("a"), a.get("b")) if n]
    for n in names:
        if n not in objs:
            return {"ok": False, "error": {"type": "Name", "msg": "没有叫 %s 的零件。现有：%s" % (
                n, "、".join(sorted(objs)))}}
    g = [Geo(objs[n]) for n in names]
    out = {"ok": True, "items": []}
    for x in g:
        o = x.obj
        out["items"].append({
            "name": x.name, "size": r3(x.hi - x.lo), "min": r3(x.lo), "max": r3(x.hi),
            "center": r3((x.lo + x.hi) / 2), "origin": r3(o.matrix_world.translation),
            "rotation_deg": r3([math.degrees(c) for c in o.matrix_world.to_euler("XYZ")], 1),
            "volume": round(abs(x.volume), 1), "area": round(x.area, 1), "closed": x.closed, "faces": x.nfaces})
    if len(g) == 2:
        A, B = g
        if bbox_gap(A, B) > FIT:
            gap, pen = bbox_gap(A, B), 0.0
        elif threaded_fit(A, B):
            gap, pen = 0.0, 0.0
            out["note"] = "同规格的螺栓和螺母同轴拧在一起，按螺纹配合算接触"
        else:
            gap, pen = pair_relation(A, B)
            if pen <= TOL and gear_mesh(A, B):
                gap = 0.0
                out["note"] = "两个齿轮的中心距正好是啮合距离，按啮合算接触"
        ca, cb = (A.lo + A.hi) / 2, (B.lo + B.hi) / 2
        out["relation"] = {
            "gap": round(gap, 3), "penetration": round(pen, 3),
            "center_delta_b_minus_a": r3(cb - ca),
            "b_min_minus_a_max": r3(B.lo - A.hi), "a_min_minus_b_max": r3(A.lo - B.hi)}
    return out


# ------------------------------------------------------------------ 动起来以后的检查

_AX = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}


def _axis_v(a, default="z"):
    a = default if a is None else a
    if isinstance(a, (list, tuple)):
        return Vector([float(c) for c in a]).normalized()
    k = str(a).lower().strip()
    sign = -1.0 if k.startswith("-") else 1.0
    return Vector(_AX[k.lstrip("+-")]) * sign


class _Skip(Exception):
    pass


def _num(x, params, t):
    if isinstance(x, (int, float)):
        return float(x)
    env = {k: getattr(math, k) for k in ("sin", "cos", "tan", "sqrt", "floor", "ceil", "atan", "atan2", "asin", "acos", "exp", "log", "hypot")}
    env.update(abs=abs, min=min, max=max, pow=pow, round=round, PI=math.pi, E=math.e, t=t)
    env.update(params)
    try:
        return float(eval(str(x).replace("Math.", ""), {"__builtins__": {}}, env))
    except Exception:
        raise _Skip("表达式 %r 没法在检查里计算" % (x,))


def _prog(t, a):
    tm = max(0.05, float(a.get("time") or 2))
    pause = float(a.get("pause", 0.6))
    t = t - float(a.get("delay") or 0)
    if t <= 0:
        return 0.0
    loop = a.get("loop", "once")
    if loop == "repeat":
        u = min(1.0, (t % (tm + pause)) / tm)
    elif loop == "pingpong":
        tt = t % (2 * (tm + pause))
        u = tt / tm if tt < tm else 1.0 if tt < tm + pause else 1 - (tt - tm - pause) / tm if tt < 2 * tm + pause else 0.0
    else:
        u = min(1.0, t / tm)
    return u if a.get("ease") == "linear" else u * u * (3 - 2 * u)


def _names(x):
    return [] if x is None else list(x) if isinstance(x, (list, tuple)) else [x]


def _plane(v, n):
    return v - n * v.dot(n)


def _sangle(u, v, n):
    return math.atan2(n.dot(u.cross(v)), u.dot(v))


POINT_KEYS = ("pivot", "center", "crank_pin", "slider_pin", "a", "b", "c", "d")
PAGE_VIEWS = {"front": (0, 0), "back": (180, 0), "right": (90, 0), "left": (-90, 0), "top": (0, 89.5), "bottom": (0, -89.5),
              "iso": (35, 26), "iso2": (-145, 26)}        # 和 web/viewer.js 里的 VIEWS 一样


def resolve_points(anims, centers):
    """动画里写成零件名的点，换成那个零件的中心坐标。"""
    out = []
    for a in anims:
        a = dict(a)
        for k in POINT_KEYS:
            v = a.get(k)
            if isinstance(v, str):
                if v not in centers:
                    raise _Skip("%s 写的是零件名 %r，但模型里没有这个零件" % (k, v))
                a[k] = [float(c) for c in centers[v]]
        out.append(a)
    return out


def pose_at(anims, t, base, params, info=None):
    """按 demo.json 的动画算出时刻 t 每个零件的位置。和 web/viewer.js 的算法一致。返回 {零件名: 4x4 矩阵}，只含动了的零件。
    info 给了的话，往里记每个连杆动画的状态：{动画序号: 摇杆转角（度）或滑块位移（mm）}。"""
    st = {}

    def get(nm):
        if nm not in st and nm in base:
            st[nm] = [base[nm].translation.copy(), base[nm].to_quaternion()]
        return st.get(nm)

    def rot_about(nm, axis, rad, pivot):
        s_ = get(nm)
        if s_ is None:
            return
        q = Matrix.Rotation(rad, 4, axis).to_quaternion()
        if pivot is not None:
            s_[0] = pivot + q @ (s_[0] - pivot)
        s_[1] = q @ s_[1]

    def rigid(names, frm, to, q):
        for nm in names:
            s_ = get(nm)
            if s_ is None:
                continue
            s_[0] = to + q @ (s_[0] - frm)
            s_[1] = q @ s_[1]

    for ai, a in enumerate(anims):
        ty = a.get("type")
        piv = Vector(a["pivot"]) if a.get("pivot") else None
        tl = max(0.0, t - float(a.get("delay") or 0))
        if ty == "spin":
            rot_about(a.get("part"), _axis_v(a.get("axis")), math.radians(_num(a.get("speed", 0), params, t) * tl), piv)
        elif ty == "turn":
            rot_about(a.get("part"), _axis_v(a.get("axis")), math.radians(_num(a.get("by", 0), params, t) * _prog(t, a)), piv)
        elif ty == "move":
            s_ = get(a.get("part"))
            if s_ is not None:
                by = a.get("by") or [0, 0, 0]
                s_[0] = s_[0] + Vector([_num(c, params, t) for c in by]) * _prog(t, a)
        elif ty == "screw":
            d, u = _axis_v(a.get("axis")), _prog(t, a)
            turns, pitch = _num(a.get("turns", 0), params, t), _num(a.get("pitch", 0), params, t)
            rot_about(a.get("part"), d, math.radians(360 * turns * u), piv)
            s_ = get(a.get("part"))
            if s_ is not None:
                s_[0] = s_[0] + d * pitch * turns * u
        elif ty in ("crank_slider", "four_bar"):
            n = _axis_v(a.get("axis"), "y")
            th = math.radians(_num(a["angle"], params, t) if a.get("angle") is not None else _num(a.get("speed", 0), params, t) * tl)
            qc = Matrix.Rotation(th, 4, n).to_quaternion()
            if ty == "crank_slider":
                o, p0, s0 = Vector(a["center"]), Vector(a["crank_pin"]), Vector(a["slider_pin"])
                d = _plane(_axis_v(a.get("slide"), "z"), n).normalized()
                pp = o + qc @ (p0 - o)
                ln = _plane(s0 - p0, n).length
                w = _plane(s0 - pp, n)
                b = d.dot(w)
                disc = max(b * b - w.length_squared + ln * ln, 0.0)
                b0 = d.dot(_plane(s0 - p0, n))
                sl = -b + (1 if b0 >= 0 else -1) * math.sqrt(disc)
                sp = s0 + d * sl
                rigid(_names(a.get("crank")), o, o, qc)
                qr = Matrix.Rotation(_sangle(_plane(s0 - p0, n), _plane(sp - pp, n), n), 4, n).to_quaternion()
                rigid(_names(a.get("rod")), p0, pp, qr)
                for nm in _names(a.get("slider")):
                    s_ = get(nm)
                    if s_ is not None:
                        s_[0] = s_[0] + d * sl
                if info is not None:
                    info[ai] = sl
            else:
                A, B0, C0, D = (Vector(a[k]) for k in "abcd")
                B = A + qc @ (B0 - A)
                r2, r3 = _plane(C0 - B0, n).length, _plane(C0 - D, n).length
                bd = _plane(D - B, n)
                dist = min(max(bd.length, abs(r2 - r3) + 1e-6), r2 + r3 - 1e-6)
                x = (dist * dist + r2 * r2 - r3 * r3) / (2 * dist)
                h = math.sqrt(max(r2 * r2 - x * x, 0.0))
                e1 = bd.normalized()
                e2 = n.cross(e1)
                side = 1 if n.dot(_plane(D - B0, n).cross(_plane(C0 - B0, n))) >= 0 else -1
                C = B + e1 * x + e2 * (side * h)
                C = C + n * (n.dot(C0) - n.dot(C))
                rigid(_names(a.get("crank")), A, A, qc)
                rigid(_names(a.get("coupler")), B0, B,
                      Matrix.Rotation(_sangle(_plane(C0 - B0, n), _plane(C - B, n), n), 4, n).to_quaternion())
                rk = _sangle(_plane(C0 - D, n), _plane(C - D, n), n)
                rigid(_names(a.get("rocker")), D, D, Matrix.Rotation(rk, 4, n).to_quaternion())
                if info is not None:
                    info[ai] = math.degrees(rk)
    return {nm: Matrix.Translation(v[0]) @ v[1].to_matrix().to_4x4() for nm, v in st.items()}


def _proj_range(geo, n):
    """零件包围盒在方向 n 上的范围。"""
    ts = [Vector((x, y, z)).dot(n) for x in (geo.lo[0], geo.hi[0]) for y in (geo.lo[1], geo.hi[1]) for z in (geo.lo[2], geo.hi[2])]
    return min(ts), max(ts)


def _line_in_bbox(geo, P, n, margin=1.0):
    """过 P、方向 n 的直线有没有穿过零件的包围盒。"""
    tmin, tmax = -1e18, 1e18
    for k in range(3):
        lo, hi = geo.lo[k] - margin, geo.hi[k] + margin
        if abs(n[k]) < 1e-9:
            if P[k] < lo or P[k] > hi:
                return False
        else:
            t1, t2 = (lo - P[k]) / n[k], (hi - P[k]) / n[k]
            tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
    return tmin <= tmax


def _inside_len(geo, P, n, t0, t1):
    """过 P、方向 n 的直线上，n 方向坐标 t0~t1 这一段里有多长在零件实体内部。"""
    if t1 - t0 < 1e-6:
        return 0.0
    k = int(min(40, max(4, math.ceil((t1 - t0) / 0.5))))
    step = (t1 - t0) / k
    o = P - n * P.dot(n)
    return step * sum(1 for i in range(k) if geo.inside(o + n * (t0 + (i + 0.5) * step)))


def _near_count(src, dst):
    """src 的采样点里，有多少个贴着 dst 的表面。"""
    return sum(1 for p in src.pts if dst.bvh.find_nearest(p, FIT)[0] is not None)


def _p3(v):
    return "(%s)" % ", ".join("%g" % round(c, 1) for c in v)


def joint_problems(anims, geos, base, where):
    """连杆的铰点上有没有销子、转动零件的转轴上有没有轴。只看静止时的模型。"""
    out = []

    def cands(group, P, n):
        return [g for g in group if g in geos and _line_in_bbox(geos[g], P, n)]

    def thr(c, n):
        r0, r1 = _proj_range(geos[c], n)
        return min(0.5, 0.3 * (r1 - r0))

    def through(X, c, P, n):
        return _inside_len(geos[X], P, n, *_proj_range(geos[c], n)) >= thr(c, n)

    def pinned(P, n, g1, g2):
        c1, c2 = cands(g1, P, n), cands(g2, P, n)
        if not c1 or not c2:
            return None
        for X in geos:
            if not _line_in_bbox(geos[X], P, n, 0.0):
                continue
            if all(X in grp or any(c != X and through(X, c, P, n) for c in cs) for grp, cs in ((g1, c1), (g2, c2))):
                return True
        return False

    def held(P, n, group):
        cs = cands(group, P, n)
        if not cs:
            return None
        return any(through(X, c, P, n) for X in geos if _line_in_bbox(geos[X], P, n, 0.0) for c in cs)

    for a in anims:
        ty = a.get("type")
        if ty == "spin":
            nm = a.get("part")
            if a.get("hollow") or nm not in geos:
                continue
            n = _axis_v(a.get("axis"))
            P = Vector(a["pivot"]) if a.get("pivot") else base[nm].translation.copy()
            if held(P, n, [nm]) is False:
                out.append("%s：%s 绕过 %s 的轴线转，但轴线上是空的（孔里没有轴）。用 shaft_through 配一根轴，或者让轴穿过它；"
                           "它本来就是空心的、不需要轴，就在这个动画里加 \"hollow\": true" % (where, nm, _p3(P)))
        elif ty in ("crank_slider", "four_bar"):
            n = _axis_v(a.get("axis"), "y")
            if ty == "four_bar":
                grp = {k: _names(a.get(k)) for k in ("crank", "coupler", "rocker")}
                moving = (("b", "crank", "coupler"), ("c", "coupler", "rocker"))
                ground = (("a", "crank"), ("d", "rocker"))
                cn = {"crank": "曲柄", "coupler": "连杆", "rocker": "摇杆"}
            else:
                grp = {k: _names(a.get(k)) for k in ("crank", "rod", "slider")}
                moving = (("crank_pin", "crank", "rod"), ("slider_pin", "rod", "slider"))
                ground = (("center", "crank"),)
                cn = {"crank": "曲柄", "rod": "连杆", "slider": "滑块"}
            for key, g1, g2 in moving:
                P = Vector(a[key])
                r = pinned(P, n, grp[g1], grp[g2])
                if r is None:
                    miss = [g for g in (g1, g2) if not cands(grp[g], P, n)]
                    out.append("%s：铰点 %s %s 不在%s这一组零件（%s）上。检查这个点的坐标，或者直接写销子的零件名" % (
                        where, key, _p3(P), "、".join(cn[g] for g in miss), "、".join(x for g in miss for x in grp[g])))
                elif r is False:
                    out.append("%s：%s和%s在铰点 %s %s 没有销子连着（那里是空的，或者只是面贴面）。"
                               "在 model.py 里用 pin_joint(%s, %s, %s, 直径) 补一根销子，再把销子的名字写进其中一组" % (
                                   where, cn[g1], cn[g2], key, _p3(P), grp[g1][0] if grp[g1] else "a", grp[g2][0] if grp[g2] else "b", _p3(P)))
            if a.get("hollow"):
                continue
            for key, g in ground:
                P = Vector(a[key])
                if held(P, n, grp[g]) is False:
                    names = cands(grp[g], P, n)
                    out.append("%s：%s 绕 %s %s 转，但转轴那里是空的，没有轴穿过。在 model.py 里用 shaft_through([%s], 起点, 终点, 直径) "
                               "补一根轴（一头落在支座或电机上）" % (where, "、".join(names), key, _p3(P), ", ".join(names)))
    return out


def mode_motion(job, a):
    """把 demo.json 里每一步的动画摆到几个时刻：动起来以后会不会穿模、贴着的零件会不会离开、铰点和转轴上有没有东西；
    并算出运动范围（摆角、行程、每个零件扫过的范围）。"""
    t0 = time.time()
    load_blend(job)
    cfg = json.load(open(os.path.join(job, "demo.json"), encoding="utf-8-sig"))
    objs = {o.name: o for o in part_objects()}
    base = {n: o.matrix_world.copy() for n, o in objs.items()}
    params = {p["id"]: float(p.get("value", 0)) for p in cfg.get("params", []) if isinstance(p, dict) and "id" in p}
    allow = set(bpy.context.scene.get("qb_allow_overlap", []))
    static = {n: Geo(o) for n, o in objs.items()}
    centers = {n: (g.lo + g.hi) / 2 for n, g in static.items()}
    local = {}
    for n, g in static.items():                         # 每个零件留一些采样点，用来算扫过的范围
        pts = g.pts if len(g.pts) <= 400 else g.pts[::max(1, len(g.pts) // 400)]
        inv = np.array(base[n].inverted())
        w = np.array([p[:] for p in pts], dtype=np.float64)
        local[n] = w @ inv[:3, :3].T + inv[:3, 3]
    names = sorted(objs)
    rest_pen, rest_gap = {}, {}                         # 静止时就穿模的那些对前面已经报过了，这里不重复
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            if bbox_gap(static[x], static[y]) <= FIT:
                k = "%s|%s" % (x, y)
                gap, pen = pair_relation(static[x], static[y])
                rest_gap[k] = gap
                if pen > TOL and not threaded_fit(static[x], static[y]):
                    rest_pen[k] = True
    problems, warnings, notes, ranges, seen, seen_joint, checked = [], [], [], [], set(), set(), 0
    for si, step in enumerate(cfg.get("steps", [])):
        anims = [x for x in step.get("anim", []) if isinstance(x, dict) and x.get("type") != "blink"]
        key = json.dumps(anims, sort_keys=True, ensure_ascii=False)
        if not anims or key in seen:
            continue
        seen.add(key)
        where = "第 %d 步「%s」" % (si + 1, step.get("title", ""))
        try:
            anims = resolve_points(anims, centers)
            links = [i for i, x in enumerate(anims) if x.get("type") in ("crank_slider", "four_bar")]
            cyc = [x for x in anims if x.get("type") in ("spin", "crank_slider", "four_bar")]
            cyc_parts = {nm for x in cyc for k in ("part", "crank", "rod", "slider", "coupler", "rocker") for nm in _names(x.get(k))}
            speeds = [abs(_num(x.get("speed", 0), params, 0.0)) for x in cyc if x.get("angle") is None]
            speeds = [v for v in speeds if v > 1e-9]
            if speeds:
                times = [ang / max(speeds) for ang in (41, 97, 163, 229, 301, 347)]
            else:
                tm = max([float(x.get("time") or 2) + float(x.get("delay") or 0) for x in anims] + [0.5])
                times = [tm * f for f in (0.25, 0.5, 0.75, 1.0)]
            # 角度由滑条给的连杆：把那个滑条从最小扫到最大
            swept = [p for p in cfg.get("params", []) if isinstance(p, dict) and "id" in p and any(
                x.get("angle") is not None and re.search(r"\b%s\b" % re.escape(str(p["id"])), str(x["angle"])) for x in anims)]

            def with_param(f):
                pp = dict(params)
                for p in swept:
                    lo, hi = float(p.get("min", 0)), float(p.get("max", 1))
                    pp[p["id"]] = lo + (hi - lo) * f
                return pp, "滑条 %s 时" % "、".join("%s=%g" % (p["id"], pp[p["id"]]) for p in swept)

            samples = [(t, params, "%.1f 秒时" % t) for t in times]
            for f in ((0.0, 0.2, 0.4, 0.6, 0.8, 1.0) if swept else ()):
                samples.append((times[-1],) + with_param(f))
            # ---- 运动范围：细分很多个时刻，只算位置，不做碰撞
            dense = []
            if speeds:
                lk = [abs(_num(anims[i].get("speed", 0), params, 0.0)) for i in links if anims[i].get("angle") is None]
                lk = [v for v in lk if v > 1e-9]
                period = 360.0 / (min(lk) if lk else min(speeds))
                dense += [(period * i / 180, params, "%.1f 秒时" % (period * i / 180)) for i in range(180)]
            else:
                dense += [(times[-1] * i / 24, params, "%.1f 秒时" % (times[-1] * i / 24)) for i in range(25)]
            if swept:
                dense += [(times[-1],) + with_param(i / 60) for i in range(61)]
            sweep_lo, sweep_hi, ext = {}, {}, {}
            for t, par, label in dense:
                info = {}
                pose = pose_at(anims, t, base, par, info)
                for n, m in pose.items():
                    mm = np.array(m)
                    w = local[n] @ mm[:3, :3].T + mm[:3, 3]
                    lo, hi = w.min(axis=0), w.max(axis=0)
                    sweep_lo[n] = lo if n not in sweep_lo else np.minimum(sweep_lo[n], lo)
                    sweep_hi[n] = hi if n not in sweep_hi else np.maximum(sweep_hi[n], hi)
                for i, v in info.items():
                    e = ext.setdefault(i, [v, v, None, None])
                    if v <= e[0]:
                        e[0], e[2] = v, (t, par, label)
                    if v >= e[1]:
                        e[1], e[3] = v, (t, par, label)
            lines, swing, stroke = [], [], []
            for i in links:
                if i not in ext:
                    continue
                lo, hi, s_lo, s_hi = ext[i]
                x = anims[i]
                if x["type"] == "four_bar":
                    swing.append(round(hi - lo, 1))
                    lines.append("摇杆（%s）摆角 %.1f°：相对初始位置 %+.1f° ~ %+.1f°" % ("、".join(_names(x.get("rocker"))), hi - lo, lo, hi))
                else:
                    stroke.append(round(hi - lo, 1))
                    lines.append("滑块（%s）行程 %.1f mm：相对初始位置 %+.1f ~ %+.1f mm" % ("、".join(_names(x.get("slider"))), hi - lo, lo, hi))
                for smp in (s_lo, s_hi):                 # 摆到两头、走到两头的时刻也要查碰撞
                    if smp is not None:
                        samples.append((smp[0], smp[1], "%s（%s到头）" % (smp[2], "摇杆摆" if x["type"] == "four_bar" else "滑块走")))
            grown = []
            for n in sweep_lo:
                g = static[n]
                grow = max(float(np.max(g.lo - sweep_lo[n])), float(np.max(sweep_hi[n] - g.hi)))
                if grow > 1.0:
                    grown.append((grow, n))
            for grow, n in sorted(grown, reverse=True)[:8]:
                lines.append("%s 扫过的范围 x %g~%g  y %g~%g  z %g~%g" % (
                    n, round(sweep_lo[n][0], 1), round(sweep_hi[n][0], 1), round(sweep_lo[n][1], 1), round(sweep_hi[n][1], 1),
                    round(sweep_lo[n][2], 1), round(sweep_hi[n][2], 1)))
            if lines:
                ranges.append({"step": si + 1, "title": step.get("title", ""), "lines": lines, "swing": swing, "stroke": stroke})
            ever = set(sweep_lo)
            # ---- 在动的零件从这一步的视角看不看得见
            vw = step.get("view")
            preset = vw if isinstance(vw, str) else (vw or {}).get("preset") if isinstance(vw, dict) else None
            if cyc and not step.get("highlight") and not step.get("section") and not step.get("explode") and (vw is None or preset in PAGE_VIEWS):
                az, el = PAGE_VIEWS.get(preset or "iso")
                gone = set(_names(step.get("ghost"))) | set(_names(step.get("hide")))
                main = [nm for x in cyc for k in ("part", "crank", "rod", "slider", "coupler", "rocker") for nm in _names(x.get(k))[:1]]
                hid = hidden_from(list(static.values()), view_dir(az, el), subjects=set(main), blockers=set(names) - gone)
                for nm in dict.fromkeys(main):
                    if nm in hid and hid[nm][0] >= 0.8:
                        msg = "%s：%s 在动，但从这一步的视角（%s）看它有 %d%% 被 %s 挡住。把 %s 写进这一步的 ghost，或者换个视角，或者用 section" % (
                            where, nm, preset or "默认的 iso", round(100 * hid[nm][0]), hid[nm][1], hid[nm][1])
                        (problems if hid[nm][0] >= 0.97 else warnings).append(msg)
            # ---- 铰点和转轴
            jk = json.dumps([{k: v for k, v in x.items() if k not in ("speed", "angle", "delay")} for x in cyc], sort_keys=True, ensure_ascii=False)
            if cyc and jk not in seen_joint:
                seen_joint.add(jk)
                problems += joint_problems(cyc, static, base, where)
            # ---- 碰撞、贴合
            worst, cover, n0 = {}, {}, {}
            for t, par, label in samples:
                pose = pose_at(anims, t, base, par)
                moved = [n for n, m in pose.items() if any(abs(m[r][c] - base[n][r][c]) > 1e-7 for r in range(3) for c in range(4))]
                if not moved:
                    continue
                for n in moved:
                    objs[n].matrix_world = pose[n]
                bpy.context.view_layer.update()
                geo = dict(static)
                geo.update({n: Geo(objs[n]) for n in moved})
                for n in moved:
                    for other in names:
                        if other == n or (other in moved and other < n):
                            continue
                        k = "%s|%s" % tuple(sorted((n, other)))
                        if n in cyc_parts and other not in ever and k not in allow and rest_gap.get(k, 9e9) <= FIT:
                            if k not in n0:
                                n0[k] = _near_count(static[n], static[other])
                            if n0[k] >= 12:
                                ratio = _near_count(geo[n], geo[other]) / n0[k]
                                if ratio < cover.get(k, (9, ""))[0]:
                                    cover[k] = (ratio, label, n, other)
                        if k in rest_pen or k in allow or bbox_gap(geo[n], geo[other]) > 0 or threaded_fit(geo[n], geo[other]):
                            continue
                        pen = pair_relation(geo[n], geo[other])[1]
                        if pen > max(TOL, 0.15) and pen > worst.get(k, (0, 0))[0]:
                            worst[k] = (pen, label)
                for n in moved:
                    objs[n].matrix_world = base[n]
                bpy.context.view_layer.update()
            checked += 1
            for k, (pen, label) in sorted(worst.items(), key=lambda kv: -kv[1][0])[:6]:
                x, y = k.split("|")
                problems.append("%s动起来以后穿模：%s %s 和 %s 互相扎进去约 %.1f mm（静止时不穿）" % (where, label, x, y, pen))
            for k, (ratio, label, n, other) in sorted(cover.items(), key=lambda kv: kv[1][0])[:6]:
                g = static[other]
                rng = "%s 的范围是 x %g~%g  y %g~%g  z %g~%g" % (other, round(g.lo[0], 1), round(g.hi[0], 1), round(g.lo[1], 1),
                                                             round(g.hi[1], 1), round(g.lo[2], 1), round(g.hi[2], 1))
                if ratio <= 0:
                    problems.append("%s：%s 静止时贴着 %s，动起来以后 %s完全离开了它。%s；%s 扫过的范围见下面的运动范围。把 %s 做大或挪到位" % (
                        where, n, other, label, rng, n, other))
                elif ratio < 0.7:
                    warnings.append("%s：%s 贴着 %s 的部分最少时只剩 %d%%（%s），有一部分探到外面去了。%s" % (
                        where, n, other, round(100 * ratio), label, rng))
        except _Skip as e:
            notes.append("第 %d 步没有做运动检查：%s" % (si + 1, e))
    return {"ok": not problems, "problems": problems, "warnings": warnings, "notes": notes, "ranges": ranges,
            "checked_steps": checked, "seconds": round(time.time() - t0, 1)}


def mode_index(path):
    """导出当前 Blender 版本的 API 索引，给 search_bpy 用。"""
    items = []

    def add(kind, name, sig, doc):
        items.append({"k": kind, "n": name, "s": sig, "d": (doc or "").strip().split("\n\n")[0][:300]})

    for mod in dir(bpy.ops):
        if mod.startswith("_"):
            continue
        try:
            sub = getattr(bpy.ops, mod)
            names = dir(sub)
        except Exception:
            continue
        for op in names:
            if op.startswith("_"):
                continue
            try:
                rna = getattr(sub, op).get_rna_type()
                args = []
                for p in rna.properties:
                    if p.identifier == "rna_type":
                        continue
                    args.append(p.identifier)
                add("op", "bpy.ops.%s.%s" % (mod, op), "(%s)" % ", ".join(args[:14]), rna.description)
            except Exception:
                continue
    keep = re.compile(r"^(Object|Mesh|MeshVertex|MeshPolygon|MeshEdge|Material|Camera|Light|SunLight|PointLight|"
                      r"AreaLight|Scene|RenderSettings|Curve|TextCurve|Spline|Collection|World|Image|"
                      r"\w*Modifier|ShaderNode\w*|BlendData\w*|ViewLayer|UnitSettings|Depsgraph|"
                      r"CyclesRenderSettings|Keyframe|FCurve|Action|Constraint|\w+Constraint)$")
    for name in dir(bpy.types):
        if not keep.match(name):
            continue
        try:
            rna = getattr(bpy.types, name).bl_rna
        except Exception:
            continue
        add("type", "bpy.types." + name, "", rna.description)
        for p in rna.properties:
            if p.identifier == "rna_type":
                continue
            sig = p.type.lower()
            if p.type == "ENUM":
                try:
                    sig += " in {%s}" % ", ".join(repr(e.identifier) for e in list(p.enum_items)[:12])
                except Exception:
                    pass
            add("prop", "%s.%s" % (name, p.identifier), sig, p.description)
        for f in rna.functions:
            add("func", "%s.%s" % (name, f.identifier),
                "(%s)" % ", ".join(p.identifier for p in f.parameters if not p.is_output), f.description)
    for n in dir(bmesh.ops):
        if n.startswith("_"):
            continue
        doc = getattr(bmesh.ops, n).__doc__ or ""
        sig = doc.strip().split("\n")[0]
        body = " ".join(l.strip() for l in doc.strip().split("\n")[1:] if l.strip())
        add("bmesh", "bmesh.ops." + n, sig, body)
    json.dump({"version": bpy.app.version_string, "items": items}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False)
    return {"ok": True, "count": len(items), "version": bpy.app.version_string}


def parse(argv):
    a = {"res": 512, "samples": 16, "device": "cpu", "az": 35.0, "el": 28.0}
    pos = []
    i = 0
    while i < len(argv):
        t = argv[i]
        if t.startswith("--"):
            key = t[2:].replace("-", "_")
            if key in ("no_render",):
                a[key] = True
            else:
                i += 1
                v = argv[i]
                a[key] = float(v) if key in ("az", "el", "pos") else int(v) if key in ("res", "samples") else v
        else:
            pos.append(t)
        i += 1
    return pos, a


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    pos, a = parse(argv)
    mode, target = pos[0], pos[1]
    try:
        if mode == "build":
            rep = mode_build(target, a)
        elif mode == "view":
            rep = mode_view(target, a)
        elif mode == "section":
            rep = mode_section(target, a)
        elif mode == "measure":
            rep = mode_measure(target, a)
        elif mode == "motion":
            rep = mode_motion(target, a)
        elif mode == "index":
            rep = mode_index(target)
        else:
            rep = {"ok": False, "error": {"type": "Usage", "msg": "未知模式 " + mode}}
    except SystemExit as e:
        rep = {"ok": False, "error": {"type": "Missing", "msg": str(e)}}
    except BaseException as e:  # noqa
        rep = {"ok": False, "error": {"type": "Internal:" + type(e).__name__, "msg": str(e),
                                      "trace": traceback.format_exc()[-1500:]}}
    rep["blender"] = bpy.app.version_string
    if mode != "index":
        out = os.path.join(target, "out")
        os.makedirs(out, exist_ok=True)
        name = {"build": "report.json", "view": "view.json", "section": "section.json", "measure": "measure.json",
                "motion": "motion.json"}[mode]
        json.dump(rep, open(os.path.join(out, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("QB_RESULT " + json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
