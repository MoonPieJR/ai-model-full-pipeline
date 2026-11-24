#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""白模可绑骨性诊断：碎片 / 开边 / 非流形 / 面长分布 / 姿态。"""
import sys
import numpy as np
import trimesh

path = sys.argv[1] if len(sys.argv) > 1 else "out256s/triposr_raw.glb"
m = trimesh.load(path, force="mesh")
if isinstance(m, trimesh.Scene):
    m = trimesh.util.concatenate([g for g in m.geometry.values()
                                  if isinstance(g, trimesh.Trimesh)])
print(f"文件      {path}")
print(f"顶点      {len(m.vertices):,}")
print(f"三角面    {len(m.faces):,}")
print(f"水密      {m.is_watertight}   流形 {m.is_winding_consistent}   体积 {m.volume:.4f}")
print(f"包围盒    {np.round(m.bounds, 3).tolist()}")
ext = m.bounds[1] - m.bounds[0]
print(f"尺寸      {np.round(ext, 3).tolist()}  最长轴占比 {ext.max()/ext.sum():.2f}")

# 连通分量（碎片）
comps = m.split(only_watertight=False)
sizes = sorted([len(c.faces) for c in comps], reverse=True)
print(f"\n连通分量  {len(comps)} 个")
print(f"  最大    {sizes[0]:,} 面 ({100*sizes[0]/len(m.faces):.1f}%)")
for i, s in enumerate(sizes[1:8], 2):
    print(f"  #{i:<2}    {s:,} 面 ({100*s/len(m.faces):.1f}%)")
small = sum(1 for s in sizes if s < 500)
print(f"  <500 面的碎屑: {small} 个，合计 {sum(s for s in sizes if s<500):,} 面")

# 边统计
e = np.sort(m.edges, axis=1)
uniq, cnt = np.unique(e, axis=0, return_counts=True)
print(f"\n边        {len(uniq):,} 条唯一边")
for k in (1, 2, 3):
    n = int((cnt == k).sum())
    print(f"  {k} 面共用: {n:,} ({100*n/len(uniq):.1f}%)")
print(f"  → 边界边(开洞) {int((cnt==1).sum()):,}   非流形 {int((cnt>2).sum()):,}")

# 面长分布（绑骨/重拓扑的平滑度参考）
# 面法线夹角：用边邻接重建
e2f = {}
for fi, f in enumerate(m.faces):
    for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
        e2f.setdefault((min(a, b), max(a, b)), []).append(fi)
ang = []
for k, fl in e2f.items():
    if len(fl) == 2:
        n1, n2 = m.face_normals[fl[0]], m.face_normals[fl[1]]
        ang.append(np.degrees(np.arccos(np.clip(np.dot(n1, n2), -1, 1))))
ang = np.array(ang)
if len(ang):
    print(f"\n面夹角   中位 {np.median(ang):.1f}°  90th {np.percentile(ang,90):.1f}°  "
          f">120° 的面 {int((ang>120).sum()):,} ({100*(ang>120).mean():.1f}%)")
ar = m.area_faces
print(f"面面积    中位 {np.median(ar):.3e}  最大/最小 {ar.max()/max(ar.min(),1e-12):.1f}x")

# 姿态线索：横截面宽度沿高度分布（判断是否 T/A-pose、站直）
v = m.vertices
lo, hi = v[:, 2].min(), v[:, 2].max()
print(f"\n沿高度的横向宽度（Z 为长轴时）:")
bins = 12
for i in range(bins):
    z0 = lo + (hi - lo) * i / bins
    z1 = lo + (hi - lo) * (i + 1) / bins
    sel = (v[:, 2] >= z0) & (v[:, 2] < z1)
    if sel.sum() < 10:
        continue
    p = v[sel]
    print(f"  z {z0:+.2f}..{z1:+.2f}  n={sel.sum():6,}  "
          f"x跨度 {p[:,0].max()-p[:,0].min():.3f}  y跨度 {p[:,1].max()-p[:,1].min():.3f}")
