"""鲸鱼娘 semi-chibi 建模 —— 几何工具层

约定：
  * Z 轴向上，原点在脚底中心，正面朝 -Y
  * 所有 mesh 顶点直接构建在世界坐标，物体 transform 保持 identity
    → 这样 Shader 的 Object 纹理坐标 == 世界坐标，发色 Z 渐变全局一致
  * 标度：1 头身 = 1.0 BU
"""
import math
import bmesh
import bpy
from mathutils import Vector

TAU = math.pi * 2


# ────────────────────────────── 场景与材质 ──────────────────────────────

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def hex_rgba(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


PALETTE = {
    "HAIR_ROOT": "#3a5593",
    "HAIR_MID":  "#344b88",
    "HAIR_TIP":  "#58a7d3",
    "DRESS_DEEP": "#28325b",
    "DRESS_MID":  "#2a3663",
    "DRESS_SHADE": "#242c54",
    "BOW_DARK":   "#2d3354",
    "BOW_SKY":    "#539aca",
    "WHITE":      "#fefefe",
    "GOLD":       "#dbbfac",
    "FIN":        "#3c4470",
    "FIN_LIGHT":  "#b9bcd4",
    "FIN_LIGHT":  "#b9bcd4",
    "FIN_LIGHT":  "#b9bcd4",
    "TAIL":       "#323d69",
    "SOCK":       "#e8e4ee",
    "SHOE":       "#262e54",
    "SKIN":       "#f7e2dd",
    "EYE_IRIS":   "#4a7fc0",
    "EYE_LIGHT":  "#a1b3df",
    "OUTLINE":    "#1b2448",
    "BLUSH":      "#f0bcbc",
    "BUSTIER":    "#f4f2f6",
}


def solid_mat(name, hex_color, rough=0.55, metal=0.0, sheen=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = hex_rgba(hex_color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if sheen and "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = sheen
    mat.diffuse_color = hex_rgba(hex_color)
    return mat


def gradient_mat(name, stops, rough=0.42, sheen=0.25):
    """stops: [(z, hex), ...] 按 z 从低到高；用 Object 坐标 Z 驱动渐变。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = rough
    if "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = sheen

    tex = nt.nodes.new("ShaderNodeTexCoord")
    tex.location = (-900, 0)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-700, 0)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-480, 0)

    lo, hi = stops[0][0], stops[-1][0]
    span = max(hi - lo, 1e-6)
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = hex_rgba(stops[0][1])
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = hex_rgba(stops[-1][1])
    for z, h in stops[1:-1]:
        el = ramp.color_ramp.elements.new((z - lo) / span)
        el.color = hex_rgba(h)

    # Object 坐标的 Z 直接落在 [lo, hi]，需先归一化到 [0,1]
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.location = (-600, -220)
    mr.inputs["From Min"].default_value = lo
    mr.inputs["From Max"].default_value = hi
    mr.inputs["To Min"].default_value = 0.0
    mr.inputs["To Max"].default_value = 1.0

    nt.links.new(tex.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    mat.diffuse_color = hex_rgba(stops[-1][1])
    return mat


def build_materials():
    M = {}
    for key in ("DRESS_DEEP", "DRESS_MID", "DRESS_SHADE", "BOW_DARK", "BOW_SKY",
                "WHITE", "GOLD", "FIN", "TAIL", "SOCK", "SHOE", "SKIN",
                "EYE_IRIS", "EYE_LIGHT", "OUTLINE", "BLUSH", "FIN_LIGHT"):
        hexc = PALETTE[key]
        rough = 0.35 if key == "BOW_SKY" else (0.3 if key == "GOLD" else 0.55)
        metal = 0.75 if key == "GOLD" else 0.0
        sheen = 0.3 if key in ("WHITE", "BUSTIER", "SOCK") else 0.0
        M[key] = solid_mat(key, hexc, rough, metal, sheen)
    M["BUSTIER"] = solid_mat("BUSTIER", PALETTE["BUSTIER"], 0.6, 0.0, 0.3)

    # 发色：Z 渐变 根→中→梢（SPEC §1）
    M["HAIR"] = gradient_mat("HAIR", [
        (0.60, PALETTE["HAIR_ROOT"]),
        (1.55, PALETTE["HAIR_MID"]),
        (2.45, PALETTE["HAIR_TIP"]),
    ])
    # 眼睛：垂直渐变 瞳深→下缘反光
    M["EYE"] = gradient_mat("EYE", [
        (1.70, PALETTE["EYE_LIGHT"]),
        (1.82, PALETTE["EYE_IRIS"]),
        (1.95, PALETTE["OUTLINE"]),
    ], rough=0.15)
    return M


# ────────────────────────────── 几何工具 ──────────────────────────────

def _finish(name, bm, mat, smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        me.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob


def add_mesh(name, verts, faces, mat=None, smooth=True):
    bm = bmesh.new()
    bverts = [bm.verts.new(v) for v in verts]
    bm.verts.ensure_lookup_table()
    for f in faces:
        try:
            bm.faces.new([bverts[i] for i in f])
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    return _finish(name, bm, mat, smooth)


def sphere(name, center, radii, mat=None, segs=32, rings=16, smooth=True):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0)
    for v in bm.verts:
        v.co.x *= radii[0]
        v.co.y *= radii[1]
        v.co.z *= radii[2]
        v.co += Vector(center)
    return _finish(name, bm, mat, smooth)


def lathe(name, profile, mat=None, segs=48, cap=True, smooth=True):
    """profile: [(z, r), ...] 自下而上。绕 Z 轴旋转成回转体。"""
    n = len(profile)
    verts, faces = [], []
    for i in range(segs):
        a = TAU * i / segs
        ca, sa = math.cos(a), math.sin(a)
        for z, r in profile:
            verts.append((r * ca, r * sa, z))
    for i in range(segs):
        j = (i + 1) % segs
        for k in range(n - 1):
            faces.append((i * n + k, j * n + k, j * n + k + 1, i * n + k + 1))
    if cap:
        # 顶点是「圈优先」排列：第 i 圈（周向）占 verts[i*n : (i+1)*n]
        # 封口面连接的是轮廓上的 n 个点，而非周向的 segs 个
        if profile[0][1] > 1e-6:
            ci = len(verts); verts.append((0, 0, profile[0][0]))
            for k in range(n):
                j = (k + 1) % n
                faces.append((ci, k, j))
        if profile[-1][1] > 1e-6:
            ci = len(verts); verts.append((0, 0, profile[-1][0]))
            base = (segs - 1) * n
            for k in range(n):
                j = (k + 1) % n
                faces.append((ci, base + k, base + j))
    return add_mesh(name, verts, faces, mat, smooth)


def _catmull_rom(p0, p1, p2, p3, t):
    """标量 Catmull-Rom 插值。"""
    t2, t3 = t * t, t * t * t
    return 0.5 * ((2.0 * p1)
                  + (-p0 + p2) * t
                  + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
                  + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3)


def _densify_stations(stations, subdiv):
    """把稀疏的 (z, r) 站位加密成平滑曲线。

    直接用折线连接相邻站位会在每个站位处留下折角，正面看就是一道道
    横向亮带。这里用 Catmull-Rom 在 z 与 r 两个维度同时插值。
    """
    if subdiv <= 1 or len(stations) < 3:
        return list(stations)
    out = []
    for i in range(len(stations) - 1):
        z1, r1 = stations[i]
        z2, r2 = stations[i + 1]
        p0 = stations[max(i - 1, 0)]
        p3 = stations[min(i + 2, len(stations) - 1)]
        for k in range(subdiv):
            t = k / subdiv
            z = _catmull_rom(p0[0], z1, z2, p3[0], t)
            r = _catmull_rom(p0[1], r1, r2, p3[1], t)
            out.append((z, max(r, 1e-4)))
    out.append(stations[-1])
    return out


def cyl_patch(name, stations, theta0, theta1, mat=None, segs=24, thickness=0.014,
              smooth=True, subdiv=1):
    """圆柱面片（带厚度）—— 用于贴合躯干/裙面的围裙、胸衣等曲面布片。

    stations: [(z, r), ...] 自下而上；r 为该高度处的贴合半径。
    theta0/theta1: 周向角度（弧度），-Y 方向为 -π/2。
    thickness: 壳体厚度，背壳半径 = r - thickness（朝轴心收）。
               注意不能为 0 —— 两层壳半径相同时会永久 z-fighting。
    subdiv: 站位加密倍数（Catmull-Rom 平滑），消除折角硬边。
    """
    stations = _densify_stations(stations, subdiv)
    m = len(stations)
    verts, faces = [], []
    for i in range(m):
        z, r = stations[i]
        for j in range(segs + 1):
            th = theta0 + (theta1 - theta0) * j / segs
            verts.append((r * math.cos(th), r * math.sin(th), z))
    for i in range(m - 1):
        for j in range(segs):
            a = i * (segs + 1) + j
            b = (i + 1) * (segs + 1) + j
            faces.append((a, a + 1, b + 1, b))
    # 背面（沿法线偏移 —— 朝轴心收 thickness）
    off = len(verts)
    for i in range(m):
        z, r = stations[i]
        rb = max(r - thickness, 1e-4)
        for j in range(segs + 1):
            th = theta0 + (theta1 - theta0) * j / segs
            verts.append((rb * math.cos(th), rb * math.sin(th), z))
    for i in range(m - 1):
        for j in range(segs):
            a = off + i * (segs + 1) + j
            b = off + (i + 1) * (segs + 1) + j
            faces.append((a, b, b + 1, a + 1))
    # 四周封边
    for i in range(m - 1):
        for j in (0, segs):
            a = i * (segs + 1) + j
            b = (i + 1) * (segs + 1) + j
            faces.append((a, b, off + b, off + a))
    for i in (0, m - 1):
        for j in range(segs):
            a = i * (segs + 1) + j
            faces.append((a, off + a, off + a + 1, a + 1))
    return add_mesh(name, verts, faces, mat, smooth)


def lathe_wave(name, profile, mat=None, segs=96, amp=0.0, waves=8, phase=0.0,
               cap=True, smooth=True):
    """带周向波浪的回转体 —— 用于裙摆荷叶边（比珠串更接近真实花边）。"""
    n = len(profile)
    verts, faces = [], []
    for i in range(segs):
        th = TAU * i / segs
        ca, sa = math.cos(th), math.sin(th)
        k = 1.0 + amp * math.sin(waves * th + phase)
        for z, r in profile:
            verts.append((r * k * ca, r * k * sa, z))
    for i in range(segs):
        j = (i + 1) % segs
        for m in range(n - 1):
            faces.append((i * n + m, j * n + m, j * n + m + 1, i * n + m + 1))
    if cap:
        if profile[0][1] > 1e-6:
            ci = len(verts); verts.append((0, 0, profile[0][0]))
            for m in range(n):
                faces.append((ci, m, (m + 1) % n))
        if profile[-1][1] > 1e-6:
            ci = len(verts); verts.append((0, 0, profile[-1][0]))
            base = (segs - 1) * n
            for m in range(n):
                faces.append((ci, base + m, base + ((m + 1) % n)))
    return add_mesh(name, verts, faces, mat, smooth)


def tube(name, path, radii, mat=None, segs=16, cap=True, smooth=True):
    """沿 path 生成变半径管；path: [(x,y,z)], radii: [r,...]"""
    P = [Vector(p) for p in path]
    m = len(P)
    verts, faces = [], []
    up = Vector((0, 0, 1))
    for i, p in enumerate(P):
        if i == 0:
            tan = (P[1] - P[0])
        elif i == m - 1:
            tan = (P[-1] - P[-2])
        else:
            tan = (P[i + 1] - P[i - 1])
        tan.normalize()
        ref = up if abs(tan.dot(up)) < 0.94 else Vector((1, 0, 0))
        u = tan.cross(ref).normalized()
        v = tan.cross(u).normalized()
        r = radii[i]
        for j in range(segs):
            a = TAU * j / segs
            verts.append(tuple(p + u * (math.cos(a) * r) + v * (math.sin(a) * r)))
    for i in range(m - 1):
        for j in range(segs):
            k = (j + 1) % segs
            faces.append((i * segs + j, i * segs + k, (i + 1) * segs + k, (i + 1) * segs + j))
    if cap:
        for end, flip in ((0, True), (m - 1, False)):
            ci = len(verts); verts.append(tuple(P[end]))
            base = end * segs
            for j in range(segs):
                k = (j + 1) % segs
                f = (ci, base + k, base + j) if flip else (ci, base + j, base + k)
                faces.append(f)
    return add_mesh(name, verts, faces, mat, smooth)


def ribbon(name, path, widths, mat=None, normal=(0, -1, 0), segs=3, thick=0.012):
    """沿 path 生成有厚度的带状薄片（刘海 / 围裙 / 饰带）。"""
    P = [Vector(p) for p in path]
    m = len(P)
    verts, faces = [], []
    nrm = Vector(normal).normalized()
    for i, p in enumerate(P):
        if i == 0:
            tan = (P[1] - P[0])
        elif i == m - 1:
            tan = (P[-1] - P[-2])
        else:
            tan = (P[i + 1] - P[i - 1])
        tan.normalize()
        side = tan.cross(nrm)
        if side.length < 1e-6:
            side = tan.cross(Vector((1, 0, 0)))
        side.normalize()
        w = widths[i] * 0.5
        for s in (-1, 1):
            for d in (-1, 1):
                verts.append(tuple(p + side * (s * w) + nrm * (d * thick)))
    for i in range(m - 1):
        a = i * 4
        b = (i + 1) * 4
        for j in range(4):
            k = (j + 1) % 4
            faces.append((a + j, a + k, b + k, b + j))
    faces.append((0, 1, 3, 2))
    faces.append(((m - 1) * 4 + 0, (m - 1) * 4 + 2, (m - 1) * 4 + 3, (m - 1) * 4 + 1))
    return add_mesh(name, verts, faces, mat, smooth=False)


def bead_arc(name, path, radius, mat=None, segs=12, rings=8, squash=1.0):
    """沿 path 排布一串球 —— 荷叶边 / 花边。"""
    objs = []
    for i, p in enumerate(path):
        objs.append(sphere(f"{name}_{i:02d}", p, (radius, radius, radius * squash),
                           mat, segs=segs, rings=rings))
    return objs


def bow(name, center, size, mat, depth=0.42, tilt=0.0, axis="y"):
    """蝴蝶结：2 个环 + 2 条带 + 中间结。"""
    cx, cy, cz = center
    s = size
    parts = []
    sign = 1 if tilt >= 0 else -1
    for side in (-1, 1):
        cxx = cx + side * s * 0.78
        parts.append(sphere(f"{name}_loop{'L' if side < 0 else 'R'}",
                            (cxx, cy, cz), (s * 0.62, s * 0.30 * depth, s * 0.46), mat))
    parts.append(sphere(f"{name}_knot", (cx, cy - s * 0.04, cz), (s * 0.30, s * 0.26, s * 0.30), mat))
    for side in (-1, 1):
        parts.append(sphere(f"{name}_tail{'L' if side < 0 else 'R'}",
                            (cx + side * s * 0.30, cy - s * 0.06, cz - s * 0.62),
                            (s * 0.20, s * 0.14, s * 0.52), mat))
    return parts


def join_parts(objs, name):
    """把一组 object 合成一个（保持材质分槽）。"""
    objs = [o for o in objs if o and o.type == "MESH"]
    if not objs:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    return ob
