#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_variant.py —— 快速渲染参数变体（不重做几何/颜色迁移）
用法：python render_variant.py <glb> <out.png> <sat> <key> <fill> <rim> <world> [samples]
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp


def main():
    glb, out = sys.argv[1], sys.argv[2]
    sat = float(sys.argv[3])
    key, fill, rim = (float(x) for x in sys.argv[4:7])
    world = float(sys.argv[7])
    samples = int(sys.argv[8]) if len(sys.argv) > 8 else 40

    bp.reset_scene()
    meshes, _ = bp.import_glb(glb, "Import")
    bp.orient_up(meshes)
    bp.normalize(meshes)
    bp.laplacian_smooth(meshes, 0.25, 2)
    coll = bp.get_coll("Render")
    cam = bp.setup_camera(coll)
    bp.frame_model(cam, meshes, 0)
    mat = bp.build_fixed_material(meshes, "WhaleChan_Fixed",
                                  color_boost=1.0, saturation=sat)
    bp.apply_material(meshes, mat)
    bp.setup_world(world)
    bp.setup_lights(coll)
    # 灯光强度覆盖
    for ob in coll.objects:
        if ob.type == "LIGHT":
            for tag, base, sc in (("Key", 120.0, key), ("Fill", 40.0, fill),
                                  ("Rim", 90.0, rim)):
                if tag in ob.name:
                    ob.data.energy = base * sc / 100.0
    bp.setup_render(samples, 1024)
    bp.render_to(out)
    print("[done]", out)


if __name__ == "__main__":
    main()
    os._exit(0)
