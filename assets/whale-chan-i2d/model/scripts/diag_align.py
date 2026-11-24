#!/usr/bin/env python3
"""诊断：把模型剪影按当前配准叠到参考图上，直观看偏移量。"""
import sys, json
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, '/workspace/i2d')
import retexture_ref as R

src, refpath = sys.argv[1], sys.argv[2]
g, buf = R.load_glb(src)
prim = g["meshes"][0]["primitives"][0]
pos = R.read_accessor(g, buf, prim["attributes"]["POSITION"])[:, :3]
idx = R.read_accessor(g, buf, prim["indices"]).reshape(-1, 3).astype(np.int64)

ref, ref_a_full, small = R.ref_rgba(refpath)
H, W = ref.shape[0], ref.shape[1]
reg = json.load(open('/workspace/i2d/refout/registration.json'))
print(json.dumps(reg, indent=1)[:600])

flip = reg.get('flip', False)
fx, fy, tx, ty = reg['fx'], reg['fy'], reg['tx'], reg['ty']
px, py = R.project_pts(pos[:, 0], pos[:, 1], fx, fy, tx, ty, flip)

canvas = Image.fromarray((ref * 255).astype(np.uint8)).convert('RGB')
ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(ov)
pts = [(float(a), float(b)) for a, b in zip(px, py)]
# 只画顶点云轮廓（点太多，画点阵即可）
for a, b in pts[::7]:
    d.ellipse([a - 1.2, b - 1.2, a + 1.2, b + 1.2], fill=(255, 0, 0, 150))
canvas = Image.alpha_composite(canvas.convert('RGBA'), ov).convert('RGB')
canvas.save('/workspace/i2d/diag_overlay.png')

# 参考图角色 bbox
ys, xs = np.where(ref_a_full > 0.5)
print(f"[ref ] 角色 bbox  x[{xs.min()},{xs.max()}]  y[{ys.min()},{ys.max()}]  "
      f"高 {ys.max()-ys.min()} px  画布 {W}x{H}")
print(f"[mod ] 投影 bbox  x[{px.min():.0f},{px.max():.0f}]  y[{py.min():.0f},{py.max():.0f}]  "
      f"高 {py.max()-py.min():.0f} px")

# 头顶区域：模型 y>2.2 的顶点投影到参考图的行范围
m = pos[:, 1] > 2.2
print(f"[head] 模型头顶(y>2.2) 投影行 {py[m].min():.0f}..{py[m].max():.0f}  "
      f"列 {px[m].min():.0f}..{px[m].max():.0f}")
m2 = pos[:, 1] < 0.25
print(f"[feet] 模型脚部(y<0.25) 投影行 {py[m2].min():.0f}..{py[m2].max():.0f}")
