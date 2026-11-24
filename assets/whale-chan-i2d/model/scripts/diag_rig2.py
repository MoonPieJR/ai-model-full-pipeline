#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""骨架诊断：显示骨骼位置 + 检查权重是否真的绑上了。"""
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
arm.show_in_front = True
arm.data.display_type = "OCTAHEDRAL"

print("── 权重状态 ──")
for m in meshes:
    vgs = m.vertex_groups
    mods = [(mo.name, mo.type) for mo in m.modifiers]
    n_v = len(m.data.vertices)
    print(f"  {m.name}: {n_v:,} verts  顶点组 {len(vgs)}  修改器 {mods}")
    if vgs:
        # 有多少顶点真的有权重
        vgroups = m.data.vertices.groups if hasattr(m.data.vertices, "groups") else None
        grp = [v.groups for v in m.data.vertices]
        weighted = sum(1 for g in grp if any(x.weight > 1e-4 for x in g))
        tot = sum(len(g) for g in grp)
        print(f"    有权重的顶点 {weighted:,}/{n_v:,} ({100*weighted/n_v:.1f}%)  "
              f"平均每顶点组数 {tot/max(n_v,1):.2f}")
        for vg in vgs:
            cnt = sum(1 for g in grp
                      if any(x.group == vg.index and x.weight > 1e-4 for x in g))
            print(f"      {vg.name:28s} {cnt:7,} 顶点")

print("\n── 骨骼位置（世界坐标）──")
for b in arm.data.bones:
    h = arm.matrix_world @ b.head_local
    t = arm.matrix_world @ b.tail_local
    print(f"  {b.name:28s} head=({h.x:+.3f},{h.y:+.3f},{h.z:+.3f}) "
          f"tail=({t.x:+.3f},{t.y:+.3f},{t.z:+.3f})")

# 渲染一张带骨架的
coll = bpy.context.scene.collection
cam = bp.setup_camera(coll, dist=5.6, z=1.44, lens=62)
bp.setup_lights(coll)
bp.setup_world(0.30)
bp.frame_model(cam, meshes + [arm], 0)
bp.setup_render(24, 640, transparent=False)
os.makedirs(out, exist_ok=True)
bp.render_to(os.path.join(out, "rig_overlay.png"))
print(f"\n✓ {out}/rig_overlay.png")
