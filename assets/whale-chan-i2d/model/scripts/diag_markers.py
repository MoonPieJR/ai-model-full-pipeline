#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在骨骼关节处放小球并渲染，直观看骨架相对模型的位置。"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp

blend = sys.argv[1]
out = sys.argv[2]
bpy.ops.wm.open_mainfile(filepath=blend)

arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

for i, b in enumerate(arm.data.bones):
    for tag, p in (("head", arm.matrix_world @ b.head_local),
                   ("tail", arm.matrix_world @ b.tail_local)):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.028, location=tuple(p))
        s = bpy.context.object
        s.name = f"M_{i:02d}_{b.name.replace(':','_')}_{tag}"
        m = bpy.data.materials.new(f"mk{i}{tag}")
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (
            (1, 0.15, 0.1, 1) if tag == "head" else (0.1, 0.5, 1, 1))
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 4.0
        s.data.materials.append(m)

coll = bpy.context.scene.collection
cam = bp.setup_camera(coll, dist=5.6, z=1.44, lens=62)
bp.setup_lights(coll)
bp.setup_world(0.30)
bp.frame_model(cam, meshes + [arm], 0)
bp.setup_render(24, 700, transparent=False)
os.makedirs(out, exist_ok=True)
bp.render_to(os.path.join(out, "rig_markers.png"))
print(f"✓ {out}/rig_markers.png")
