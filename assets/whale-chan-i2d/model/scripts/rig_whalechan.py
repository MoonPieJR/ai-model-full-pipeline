#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rig_whalechan.py —— 给鲸鱼娘白模绑骨（本地，全免费）

流程：
  导入 GLB → 朝向矫正 + 归一化 → 删碎屑 → 建骨架 → 自动权重
  → 存 .blend / 导出 FBX+GLB → 渲染 bind pose 与测试 pose

骨架关键点由 rig_params.json 提供（按总高 H 的比例），方便迭代时只改数字。

用法：
  python rig_whalechan.py <in.glb> <outdir> [--params rig_params.json] [--no-render]
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp
import rig_weights as rw

# ── Mixamo 兼容骨架定义 ────────────────────────────────────
# (骨骼名, 父级, 头位置系数, 尾位置系数)  系数 = (x, y, z) × H
BONES = [
    ("mixamorig:Hips",        None,          (0.000, 0.000, 0.470), (0.000, 0.000, 0.530)),
    ("mixamorig:Spine",       "mixamorig:Hips",        (0.000, 0.000, 0.530), (0.000, 0.000, 0.580)),
    ("mixamorig:Spine1",      "mixamorig:Spine",       (0.000, 0.000, 0.580), (0.000, 0.000, 0.640)),
    ("mixamorig:Spine2",      "mixamorig:Spine1",      (0.000, 0.000, 0.640), (0.000, 0.000, 0.700)),
    ("mixamorig:Neck",        "mixamorig:Spine2",      (0.000, 0.000, 0.700), (0.000, 0.000, 0.790)),
    ("mixamorig:Head",        "mixamorig:Neck",        (0.000, 0.000, 0.790), (0.000, 0.000, 0.990)),

    ("mixamorig:LeftShoulder", "mixamorig:Spine2",     (-0.040, 0.000, 0.690), (-0.110, 0.000, 0.705)),
    ("mixamorig:LeftArm",      "mixamorig:LeftShoulder", (-0.110, 0.000, 0.705), (-0.215, 0.000, 0.620)),
    ("mixamorig:LeftForeArm",  "mixamorig:LeftArm",      (-0.215, 0.000, 0.620), (-0.300, 0.000, 0.545)),
    ("mixamorig:LeftHand",     "mixamorig:LeftForeArm",  (-0.300, 0.000, 0.545), (-0.350, 0.000, 0.500)),

    ("mixamorig:RightShoulder", "mixamorig:Spine2",    (0.040, 0.000, 0.690), (0.110, 0.000, 0.705)),
    ("mixamorig:RightArm",      "mixamorig:RightShoulder", (0.110, 0.000, 0.705), (0.215, 0.000, 0.620)),
    ("mixamorig:RightForeArm",  "mixamorig:RightArm",      (0.215, 0.000, 0.620), (0.300, 0.000, 0.545)),
    ("mixamorig:RightHand",     "mixamorig:RightForeArm",  (0.300, 0.000, 0.545), (0.350, 0.000, 0.500)),

    ("mixamorig:LeftUpLeg",   "mixamorig:Hips",        (-0.055, 0.000, 0.470), (-0.060, 0.000, 0.290)),
    ("mixamorig:LeftLeg",     "mixamorig:LeftUpLeg",   (-0.060, 0.000, 0.290), (-0.065, 0.000, 0.115)),
    ("mixamorig:LeftFoot",    "mixamorig:LeftLeg",     (-0.065, 0.000, 0.115), (-0.065, -0.070, 0.030)),
    ("mixamorig:LeftToeBase", "mixamorig:LeftFoot",    (-0.065, -0.070, 0.030), (-0.065, -0.115, 0.020)),

    # 尾巴：TripoSR 重建出的鲸鱼尾没有 Mixamo 对应骨，自定义 3 节
    ("WhaleTail_1", "mixamorig:Hips",        (0.000, -0.040, 0.450), (-0.180, -0.090, 0.430)),
    ("WhaleTail_2", "WhaleTail_1",            (-0.180, -0.090, 0.430), (-0.400, -0.140, 0.400)),
    ("WhaleTail_3", "WhaleTail_2",            (-0.400, -0.140, 0.400), (-0.620, -0.190, 0.380)),

    ("mixamorig:RightUpLeg",  "mixamorig:Hips",        (0.055, 0.000, 0.470), (0.060, 0.000, 0.290)),
    ("mixamorig:RightLeg",    "mixamorig:RightUpLeg",  (0.060, 0.000, 0.290), (0.065, 0.000, 0.115)),
    ("mixamorig:RightFoot",   "mixamorig:RightLeg",    (0.065, 0.000, 0.115), (0.065, -0.070, 0.030)),
    ("mixamorig:RightToeBase", "mixamorig:RightFoot",  (0.065, -0.070, 0.030), (0.065, -0.115, 0.020)),
]


def clean_fragments(meshes, min_faces=2000):
    """删掉小于 min_faces 的碎屑连通分量（TripoSR 会掉渣）。"""
    import bmesh
    removed = 0
    for ob in meshes:
        if ob.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.verts.ensure_lookup_table()
        junk = [v for v in bm.verts if len(v.link_faces) == 0]
        if junk:
            bmesh.ops.delete(bm, geom=junk, context="VERTS")
            removed += len(junk)
        bm.to_mesh(ob.data)
        bm.free()
    print(f"  [clean] 删除孤立顶点 {removed}")


def detect_center_x(allv, H, base_z):
    """检测模型中轴的 X 坐标。

    用头部层（z/H ∈ [0.84, 0.96]）的 x 范围中点 —— 那一段只有头和头发，
    不像裙摆/尾巴那样把包围盒撑歪。模型不一定以 x=0 为中心，
    骨架按 x=0 摆会导致整体偏移 → bone heat 找不到解。
    """
    z0 = base_z + H * 0.84
    z1 = base_z + H * 0.96
    sel = (allv[:, 2] >= z0) & (allv[:, 2] <= z1)
    if sel.sum() < 50:
        return 0.0
    p = allv[sel]
    return float((p[:, 0].min() + p[:, 0].max()) * 0.5)


def build_armature(name, H, base_z, params, center_x=0.0):
    """按系数建骨架。params 可覆盖 BONES 里的位置。

    系数 x 相对中轴 center_x，z 相对底面 base_z。
    """
    arm_data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    made = {}
    for bname, parent, head_c, tail_c in BONES:
        h = Vector(params.get(bname, head_c)) * H + Vector((center_x, 0, base_z))
        t = Vector(params.get(bname + "|tail", tail_c)) * H + Vector((center_x, 0, base_z))
        eb = arm_data.edit_bones.new(bname)
        eb.head = h
        eb.tail = t
        if parent:
            eb.parent = made[parent]
            eb.use_connect = (eb.head - made[parent].tail).length < 1e-4
        made[bname] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"  [rig] 骨骼 {len(arm_data.bones)} 根，父级 {len(arm_data.bones)}")
    return arm


def auto_weights(meshes, arm, power=6.0, H=1.0, base_z=0.0, cx=0.0):
    """自动权重。

    ⚠ Blender 内置的 bone heat（ARMATURE_AUTO）在 29.7 万顶点的密集网格上
      会**静默失败**：顶点组建好了、Armature 修改器也加了，但每个顶点的权重
      全是 0（实测「有权重的顶点 0/297462」）。
      所以改成自己算：点到骨骼线段的距离 → 高次反比 → 归一化 → 前 4 根。
    """
    import numpy as np
    bpy.context.view_layer.update()

    # 1) 先让 mesh parent 到 armature，并建好顶点组
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    try:
        bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
    except Exception as e:
        print(f"  [rig] parent_set 失败: {e}")
    for o in meshes:
        o.select_set(False)

    # 2) 取世界坐标顶点 + 骨骼线段
    allv, allf, bone_names, segs = [], [], [], []
    off = 0
    for ob in meshes:
        mw = np.array(ob.matrix_world)
        co = np.empty(len(ob.data.vertices) * 3, dtype=np.float32)
        ob.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        allv.append(co @ mw[:3, :3].T + mw[:3, 3])
        idx = np.empty(len(ob.data.polygons) * 4, dtype=np.int32)
        ob.data.polygons.foreach_get("vertices", idx)
        idx = idx.reshape(-1, 4)[:, :3] + off
        allf.append(idx)
        off += len(co)
    verts = np.concatenate(allv)
    faces = np.concatenate(allf)

    for b in arm.data.bones:
        bone_names.append(b.name)
        segs.append((arm.matrix_world @ b.head_local,
                     arm.matrix_world @ b.tail_local))
    # 只对有 deform 的骨骼算权重
    keep = [i for i, b in enumerate(arm.data.bones) if b.use_deform]
    segs = [segs[i] for i in keep]
    bnames = [bone_names[i] for i in keep]

    print(f"  [rig] 计算权重：{len(verts):,} 顶点 × {len(segs)} 骨骼")
    idx, w = rw.compute_weights(verts, segs, power=power)

    # 裙摆去腿骨：裙子下面藏着腿，抬腿时裙摆跟着腿甩出去会很难看。
    # 规则：z 落在 [skirt_lo, skirt_hi] 的顶点（裙面区），
    #       把腿骨（UpLeg/Leg/Foot）的权重按比例转移给 Hips。
    skirt_lo = base_z + H * 0.30
    skirt_hi = base_z + H * 0.47
    leg_names = ["mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot",
                 "mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot"]
    leg_ids = [bnames.index(n) for n in leg_names if n in bnames]
    hip_id = bnames.index("mixamorig:Hips") if "mixamorig:Hips" in bnames else None
    if leg_ids and hip_id is not None:
        zs = verts[:, 2]
        in_skirt = (zs >= skirt_lo) & (zs <= skirt_hi)
        # 只有远离中轴的才是裙面（中间是腿）
        away = np.abs(verts[:, 0] - cx) > H * 0.055
        mask = in_skirt & away
        moved = 0
        if mask.any():
            li = np.array(leg_ids)
            lw = w[mask][:, li].sum(axis=1)
            w[np.ix_(np.where(mask)[0], li)] *= 0.0
            w[mask, hip_id] += lw
            moved = int(mask.sum())
        print(f"  [rig] 裙摆去腿骨：{moved:,} 顶点的腿权重 → Hips")

    # 3) 写回（顶点组名 = 骨骼名）
    base = 0
    total = 0
    for oi, ob in enumerate(meshes):
        n = len(ob.data.vertices)
        sl = slice(base, base + n)
        # 建立 骨骼名 → 本地 vertex group
        for bn in bnames:
            if bn not in ob.vertex_groups:
                ob.vertex_groups.new(name=bn)
        remap = np.array([ob.vertex_groups[bn].index for bn in bnames],
                         dtype=np.int32)
        total += rw.write_to_vertex_groups(
            ob, remap[idx[sl]], w[sl])
        base += n
    print(f"  [rig] 权重写入完成（{total} 次批量调用）")

    # 4) 校验
    for ob in meshes:
        grp = [v.groups for v in ob.data.vertices]
        nw = sum(1 for g in grp if any(x.weight > 1e-4 for x in g))
        print(f"  [rig] {ob.name}: 有权重顶点 {nw:,}/{len(grp):,} "
              f"({100*nw/max(len(grp),1):.1f}%)")
    return True


def pose_and_render(arm, pose_defs, outdir, res=512, samples=32):
    """摆几个姿势渲染，验证骨架是否真的带动了模型。"""
    sc = bpy.context.scene
    bp.setup_render(samples, res, transparent=True)
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for label, rot in pose_defs.items():
        for pb in arm.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (0, 0, 0)
        for bname, euler in rot.items():
            if bname in arm.pose.bones:
                arm.pose.bones[bname].rotation_euler = euler
        bpy.context.view_layer.update()
        p = os.path.join(outdir, f"pose_{label}.png")
        bp.render_to(p)
        paths.append(p)
    return paths


def main():
    glb = sys.argv[1]
    outdir = sys.argv[2]
    pfile = None
    if "--params" in sys.argv:
        pfile = sys.argv[sys.argv.index("--params") + 1]
    do_render = "--no-render" not in sys.argv
    params = json.load(open(pfile)) if pfile else {}

    os.makedirs(outdir, exist_ok=True)
    print(f"▸ 导入 {glb}")
    bpy.ops.import_scene.gltf(filepath=glb)
    # ⚠ 清掉导入前场景里的残留对象（Blender 默认的 Cube 会在原点，
    #   包围盒被它污染 → 归一化后「脚底」算错、骨架整体偏移）。
    for o in list(bpy.context.scene.objects):
        nm = o.name
        if o.type == "MESH" and nm not in {"whale-chan-i2d"}:
            bpy.data.objects.remove(o, do_unlink=True)
            print(f"  [clean] 移除残留对象 {nm}")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    print(f"  [mesh] {len(meshes)} 个网格对象")
    if not meshes:
        sys.exit("✗ 没有网格")

    print("▸ 朝向矫正 + 归一化")
    bp.orient_up(meshes)
    bp.normalize(meshes, target_h=2.87)
    clean_fragments(meshes)

    bpy.context.view_layer.update()
    lo, hi = bp.model_bounds(meshes)
    H = hi[2] - lo[2]
    base_z = lo[2]
    print(f"  [bbox] X {hi[0]-lo[0]:.3f}  Y {hi[1]-lo[1]:.3f}  Z {H:.3f}")

    print("▸ 分层剖面（Blender 坐标，用于核对骨架位置）")
    import numpy as np
    allv = []
    for ob in meshes:
        mw = ob.matrix_world
        co = np.empty(len(ob.data.vertices) * 3, dtype=np.float32)
        ob.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(mw)
        allv.append(co @ M[:3, :3].T + M[:3, 3])
    allv = np.concatenate(allv)
    print(f"   {'z/H':>6} {'宽X':>7} {'深Y':>7} {'顶点数':>8}")
    for i in range(20):
        z0 = base_z + H * i / 20
        z1 = base_z + H * (i + 1) / 20
        sel = (allv[:, 2] >= z0) & (allv[:, 2] < z1)
        if sel.sum() < 5:
            print(f"   {i/20:6.2f} {'—':>7} {'—':>7} {sel.sum():8,}   (空层)")
            continue
        p = allv[sel]
        print(f"   {i/20:6.2f} {p[:,0].max()-p[:,0].min():7.3f} "
              f"{p[:,1].max()-p[:,1].min():7.3f} {sel.sum():8,}   "
              f"x[{p[:,0].min():+.2f},{p[:,0].max():+.2f}] y[{p[:,1].min():+.2f},{p[:,1].max():+.2f}]")

    cx = detect_center_x(allv, H, base_z)
    print(f"▸ 建骨架（中轴 x = {cx:+.3f}）")
    arm = build_armature("WhaleChan_Rig", H, base_z, params, cx)
    print("▸ 自动权重")
    auto_weights(meshes, arm, H=H, base_z=base_z, cx=cx)

    blend = os.path.join(outdir, "whale-chan-rigged.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print(f"  ✓ {blend}  {os.path.getsize(blend):,} bytes")

    print("▸ 导出")
    for fmt, path in (("FBX", os.path.join(outdir, "whale-chan-rigged.fbx")),
                      ("GLB", os.path.join(outdir, "whale-chan-rigged.glb"))):
        try:
            if fmt == "FBX":
                bpy.ops.export_scene.fbx(
                    filepath=path, use_mesh_modifiers=True, add_leaf_bones=False,
                    bake_anim=False, path_mode="COPY",
                    object_types={"ARMATURE", "MESH"})
            else:
                bpy.ops.export_scene.gltf(
                    filepath=path, export_format="GLB", export_animations=True,
                    export_skins=True, export_def_bones=True)
            print(f"  ✓ {path}  {os.path.getsize(path):,} bytes")
        except Exception as e:
            print(f"  ! {fmt} 导出失败: {e}")

    if do_render:
        print("▸ 渲染验证")
        coll = bpy.context.scene.collection
        cam = bp.setup_camera(coll, dist=5.6, z=1.44, lens=62)
        bp.setup_lights(coll)
        bp.setup_world(0.30)
        bp.frame_model(cam, meshes + [arm], 0)
        poses = {
            "bind": {},
            "leglift": {"mixamorig:LeftUpLeg": (0, -0.9, 0),
                        "mixamorig:RightUpLeg": (0, -0.5, 0),
                        "mixamorig:LeftLeg": (0, 0.7, 0)},
            "armwave": {"mixamorig:LeftArm": (0, 0, -1.1),
                        "mixamorig:RightArm": (0, 0, 1.1),
                        "mixamorig:LeftForeArm": (0, -0.8, 0),
                        "mixamorig:RightForeArm": (0, 0.8, 0)},
            "lean": {"mixamorig:Spine": (0.25, 0, 0),
                     "mixamorig:Spine1": (0.2, 0, 0),
                     "mixamorig:Neck": (0.15, 0, 0)},
        }
        pose_and_render(arm, poses, os.path.join(outdir, "poses"))
        print("  ✓ pose 渲染完成")

    print("\n✓ 全部完成")


if __name__ == "__main__":
    main()
