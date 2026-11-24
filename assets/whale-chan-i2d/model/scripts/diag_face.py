#!/usr/bin/env python3
"""诊断2：模型脸部几何位置 vs 参考图脸部像素位置。"""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage
sys.path.insert(0, '/workspace/i2d')
import retexture_ref as R

g, buf = R.load_glb('/workspace/i2d/texout/baked.glb')
prim = g["meshes"][0]["primitives"][0]
pos = R.read_accessor(g, buf, prim["attributes"]["POSITION"])[:, :3]
nrm = R.read_accessor(g, buf, prim["attributes"]["NORMAL"])[:, :3]

ref, ref_a_full, small = R.ref_rgba('/workspace/i2d/fig2.jpg')
H, W = ref.shape[:2]

# ── 参考图的脸：肤色连通域（取头部区域里最大的一块） ──
skin = (ref[..., 0] > 0.72) & (ref[..., 0] > ref[..., 2] + 0.04) & (ref[..., 1] > 0.55)
skin &= (ref_a_full > 0.5)
ys, xs = np.where(ref_a_full > 0.5)
r0, r1 = ys.min(), ys.max()
head_rows = int(r0 + (r1 - r0) * 0.40)
skin[head_rows:, :] = False
lab, n = ndimage.label(skin)
sizes = ndimage.sum(skin, lab, range(1, n + 1))
big = int(np.argmax(sizes)) + 1
fy_, fx_ = np.where(lab == big)
print(f"[ref ] 脸部肤色块: 行 {fy_.min()}..{fy_.max()} (中心 {fy_.mean():.0f})  "
      f"列 {fx_.min()}..{fx_.max()} (中心 {fx_.mean():.0f})  面积 {sizes.max():.0f}")

# ── 模型的脸：头部区域最靠前的顶点（鼻子） ──
head = pos[:, 1] > 2.2
print(f"[mod ] 头部顶点 {head.sum():,}  y {pos[head,1].min():.2f}..{pos[head,1].max():.2f}")
zs = pos[head, 2]
for q in (100, 99, 98, 95):
    thr = np.percentile(zs, q)
    m = head & (pos[:, 2] >= thr)
    print(f"[mod ] 最前 {100-q:>2}% 顶点(z>={thr:.3f}): y {pos[m,1].min():.3f}..{pos[m,1].max():.3f} "
          f"(中心 {pos[m,1].mean():.3f})  x {pos[m,0].min():.3f}..{pos[m,0].max():.3f} "
          f"(中心 {pos[m,0].mean():.3f})  n={m.sum()}")

# 用当前仿射把模型的前顶点映射到参考图
fx_, fy_, tx_, ty_ = 542.0694, -608.6865, 764.98, 1774.62
flip = True
for q in (99, 97):
    thr = np.percentile(zs, q)
    m = head & (pos[:, 2] >= thr)
    mx = -pos[m, 0] if flip else pos[m, 0]
    px = fx_ * mx + tx_
    py = fy_ * pos[m, 1] + ty_
    print(f"[map] 模型前 {100-q}% 顶点 → 参考图 行 {py.min():.0f}..{py.max():.0f} "
          f"(中心 {py.mean():.0f})  列 {px.min():.0f}..{px.max():.0f} (中心 {px.mean():.0f})")
print(f"[map] 参考图脸部中心: 行 {fy_.mean():.0f}  列 {fx_.mean():.0f}")
