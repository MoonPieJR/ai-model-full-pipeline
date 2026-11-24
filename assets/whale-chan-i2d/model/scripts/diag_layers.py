#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""沿高度分层，输出每层的宽度/深度/连通段数 —— 用数据定骨架位置。"""
import sys
import numpy as np
import trimesh

path = sys.argv[1] if len(sys.argv) > 1 else "out256s/triposr_raw.glb"
m = trimesh.load(path, force="mesh")
if isinstance(m, trimesh.Scene):
    m = trimesh.util.concatenate([g for g in m.geometry.values()
                                  if isinstance(g, trimesh.Trimesh)])

# 摆成 Z-up：最长轴 → Z
ext = m.bounds[1] - m.bounds[0]
axis = int(np.argmax(ext))
# 长轴 → Z：v_new = v_old @ M
if axis == 0:
    M3 = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float)   # X→Z
elif axis == 1:
    M3 = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float)   # Y→Z
else:
    M3 = np.eye(3)
v = m.vertices @ M3
v[:, 2] -= v[:, 2].min()
H = v[:, 2].max()
print(f"原最长轴 = {'XYZ'[axis]}  尺寸 {np.round(ext,3).tolist()}   归一化后 H={H:.3f} (应≈{ext[axis]:.3f})")

# 用 trimesh 的连通性做分层分段
M = np.eye(4)
M[:3, :3] = M3.T
M[3, 3] = 1.0
m2 = m.copy()
m2.apply_transform(M)
faces = m2.faces
tri = m2.triangles
_tz = tri[:, :, 2]
ZMIN = _tz.min()
_tz = _tz - ZMIN
H = H

NB = 25
print(f"\n{'z/H':>6} {'z':>7} {'宽x':>7} {'深y':>7} {'顶点数':>8} {'段数':>5}  段宽")
for i in range(NB):
    z0, z1 = H * i / NB, H * (i + 1) / NB
    sel = (_tz >= z0) & (_tz < z1)
    if sel.sum() < 3:
        continue
    p = tri[sel].reshape(-1, 3)
    p = p - np.array([0, 0, ZMIN])
    xspan = p[:, 0].max() - p[:, 0].min()
    yspan = p[:, 1].max() - p[:, 1].min()
    # 分段数：把该层三角面按 x 方向间隙切开
    xs = np.sort(np.unique(p[:, 0]))
    gaps = np.diff(xs)
    nseg = 1 + int((gaps > 0.02 * H).sum())
    segs = []
    if nseg > 1:
        cut = np.where(gaps > 0.02 * H)[0]
        bounds = [0] + list(cut + 1) + [len(xs)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a > 1:
                segs.append(f"{xs[a]:+.2f}..{xs[b-1]:+.2f}")
    print(f"{i/NB:6.3f} {z0:7.3f} {xspan:7.3f} {yspan:7.3f} {len(p):8,} {nseg:5d}  "
          + " ".join(segs[:4]))
