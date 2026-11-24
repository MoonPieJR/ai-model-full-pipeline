"""TripoSR 产物的 Blender 修整 + 出图管线。

对应 FiniYang 教程第 ⑥⑦ 步：
  ⑥ 保留原始 GLB → 另存一份工程 → 渲染多角度找问题 → 针对缺陷修一版
  ⑦ 高清 PNG + 转台 MP4（8 秒 / 30fps / 匀速一圈）

设计原则：
  - 原始网格与材质完整保留在独立集合里，随时可回退
  - 修整版放在独立集合 + 独立材质，方便开关对比
"""
import math
import os
import sys

import bpy
from mathutils import Vector

# ────────────────────────── 场景工具 ──────────────────────────


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                  bpy.data.cameras, bpy.data.lights, bpy.data.actions):
        for b in list(block):
            if b.users == 0:
                block.remove(b)


def get_coll(name):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def link_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# ────────────────────────── 导入与修整 ──────────────────────────


def import_glb(path, coll_name):
    """导入 GLB，返回网格对象列表。"""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    coll = get_coll(coll_name)
    for o in new:
        link_to(o, coll)
    return new, coll


def model_bounds(objs):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def orient_up(objs):
    """把模型摆成站姿：最长轴转到 +Z。

    TripoSR 内部是 z-up，但导出 glTF → 再被 Blender 导入后，
    实测人物是横躺的（最长轴在 X）。这里按包围盒自动校正：
    找到最长轴，把它转到 Z。
    """
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    spans = {"X": hi[0] - lo[0], "Y": hi[1] - lo[1], "Z": hi[2] - lo[2]}
    longest = max(spans, key=spans.get)
    if longest == "Z":
        print(f"  [orient] 最长轴已是 Z {spans}  无需旋转")
        return 0.0
    # 绕 Y 轴 -90°: +X → +Z；绕 X 轴 +90°: +Y → +Z
    if longest == "X":
        euler = (0.0, math.radians(-90.0), 0.0)
    else:
        euler = (math.radians(90.0), 0.0, 0.0)
    pivot = bpy.data.objects.new("Orient_Pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    for o in objs:
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()
    pivot.rotation_euler = euler
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    print(f"  [orient] 最长轴 {longest} {spans}  → 旋转 {euler}  "
          f"新尺寸 {round(hi[0]-lo[0],3)}x{round(hi[1]-lo[1],3)}x{round(hi[2]-lo[2],3)}")
    return longest


# 实测常量：TripoSR(internal z-up) → glTF(Y-up) → Blender(Z-up) 两次轴变换后，
# 人物正面朝世界 -Y（相机置于 -Y，即 azim=0 拍到正面）。
# 依据：azim=0 的渲染能看到脸颊腮红、围裙白色梯形、鲸尾在画面左侧。
# 曾尝试用「头部暗色顶点分布」自动探测，但 TripoSR 从单张正面图重建时，
# 背面完全是推测的、脸部又被头发遮挡，颜色启发式判反了 —— 固定为实测值。
FACE_AZIM = 0


def detect_face_azimuth(objs, head_frac=0.28, dark_thresh=0.34):
    """探测角色正面所在的方位角（返回 0 或 180）。

    依据：脸部有眼睛/嘴等暗色细节，后脑只有头发。
    取模型上部（头部）区域的暗色顶点，统计它们在世界 Y 方向的均值：
    偏 +Y → 正面朝 +Y（相机需放在 +Y，即 azim=180）。
    """
    import numpy as np
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    z_head = hi[2] - (hi[2] - lo[2]) * head_frac
    ys = []
    for o in objs:
        if o.type != "MESH":
            continue
        me = o.data
        attr = me.attributes.get("Color") or me.attributes.get("Col")
        if attr is None:
            continue
        # glTF 导出的 COLOR_0 在 Blender 里是 CORNER domain（每角点一条），
        # 需要按 loop 的 vertex_index 聚合回顶点。
        n_c = len(attr.data)
        if getattr(attr, "data_type", "FLOAT_COLOR") == "BYTE_COLOR":
            buf = np.empty(n_c * 4, dtype=np.uint8)
            attr.data.foreach_get("color", buf)
            ccols = buf.reshape(n_c, 4)[:, :3].astype(np.float32) / 255.0
        else:
            buf = np.empty(n_c * 4, dtype=np.float32)
            attr.data.foreach_get("color", buf)
            ccols = buf.reshape(n_c, 4)[:, :3]

        n_v = len(me.vertices)
        if n_c == n_v:
            vcols = ccols
        else:
            acc = np.zeros((n_v, 3), np.float32)
            cnt = np.zeros(n_v, np.float32)
            loop_v = np.empty(len(me.loops), np.int32)
            me.loops.foreach_get("vertex_index", loop_v)
            np.add.at(acc, loop_v, ccols)
            np.add.at(cnt, loop_v, 1.0)
            vcols = acc / np.maximum(cnt, 1.0)[:, None]

        lum = vcols.mean(axis=1)
        mw = np.array([list(o.matrix_world @ v.co) for v in me.vertices])
        head = mw[:, 2] > z_head
        dark = head & (lum < dark_thresh)
        if dark.any():
            ys.append(mw[dark, 1])
    if not ys:
        print("  [face] 无顶点色/无暗色顶点，默认 azim=180")
        return 180
    if ys:
        mean_y = float(np.concatenate(ys).mean())
        print(f"  [face] 头部暗色顶点世界 Y 均值 {mean_y:+.4f}（仅作诊断，"
              f"实际采用实测常量 azim={FACE_AZIM}）")
    else:
        print(f"  [face] 采用实测常量 azim={FACE_AZIM}")
    return FACE_AZIM


def normalize(objs, target_h=2.87):
    """把模型缩放到与参数化版一致的高度（2.87 BU），脚底落在 Z=0。

    注意：改 scale/location 后必须 view_layer.update()，
    否则 bound_box 读到的还是旧矩阵（缩放看起来"没生效"）。
    """
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    h = hi[2] - lo[2]
    if h <= 0:
        return 1.0
    s = target_h / h
    for o in objs:
        o.scale = (o.scale.x * s, o.scale.y * s, o.scale.z * s)
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    dz = -lo[2]
    # 平移必须作用在「顶层父级」上：子对象一旦被 orient pivot 旋转过，
    # 它的局部 Z 已经不是世界 Z，直接改 o.location.z 会平移到错误的方向。
    roots = {o.parent if o.parent is not None else o for o in objs}
    for r in roots:
        r.location.z += dz
    bpy.context.view_layer.update()
    return s


def laplacian_smooth(objs, factor=0.25, iterations=2):
    """用 numpy + scipy 做顶点拉普拉斯平滑（去碎面）。

    不用 Blender 的 LaplacianSmooth modifier —— 在 3GB 内存的沙箱里，
    5 万顶点的网格上它会直接段错误。
    """
    import numpy as np

    for o in objs:
        if o.type != "MESH":
            continue
        me = o.data
        n = len(me.vertices)
        if n == 0 or len(me.edges) == 0:
            continue
        ev = np.empty(len(me.edges) * 2, np.int32)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)

        coords = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", coords)
        coords = coords.reshape(n, 3).astype(np.float64)

        for _ in range(iterations):
            # 一环邻域均值（纯 numpy，不依赖 scipy）
            acc = np.zeros((n, 3), np.float64)
            cnt = np.zeros(n, np.float64)
            np.add.at(acc, ev[:, 0], coords[ev[:, 1]])
            np.add.at(acc, ev[:, 1], coords[ev[:, 0]])
            np.add.at(cnt, ev[:, 0], 1.0)
            np.add.at(cnt, ev[:, 1], 1.0)
            avg = acc / np.maximum(cnt, 1.0)[:, None]
            coords = coords + factor * (avg - coords)

        me.vertices.foreach_set("co", coords.astype(np.float32).ravel())
        me.update()
    bpy.context.view_layer.update()


def build_fixed_material(objs, name="WhaleChan_Fixed", roughness=0.62,
                         color_boost=1.08, saturation=1.12):
    """顶点色 → Principled BSDF，并做一点反光/饱和度修正。

    TripoSR 输出的是顶点色（无 UV 贴图），导入 Blender 后是
    Color Attribute 节点。这里重建一个受控的 PBR 材质：
      - Base Color 取自顶点色，做饱和度/亮度微调
      - 低粗糙度给树脂手办一点高光
      - 加一层轻微的 sheen 模拟手办表面的绒感

    若网格没有顶点色层（如 PBR 材质的 GLB），则退回原材质，只调粗糙度。
    """
    has_col = any(
        o.type == "MESH" and any(a.name in ("Color", "Col") for a in o.data.attributes)
        for o in objs)
    if not has_col:
        for o in objs:
            if o.type != "MESH":
                continue
            for m in o.data.materials:
                if not m.use_nodes:
                    continue
                bsdf = next((n for n in m.node_tree.nodes
                             if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf:
                    bsdf.inputs["Roughness"].default_value = roughness
        print("  [material] 无顶点色层，沿用原 PBR 材质并调整粗糙度")
        return None

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (380, 0)
    bsdf.inputs["Roughness"].default_value = roughness
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.45
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.45

    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Color" if "Color" in [a.name for a in objs[0].data.attributes] else "Col"
    attr.location = (-260, 0)

    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.location = (-60, 0)
    hsv.inputs["Saturation"].default_value = saturation
    hsv.inputs["Value"].default_value = color_boost

    nt.links.new(attr.outputs["Color"], hsv.inputs["Color"])
    nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def apply_material(objs, mat):
    for o in objs:
        if o.type != "MESH":
            continue
        o.data.materials.clear()
        o.data.materials.append(mat)


# ────────────────────────── 灯光与相机 ──────────────────────────

KEY = (3.2, -4.4, 5.0)
FILL = (-4.6, -2.4, 2.4)
RIM = (-1.6, 5.0, 4.2)


def setup_world(strength=0.42, color=(0.92, 0.90, 0.87)):
    sc = bpy.context.scene
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (color[0], color[1], color[2], 1.0)
        bg.inputs[1].default_value = strength


def setup_lights(coll):
    specs = [("Key", "AREA", KEY, 120, 4.0),
             ("Fill", "AREA", FILL, 40, 5.0),
             ("Rim", "AREA", RIM, 90, 3.0)]
    objs = []
    for name, kind, loc, power, size in specs:
        ld = bpy.data.lights.new(f"L_{name}", type=kind)
        ld.energy = power
        ld.size = size
        ob = bpy.data.objects.new(f"L_{name}", ld)
        ob.location = loc
        link_to(ob, coll)
        look_at(ob, (0, 0, 1.45))
        objs.append(ob)
    return objs


def setup_camera(coll, dist=5.6, z=1.44, lens=62):
    cd = bpy.data.cameras.new("Cam")
    cd.lens = lens
    cam = bpy.data.objects.new("Cam", cd)
    link_to(cam, coll)
    bpy.context.scene.camera = cam
    return cam


def frame_model(cam, objs, azim_deg, elev_deg=6.0, fill=0.80, target_z=None):
    """按方位角放相机，按 FOV 自动算距离，让角色占画面高度约 fill。

    距离由 sensor/lens 推出的水平 FOV 决定：
        half_fov = atan(sensor / (2 * lens))
        d = radius / tan(half_fov) / fill
    """
    bpy.context.view_layer.update()
    lo, hi = model_bounds(objs)
    if target_z is None:
        target_z = (lo[2] + hi[2]) / 2
    center = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, target_z))
    radius = max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2
    cd = cam.data
    sensor = cd.sensor_width
    half_fov = math.atan(sensor / (2.0 * cd.lens))
    d = radius / math.tan(half_fov) / max(fill, 0.05)
    a = math.radians(azim_deg)
    e = math.radians(elev_deg)
    cam.location = center + Vector((math.sin(a) * math.cos(e) * d,
                                    -math.cos(a) * math.cos(e) * d,
                                    math.sin(e) * d))
    look_at(cam, center)
    return center, radius


# ────────────────────────── 渲染 ──────────────────────────


def setup_render(samples=64, res=1024, denoise=True, transparent=False):
    """denoise=False 用于转台动画：
    本沙箱 2 核无 AVX，OpenImageDenoise 每帧重新加载内核要 30~50 秒，
    144 帧会被 denoiser 拖到 2 小时以上。改用更多采样换速度。"""
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = denoise
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = transparent
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print(f"  Saved: {path}", flush=True)


def render_views(outdir, cam, objs, views, samples=64, res=1024, transparent=False):
    setup_render(samples, res, transparent=transparent)
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for name, azim in views:
        frame_model(cam, objs, azim)
        p = os.path.join(outdir, f"{name}.png")
        render_to(p)
        paths.append(p)
    return paths


def render_turntable(outdir, cam, objs, name="turntable", seconds=8, fps=30,
                     res=1080, samples=32, transparent=False):
    """转台视频：角色匀速旋转一圈，相机灯光固定。"""
    sc = bpy.context.scene
    setup_render(samples, res, denoise=False, transparent=transparent)
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    frames = seconds * fps
    sc.frame_start = 1
    sc.frame_end = frames
    sc.render.fps = fps
    sc.render.image_settings.file_format = "FFMPEG"
    sc.render.ffmpeg.format = "MPEG4"
    sc.render.ffmpeg.codec = "H264"
    sc.render.ffmpeg.constant_rate_factor = "HIGH"
    sc.render.ffmpeg.ffmpeg_preset = "GOOD"
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{name}.mp4")
    sc.render.filepath = path

    # 旋转组：把模型挂到一个空物体下，绕 Z 轴匀速转
    pivot = bpy.data.objects.new("Turntable_Pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.location = (0, 0, 0)
    # 对象可能已经挂在 orient pivot 下（带旋转），把根节点整体挂到转台 pivot
    roots = {o.parent if o.parent is not None else o for o in objs}
    for r in roots:
        r.parent = pivot
        r.matrix_parent_inverse = pivot.matrix_world.inverted()

    frame_model(cam, objs, 0)
    for f in range(1, frames + 1):
        pivot.rotation_euler = (0, 0, 2 * math.pi * (f - 1) / frames)
        sc.frame_set(f)
    sc.frame_set(1)
    pivot.rotation_euler = (0, 0, 0)
    bpy.ops.render.render(animation=True)
    print(f"  Saved: {path}", flush=True)
    return path
