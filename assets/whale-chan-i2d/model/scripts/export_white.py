#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_white.py —— 白模收尾：逐个对象单独导出 + Cube Projection UV + 补渲染

为什么要单独导出：Blender 的 glTF/FBX 导出默认打包**整个场景**，
之前一次导出把 4 个版本全塞进了一个 GLB（11MB → 应为 1MB 级）。
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp

blend = sys.argv[1]
outdir = sys.argv[2]
bpy.ops.wm.open_mainfile(filepath=blend)

objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print(f"▸ 场景中 {len(objs)} 个网格")


def has_uv(o):
    return o.data.uv_layers.active is not None and len(o.data.uv_layers) > 0


def cube_uv(o):
    """Edit Mode → Cube Projection：纯几何体的实用 UV（盒式投影）。"""
    if has_uv(o):
        print(f"  [uv] {o.name} 已有 UV，跳过")
        return
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.cube_project(cube_size=2.0, correct_aspect=True,
                             clip_to_bounds=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    print(f"  [uv] {o.name} Cube Projection 完成")


def clean_data(o):
    """白模只需要几何 + 一层 UV：多余的颜色层/UV 层会让文件白白大一倍。"""
    for attr in list(o.data.color_attributes):
        o.data.color_attributes.remove(attr)
    uvls = list(o.data.uv_layers)
    for u in uvls[1:]:
        o.data.uv_layers.remove(u)
    for attr in list(o.data.attributes):
        if attr.name not in ("position", "normal"):
            try:
                o.data.attributes.remove(attr)
            except Exception:
                pass
    o.data.update()


def export_one(o, stem):
    clean_data(o)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    res = {}
    for fmt in ("GLB", "FBX", "OBJ"):
        p = os.path.join(outdir, f"{stem}.{fmt.lower()}")
        try:
            if fmt == "GLB":
                bpy.ops.export_scene.gltf(filepath=p, export_format="GLB",
                                        use_selection=True,
                                        export_animations=False,
                                        export_morph=False,
                                        export_extras=False)
            elif fmt == "FBX":
                bpy.ops.export_scene.fbx(filepath=p, use_selection=True,
                                         use_mesh_modifiers=True,
                                         path_mode="COPY", bake_anim=False,
                                         mesh_smooth_type="FACE")
            else:
                bpy.ops.wm.obj_export(filepath=p, export_selected_objects=True,
                                      export_materials=False,
                                      export_uv=True, export_normals=True)
            res[fmt] = {"path": p, "bytes": os.path.getsize(p)}
            print(f"  ✓ {p}  {os.path.getsize(p):,}")
        except Exception as e:
            print(f"  ! {fmt} 失败: {e}")
    return res


# 对象名 → 输出文件名
STEM = {
    "WhaleChan_White": "white-high",
    "WhaleChan_White_vox": "white-voxel0014",
    "WhaleChan_White_vox.001": "white-voxel002",
    "WhaleChan_White_quad": "white-quad",
    "WhaleChan_White_vox_quad": "white-quad",
}

report = {}
for o in objs:
    stem = STEM.get(o.name)
    if stem is None:
        # 兜底：按名字猜
        n = o.name
        stem = ("white-high" if "vox" not in n and "quad" not in n
                else ("white-quad" if "quad" in n else n.replace("_vox", "_vox")))
    print(f"\n▸ {o.name} → {stem}")
    cube_uv(o)
    r = export_one(o, stem)
    report[stem] = {
        "verts": len(o.data.vertices),
        "faces": len(o.data.polygons),
        "size": [round(v, 3) for v in o.dimensions],
        "files": r,
    }

# 补渲染 quad
rdir = os.path.join(outdir, "renders")
os.makedirs(rdir, exist_ok=True)
coll = bpy.context.scene.collection
cam = bp.setup_camera(coll, dist=5.6, z=1.44, lens=62)
bp.setup_lights(coll)
bp.setup_world(0.30)
bp.setup_render(24, 512, transparent=False)
mat = bpy.data.materials.new("WM")
mat.use_nodes = True
bs = mat.node_tree.nodes.get("Principled BSDF")
bs.inputs["Base Color"].default_value = (0.72, 0.74, 0.78, 1)
bs.inputs["Roughness"].default_value = 0.55
for o in objs:
    o.data.materials.clear()
    o.data.materials.append(mat)
    o.hide_render = True
for o in objs:
    o.hide_render = False
    bp.frame_model(cam, [o], 0)
    stem = STEM.get(o.name, o.name)
    p = os.path.join(rdir, f"white_{stem.replace('white-','')}.png")
    print("   →", os.path.basename(p))
    bp.render_to(p)
    print(f"  ✓ {p}")
    o.hide_render = True

with open(os.path.join(outdir, "white_report.json"), "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print("\n✓ 导出完成")
