#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
optimize_white.py —— 鲸鱼娘白模优化（几何层，不含贴图/骨骼）

输入：TripoSR 直出的裸网格
输出：
  white-high.glb/.fbx/.obj   清理+平滑后的原拓扑高模（细节全）
  white-voxel*.glb           Voxel 重网格（均匀拓扑，脸部有面，绑骨/雕刻友好）
  white-quad.glb             Quad 四边面重网格（最适合后续手工建模）
  white-clean.blend          干净工程（Z-up、脚底在原点、已归一化）
  renders/white_compare.png  各版本对比渲染

用法：
  python optimize_white.py <in.glb> <outdir> [--voxels 0.014,0.020]
"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp

TARGET_H = 2.87


# ── 1. 删碎屑 ────────────────────────────────────────────────
def drop_fragments(ob, min_faces=1000):
    """按连通分量拆开，删掉小的，再合并回来。"""
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.mesh.separate(type="LOOSE")
    parts = [o for o in bpy.context.scene.objects
             if o.type == "MESH" and o.name.startswith(ob.name)]
    junk = [o for o in parts if len(o.data.polygons) < min_faces]
    kept = [o for o in parts if len(o.data.polygons) >= min_faces]
    for o in junk:
        print(f"  [clean] 丢弃碎屑 {o.name}  {len(o.data.polygons)} 面")
        bpy.data.objects.remove(o, do_unlink=True)
    if not kept:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in kept:
        o.select_set(True)
    bpy.context.view_layer.objects.active = kept[0]
    bpy.ops.object.join()
    res = bpy.context.view_layer.objects.active
    res.name = ob.name
    print(f"  [clean] 保留 {len(kept)} 块，合并为 {len(res.data.polygons):,} 面")
    return res


# ── 2. Laplacian 平滑（纯 numpy，一环邻域均值）─────────────────
def laplacian_smooth(ob, iters=2, factor=0.5):
    """Bpy 的 LAPLACIANSMOOTH modifier 会段错误，改用 numpy 自己算。"""
    me = ob.data
    nv = len(me.vertices)
    co = np.empty(nv * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    # 建邻接
    edges = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)
    deg = np.zeros(nv, dtype=np.int32)
    np.add.at(deg, edges[:, 0], 1)
    np.add.at(deg, edges[:, 1], 1)
    for _ in range(iters):
        acc = np.zeros_like(co)
        for a, b in ((edges[:, 0], edges[:, 1]), (edges[:, 1], edges[:, 0])):
            np.add.at(acc, a, co[b])
        avg = acc / np.maximum(deg[:, None], 1)
        co = co + (avg - co) * factor
    co = co.astype(np.float32)
    me.vertices.foreach_set("co", co.ravel())
    me.update()
    print(f"  [smooth] Laplacian ×{iters}  factor={factor}")


# ── 3. 重网格 ────────────────────────────────────────────────
def voxel_remesh(ob, voxel_size, smooth=True):
    """Voxel 重网格：拓扑均匀、抹掉发丝细节 → 脸部才有面。"""
    dup = ob.copy()
    dup.data = ob.data.copy()
    bpy.context.scene.collection.objects.link(dup)
    dup.name = ob.name + "_vox"
    bpy.ops.object.select_all(action="DESELECT")
    dup.select_set(True)
    bpy.context.view_layer.objects.active = dup
    m = dup.modifiers.new("Remesh", "REMESH")
    m.mode = "VOXEL"
    m.voxel_size = voxel_size
    m.use_smooth_shade = True
    if smooth:
        s = dup.modifiers.new("Smooth", "SMOOTH")
        s.factor = 0.6
        s.iterations = 3
    bpy.ops.object.modifier_apply(modifier=m.name)
    if smooth:
        bpy.ops.object.modifier_apply(modifier=s.name)
    print(f"  [remesh] voxel={voxel_size}  →  {len(dup.data.vertices):,} 顶点 "
          f"{len(dup.data.polygons):,} 面")
    return dup


def quad_remesh(ob, target_faces=None):
    """Quad 四边面重网格：最适合后续手工建模/雕刻/绑骨。"""
    dup = ob.copy()
    dup.data = ob.data.copy()
    bpy.context.scene.collection.objects.link(dup)
    dup.name = ob.name + "_quad"
    bpy.ops.object.select_all(action="DESELECT")
    dup.select_set(True)
    bpy.context.view_layer.objects.active = dup
    m = dup.modifiers.new("QuadRemesh", "REMESH")
    m.mode = "SHARP"
    # Blender 4.x 的 SHARP 模式用 octree_depth + scale，没有 target_faces
    m.octree_depth = 7
    m.scale = 0.99
    m.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=m.name)
    print(f"  [remesh] quad  →  {len(dup.data.vertices):,} 顶点 "
          f"{len(dup.data.polygons):,} 面")
    return dup


def tri_count(ob):
    return sum(max(len(p.vertices) - 2, 0) for p in ob.data.polygons)


def stats(ob):
    co = np.empty(len(ob.data.vertices) * 3, dtype=np.float32)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(ob.matrix_world)
    w = co @ mw[:3, :3].T + mw[:3, 3]
    e = w.max(axis=0) - w.min(axis=0)
    return {"verts": len(ob.data.vertices), "faces": len(ob.data.polygons),
            "tris": tri_count(ob), "size": [round(float(x), 3) for x in e]}


def export(ob, outdir, stem, formats=("GLB", "FBX", "OBJ")):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    out = {}
    for f in formats:
        p = os.path.join(outdir, f"{stem}.{f.lower()}")
        try:
            if f == "GLB":
                bpy.ops.export_scene.gltf(filepath=p, export_format="GLB",
                                        export_animations=False,
                                        export_morph=False)
            elif f == "FBX":
                bpy.ops.export_scene.fbx(filepath=p, use_mesh_modifiers=True,
                                         path_mode="COPY", bake_anim=False)
            else:
                bpy.ops.wm.obj_export(filepath=p, export_selected_objects=True,
                                      export_materials=False)
            out[f] = (p, os.path.getsize(p))
            print(f"  ✓ {p}  {os.path.getsize(p):,}")
        except Exception as e:
            print(f"  ! {f} 导出失败: {e}")
    return out


def main():
    src = sys.argv[1]
    outdir = sys.argv[2]
    voxels = [0.014, 0.020]
    if "--voxels" in sys.argv:
        voxels = [float(x) for x in
                  sys.argv[sys.argv.index("--voxels") + 1].split(",")]
    os.makedirs(outdir, exist_ok=True)

    print(f"▸ 导入 {src}")
    before = set(o.name for o in bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=src)
    # 只删导入**之前**就存在的残留（Blender 默认 Cube 会污染包围盒），
    # 导入进来的对象一律保留 —— 它们的名字随源文件而变，不能硬编码。
    for o in list(bpy.context.scene.objects):
        if o.name in before:
            nm = o.name
            bpy.data.objects.remove(o, do_unlink=True)
            print(f"  [clean] 移除残留 {nm}")
    imported = [o for o in bpy.context.scene.objects
                if o.type == "MESH" and o.name not in before]
    if not imported:
        sys.exit("✗ 导入后没有网格")
    if len(imported) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in imported:
            o.select_set(True)
        bpy.context.view_layer.objects.active = imported[0]
        bpy.ops.object.join()
    ob = next(o for o in bpy.context.scene.objects
              if o.type == "MESH" and o.name not in before)
    ob.name = "WhaleChan_White"
    print(f"  [mesh] {ob.name}  {len(ob.data.vertices):,} 顶点 "
          f"{len(ob.data.polygons):,} 面")

    print("▸ 删碎屑")
    ob = drop_fragments(ob, min_faces=1000)

    print("▸ 朝向 + 归一化")
    bp.orient_up([ob])
    bp.normalize([ob], target_h=TARGET_H)
    st = stats(ob)
    print(f"  [stat] {st}")

    print("▸ Laplacian 平滑")
    laplacian_smooth(ob, iters=2, factor=0.45)

    report = {"source": src, "versions": {}}

    # A. 高模（原拓扑）
    print("▸ [A] 高模（原拓扑）")
    # 白模不需要顶点色（会误导后续贴图），删掉；UV 保留（方便直接投影贴图）
    if "COLOR_0" in [a.name for a in ob.data.color_attributes]:
        ob.data.color_attributes.remove(ob.data.color_attributes["COLOR_0"])
        print("  [clean] 移除 COLOR_0 顶点色")
    stA = stats(ob)
    report["versions"]["high"] = stA
    print(f"  [stat] {stA}")
    export(ob, outdir, "white-high")

    # B. Voxel 重网格（多档）
    vox_objs = []
    for vs in voxels:
        print(f"▸ [B] Voxel 重网格 {vs}")
        v = voxel_remesh(ob, vs)
        bp.normalize([v], target_h=TARGET_H)     # 体素化会内缩，重新对齐高度
        stv = stats(v)
        report["versions"][f"voxel_{vs}"] = stv
        print(f"  [stat] {stv}")
        export(v, outdir, f"white-voxel{str(vs).replace('.','')}")
        vox_objs.append((vs, v))

    # C. Quad 重网格（用最细的 voxel 版为基底）
    if vox_objs:
        vs, base = min(vox_objs, key=lambda t: t[0])
        print(f"▸ [C] Quad 重网格（基底 voxel={vs}）")
        q = quad_remesh(base)
        bp.normalize([q], target_h=TARGET_H)
        stq = stats(q)
        report["versions"]["quad"] = stq
        print(f"  [stat] {stq}")
        export(q, outdir, "white-quad")

    # 工程文件
    blend = os.path.join(outdir, "white-clean.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print(f"  ✓ {blend}  {os.path.getsize(blend):,}")

    with open(os.path.join(outdir, "white_report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 对比渲染
    print("▸ 对比渲染")
    rdir = os.path.join(outdir, "renders")
    os.makedirs(rdir, exist_ok=True)
    coll = bpy.context.scene.collection
    cam = bp.setup_camera(coll, dist=5.6, z=1.44, lens=62)
    bp.setup_lights(coll)
    bp.setup_world(0.30)
    bp.setup_render(24, 512, transparent=False)
    # 灰模材质
    mat = bpy.data.materials.new("WhiteMat")
    mat.use_nodes = True
    b = mat.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.72, 0.74, 0.78, 1)
    b.inputs["Roughness"].default_value = 0.55
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.name != ob.name:
            o.hide_render = True
    for o in bpy.context.scene.objects:
        if o.type == "MESH":
            o.data.materials.clear()
            o.data.materials.append(mat)
    for nm, o in [("high", ob)] + [(f"voxel{v}", oo) for v, oo in vox_objs]:
        for other in bpy.context.scene.objects:
            if other.type == "MESH":
                other.hide_render = (other is not o)
        bp.frame_model(cam, [o], 0)
        bp.render_to(os.path.join(rdir, f"white_{nm}.png"))
        print(f"  ✓ white_{nm}.png")

    print("\n✓ 白模优化完成")


if __name__ == "__main__":
    main()
