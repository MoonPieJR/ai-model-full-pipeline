#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bake_transform.py —— 把 Blender 侧的轴向/标度变换烘焙进 GLB 的 POSITION

为什么需要：
  TripoSR 的原始 GLB 里 POSITION 是 marching cubes 的**局部坐标**（横躺、
  尺度 ~0.5~1.0）。渲染时的站姿是靠 Blender 的 orient_up（绕 Y −90°）
  + normalize（缩放到 2.87 BU、脚底 z=0）实现的 —— 那只是 object transform，
  glTF 导出会把它变成 node TRS，POSITION 本身不变。
  于是任何在 numpy 层做深度判断的步骤（box UV 的投影平面、z-buffer）
  都拿不到"哪个轴是深度轴"。

本脚本：用 Blender 走一遍与渲染完全相同的 orient/normalize/smooth，
再把变换 apply 进 mesh 数据后导出，得到 POSITION = 世界坐标的 GLB
（导出时 export_yup=True → glTF 里 Y 是垂直轴、Z 是深度轴）。

用法：python bake_transform.py <src.glb> <dst.glb>
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp


def main():
    src, dst = sys.argv[1], sys.argv[2]
    bp.reset_scene()
    meshes, _ = bp.import_glb(src, "Import")
    bp.orient_up(meshes)
    bp.normalize(meshes)
    bp.laplacian_smooth(meshes, 0.25, 2)

    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    for o in meshes:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()
    lo, hi = bp.model_bounds(meshes)
    print(f"[xform] 尺寸 {hi[0]-lo[0]:.3f} x {hi[1]-lo[1]:.3f} x {hi[2]-lo[2]:.3f}"
          f"  底 z={lo[2]:.4f}")

    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB",
                              export_apply=True, export_yup=True)
    print(f"[out]  {dst}  {os.path.getsize(dst):,} bytes")


if __name__ == "__main__":
    main()
    os._exit(0)
