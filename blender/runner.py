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

TOL = 0.05          # 毫米：小于这个算接触 / 不算穿模
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
        self.bvh = BVHTree.FromBMesh(bm)
        bm.free()

    @property
    def closed(self):
        return self.nonmanifold == 0 and self.loose == 0

    _DIRS = [Vector(v).normalized() for v in ((0.5377, 0.2713, 0.7982), (-0.3111, 0.8263, 0.4696),
                                               (0.7193, -0.6191, -0.3157))]

    def inside(self, p):
        """射线奇偶法判断点是否在实体内部（网格封闭时才可靠）。射线正好擦过棱时会数错，所以打三条取多数。"""
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
        return votes >= 2


def bbox_gap(a, b):
    d = np.maximum(0, np.maximum(a.lo - b.hi, b.lo - a.hi))
    return float(np.linalg.norm(d))


def pair_relation(a, b):
    """返回 (间隙 mm, 穿入深度 mm)。间隙是表面最近距离的估计；穿入深度是一个零件的点扎进另一个内部的最大深度。"""
    gap = float("inf")
    pen = 0.0
    for p_src, q in ((a, b), (b, a)):
        lo, hi = q.lo - TOL, q.hi + TOL
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
            if bg > TOL:
                gap, pen = bg, 0.0
            elif threaded_fit(a, b):
                gap, pen = 0.0, 0.0
            else:
                gap, pen = pair_relation(a, b)
            for x, y in ((a, b), (b, a)):
                if gap < nearest[x.name][1]:
                    nearest[x.name] = (y.name, gap)
            key = "%s|%s" % tuple(sorted((a.name, b.name)))
            if pen > TOL:
                pairs.append({"a": a.name, "b": b.name, "penetration": round(pen, 2), "allowed": key in allow_ov})
                contact[a.name].append(b.name)
                contact[b.name].append(a.name)
                if key not in allow_ov:
                    issues.append("穿模：%s 和 %s 互相扎进去了，最深约 %.2f mm" % (a.name, b.name, pen))
            elif gap <= TOL:
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
    objs = part_objects()
    if not objs:
        rep["error"] = {"type": "Empty", "msg": "脚本跑完了，但场景里一个零件都没有", "line": None, "src": ""}
        return rep
    sanitize_names(objs)
    plan = None
    pp = os.path.join(job, "plan.json")
    if os.path.exists(pp):
        try:
            plan = json.load(open(pp, encoding="utf-8"))
        except Exception:
            plan = None
    rep["stage"] = "measure"
    m, _ = measure_all(objs, plan)
    rep.update(m)
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
        if bbox_gap(A, B) > TOL:
            gap, pen = bbox_gap(A, B), 0.0
        elif threaded_fit(A, B):
            gap, pen = 0.0, 0.0
            out["note"] = "同规格的螺栓和螺母同轴拧在一起，按螺纹配合算接触"
        else:
            gap, pen = pair_relation(A, B)
        ca, cb = (A.lo + A.hi) / 2, (B.lo + B.hi) / 2
        out["relation"] = {
            "gap": round(gap, 3), "penetration": round(pen, 3),
            "center_delta_b_minus_a": r3(cb - ca),
            "b_min_minus_a_max": r3(B.lo - A.hi), "a_min_minus_b_max": r3(A.lo - B.hi)}
    return out


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
        name = {"build": "report.json", "view": "view.json", "section": "section.json", "measure": "measure.json"}[mode]
        json.dump(rep, open(os.path.join(out, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("QB_RESULT " + json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
