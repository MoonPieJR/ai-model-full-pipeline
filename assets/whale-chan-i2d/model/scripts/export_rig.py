#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出模型顶点(世界坐标) + 骨骼线段，供外部画对位图。"""
import os
import sys

import bpy
import numpy as np

blend = sys.argv[1]
out = sys.argv[2]
bpy.ops.wm.open_mainfile(filepath=blend)

arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

allv = []
for ob in meshes:
    mw = np.array(ob.matrix_world)
    co = np.empty(len(ob.data.vertices) * 3, dtype=np.float32)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    allv.append(co @ mw[:3, :3].T + mw[:3, 3])
V = np.concatenate(allv)

segs, names = [], []
for b in arm.data.bones:
    if not b.use_deform:
        continue
    segs.append(np.stack([arm.matrix_world @ b.head_local,
                          arm.matrix_world @ b.tail_local]))
    names.append(b.name)
S = np.stack(segs)

np.savez(out, V=V, S=S, names=np.array(names))
print(f"✓ {out}  顶点 {len(V):,}  骨段 {len(S)}")
