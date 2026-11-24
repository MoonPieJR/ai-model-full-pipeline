#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retexture_ref.py —— 用参考图作为「唯一色彩真值」，重做 UV 贴图与顶点色

背景
----
上一版贴图的色彩源头是 TripoSR 的顶点色，而 TripoSR 顶点色本身就把
原图里深藏青的裙子 / 白围裙 / 蓝渐变头发全洗成了灰白，还残留紫洋红色斑。
box projection 再把这些错误顶点色「拉成大色块」—— 于是贴图既不像原图，
渲染出来也不像原图。

本脚本换一个思路：**不再修顶点色，直接把原图投影回网格。**
  1. PIL 泛洪抠出角色 alpha（背景是渐变，只能用连通泛洪，不能用全局阈值）
  2. 把模型剪影投影到参考图画布，与参考图 alpha 做 IoU 配准
     —— 搜索 (scale_x, scale_y, tx, ty) 与「是否左右镜像」，
        由 IoU 自动决定正/背面（单图重建无法靠启发式猜朝向）
  3. 去掉原图里烘焙的明暗（低频压平）→ 得到干净 albedo
  4. 把 albedo 按配准结果「掰」到模型正面投影域 → 作为贴图正面大区
  5. 背面用镜像 albedo，左右侧取正面轮廓边缘色，顶底取平均色
  6. UV 逐面角给出（拆点），同时写 COLOR_0 作为不读贴图的查看器兜底

用法：python retexture_ref.py <src.glb> <ref.jpg> <outdir> [tex_size]
"""
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_CT = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
JSON_CH = 0x4E4F534A
BIN_CH = 0x004E4942


# ─────────────────────────── GLB IO ───────────────────────────
def load_glb(path):
    with open(path, "rb") as f:
        _, _, length = struct.unpack("<4sII", f.read(12))
        chunks = {}
        while f.tell() < length:
            cl, ct = struct.unpack("<II", f.read(8))
            chunks[ct] = f.read(cl)
    return json.loads(chunks[JSON_CH]), chunks[BIN_CH]


def read_accessor(g, buf, idx):
    a = g["accessors"][idx]
    bv = g["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    n = a["count"] * _NC[a["type"]]
    arr = np.frombuffer(buf, dtype=_CT[a["componentType"]], count=n, offset=off)
    arr = arr.reshape(a["count"], _NC[a["type"]]).astype(np.float64)
    if a.get("normalized") and a["componentType"] in (5121, 5123, 5125):
        arr = arr / float({5121: 255.0, 5123: 65535.0,
                           5125: 4294967295.0}[a["componentType"]])
    return arr


def srgb2lin(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin2srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92,
                    1.055 * np.power(c, 1 / 2.4) - 0.055)


# ─────────────────────── 参考图抠像（泛洪） ───────────────────────
def ref_rgba(path, work=1800):
    """背景是柔和渐变，只能用「从画布边缘泛洪」的方式抠。
    PIL 的 floodfill 以种子色为基准、逐像素比较，能跨越渐变。

    全流程都在工作分辨率（≈1400px 宽）上做 —— 原图 3552×4736 做 float64
    高斯滤波会吃掉 2GB+ 内存，沙箱只有 3GB。
    """
    im = Image.open(path).convert("RGB")
    if max(im.size) > work:
        s = work / max(im.size)
        small = im.resize((round(im.width * s), round(im.height * s)),
                          Image.LANCZOS)
    else:
        small = im
    rgba = small.convert("RGBA")
    w, h = rgba.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for pt in seeds:
        try:
            ImageDraw.floodfill(rgba, pt, (255, 255, 255, 0), thresh=34)
        except Exception:
            pass
    alpha = np.asarray(rgba).astype(np.float32)[..., 3] / 255.0
    # 补内部孔洞（角色身上与背景同色的区域）
    alpha = ndimage.binary_fill_holes(alpha > 0.5).astype(np.float32)
    # 轻微闭运算，补上泛洪漏掉的一像素边
    alpha = ndimage.binary_closing(alpha > 0.5, np.ones((3, 3))).astype(np.float32)
    rgb = np.asarray(small).astype(np.float32) / 255.0
    return rgb, alpha, small


# ─────────────────── 剪影投影 + IoU 配准 ───────────────────
def project_pts(x, y, fx, fy, tx, ty, flip):
    xr = -x if flip else x
    return fx * xr + tx, fy * y + ty


def splat(px, py, W, H):
    m = np.zeros((H, W), dtype=bool)
    ix = np.round(px).astype(np.int64)
    iy = np.round(py).astype(np.int64)
    ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
    m[iy[ok], ix[ok]] = True
    # 1 像素膨胀，补三角形之间的空隙
    return ndimage.binary_dilation(m, np.ones((3, 3)))


def iou(a, b):
    u = np.logical_or(a, b).sum()
    return np.logical_and(a, b).sum() / max(u, 1)


def silhouette_iou(pos, ref_mask, W, H, fx, fy, tx, ty, flip):
    px, py = project_pts(pos[:, 0], pos[:, 1], fx, fy, tx, ty, flip)
    return iou(splat(px, py, W, H), ref_mask)


def refine(pos, ref_mask, W, H, fx, fy, tx, ty, flip, iters=6):
    best = silhouette_iou(pos, ref_mask, W, H, fx, fy, tx, ty, flip)
    p = [fx, fy, tx, ty]
    for it in range(iters):
        step = 0.06 / (1.6 ** it)
        improved = True
        while improved:
            improved = False
            for d in range(4):
                for sgn in (1, -1):
                    q = list(p)
                    q[d] += sgn * step * (step if d < 2 else step * 60)
                    v = silhouette_iou(pos, ref_mask, W, H,
                                        q[0], q[1], q[2], q[3], flip)
                    if v > best + 1e-7:
                        best, p = v, q
                        improved = True
    return p[0], p[1], p[2], p[3], best


def fit_landmarks(ref_mask, pos, flip):
    """用「头部宽度 + 整体高度」给一个稳健初值：
    尾巴会让整体 bbox 偏移，但头是对称的。"""
    ys, xs = np.where(ref_mask)
    rx0, rx1, ry0, ry1 = xs.min(), xs.max(), ys.min(), ys.max()
    H = ry1 - ry0 + 1
    head = ref_mask[ry0:ry0 + int(H * 0.22), :]
    hs = np.where(head.any(axis=0))[0]
    ref_head_w = (hs.max() - hs.min() + 1) if len(hs) else (rx1 - rx0 + 1)
    ref_head_c = (hs.min() + hs.max()) / 2 if len(hs) else (rx0 + rx1) / 2

    mx = -pos[:, 0] if flip else pos[:, 0]
    my = pos[:, 1]
    top = my > my.max() - (my.max() - my.min()) * 0.22
    hsx = mx[top]
    m_head_w = hsx.max() - hsx.min() + 1
    m_head_c = (hsx.min() + hsx.max()) / 2
    fx = ref_head_w / max(m_head_w, 1e-6)
    fy = -H / max(my.max() - my.min(), 1e-6)
    tx = ref_head_c - fx * m_head_c
    # 垂直：模型 y 向上 → 图像行号向下；模型头顶(my.max)对齐参考图顶部(ry0)
    ty = ry0 - fy * my.max()
    return fx, fy, tx, ty


# ─────────────────── 纵向比例配准（轮廓面积剖面 DTW） ───────────────────
def area_profile_model(pos, nb=256):
    """模型每一水平条带的「面积」≈ 该条带顶点数（marching cubes 密度近似均匀）。"""
    y = pos[:, 1]
    y0, y1 = y.min(), y.max()
    b = np.clip(((y - y0) / max(y1 - y0, 1e-9) * (nb - 1)).round().astype(int),
                0, nb - 1)
    cnt = np.bincount(b, minlength=nb).astype(np.float64)
    return cnt / max(cnt.max(), 1e-9)


def area_profile_ref(mask, nb=256):
    """参考图每一行的「面积」= 该行 alpha 像素数（同样归一化）。"""
    area = mask.sum(axis=1).astype(np.float64)
    idx = np.where(mask.any(axis=1))[0]
    if len(idx) == 0:
        return np.ones(nb), np.zeros(nb, dtype=int)
    r0, r1 = idx.min(), idx.max()
    rows = np.linspace(r0, r1, nb).round().astype(int)
    prof = area[rows]
    return prof / max(prof.max(), 1e-9), rows


def dtw_map(a_mod, a_ref, slope_pen=0.10):
    """DTW 对齐两条剖面 → 模型条带 → 参考图行的单调映射。

    单图重建的**比例**和原图不同（实测 TripoSR 把头重建小了约 30%），
    全局仿射只能对齐总高，总高对齐了脸就会错位到头顶。
    用「面积剖面」对齐可以把头/身/裙的相对高度自动配准。
    """
    n, m = len(a_mod), len(a_ref)
    INF = 1e18
    D = np.full((n + 1, m + 1), INF)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        c = np.abs(a_mod[i - 1] - a_ref)
        D[i, 1:] = c + np.minimum(
            np.minimum(D[i - 1, :-1], D[i - 1, 1:] + slope_pen),
            D[i, :-1] + slope_pen)
    i, j = n, m
    back = np.zeros(n, dtype=np.float64)
    while i > 0 and j > 0:
        back[i - 1] = j - 1
        if i > 1 and j > 1 and D[i - 1, j - 1] <= D[i - 1, j] and D[i - 1, j - 1] <= D[i, j - 1]:
            i, j = i - 1, j - 1
        elif i > 1 and D[i - 1, j] <= D[i, j - 1]:
            i, j = i - 1, j
        else:
            i, j = i, j - 1
    # 缺口用插值补齐，并强制单调
    good = np.where(back >= 0)[0]
    back = np.interp(np.arange(n), good, back[good])
    back = np.maximum.accumulate(back)
    return back


# ─────────────────── 去光照（低频压平） ───────────────────
def flatten_shading(rgb, alpha, sigma_frac=0.05):
    """参考图是「渲染图」，明暗是烘焙进去的。压掉低频光照当 albedo 用，
    否则模型会被二次打光（照片的阴影 + 渲染器灯光）。"""
    lin = srgb2lin(rgb.astype(np.float32))
    m = alpha > 0.5
    if m.sum() < 100:
        return rgb
    sig = max(4.0, sigma_frac * max(rgb.shape[0], rgb.shape[1]))
    w = ndimage.gaussian_filter(alpha.astype(np.float32), sig)
    num = np.stack([ndimage.gaussian_filter(lin[..., c] * w, sig) for c in range(3)],
                   axis=-1)
    den = ndimage.gaussian_filter(w, sig)[..., None]
    base = num / np.maximum(den, 1e-6)
    mean = lin[m].mean(axis=0)
    flat = np.clip(lin * (mean / np.maximum(base, 1e-3)), 0, 1)
    return lin2srgb(np.where(m[..., None], flat, rgb).astype(np.float32))


def extend_outward(rgb, alpha, iters=28):
    """把角色颜色向外延伸若干像素，覆盖模型剪影比参考图更胖的部分，
    避免模型边缘出现一圈背景米白。

    用「最近角色像素的颜色」而不是扩散平均 —— 扩散会把颜色抹成灰白雾状，
    在模型上表现为一片片白斑；最近邻在轮廓附近能保住原本的颜色。
    """
    m = alpha > 0.5
    if iters <= 0:
        return rgb, alpha
    dist, idx = ndimage.distance_transform_edt(~m, return_indices=True)
    src = rgb[idx[0], idx[1]]
    g = np.clip(dist / float(iters), 0, 1)[..., None]
    return rgb.astype(np.float32) * (1 - g) + src * g, dist


# ─────────────────────────── 主流程 ───────────────────────────
def prefilter_by_compression(rgb, comp):
    """按「局部压缩率」给贴图做变半径模糊。

    为什么需要：平面投影在掠射面（比如头顶那个几乎与视线平行的圆顶）上
    会把贴图压得很扁 —— 同样的贴图面积挤在很小的屏幕面积里，就是典型的
    缩小采样（minification），没有 mipmap 就会出摩尔纹（渲染出来是横条纹）。
    这里按压缩率给不同区域做不同半径的模糊，等价于自己生成 mipmap。

    压缩率 c = 1/|n·视线|：正对视线 c=1，掠射 c→∞。
    模糊半径按 mipmap 的经验取 ~c（texel）。
    """
    b1 = ndimage.gaussian_filter(rgb, (1.0, 1.0, 0))
    b2 = ndimage.gaussian_filter(rgb, (2.0, 2.0, 0))
    b3 = ndimage.gaussian_filter(rgb, (4.0, 4.0, 0))
    b4 = ndimage.gaussian_filter(rgb, (7.0, 7.0, 0))
    c = comp[..., None]
    out = np.where(c < 1.5, rgb,
                   np.where(c < 2.5, b1,
                            np.where(c < 4.5, b2,
                                     np.where(c < 8.0, b3, b4))))
    return out.astype(np.float32)


def rasterize_comp(uv_tex, idx, comp_face, size):
    """把每个面的压缩率光栅化到图集坐标（取最大覆盖值）。"""
    comp = np.zeros((size, size), dtype=np.float32)
    t0, t1, t2 = idx[:, 0], idx[:, 1], idx[:, 2]
    ax, ay = uv_tex[t0, 0], uv_tex[t0, 1]
    bx, by = uv_tex[t1, 0], uv_tex[t1, 1]
    cx, cy = uv_tex[t2, 0], uv_tex[t2, 1]
    minx = np.maximum(np.minimum(np.minimum(ax, bx), cx).astype(int), 0)
    maxx = np.minimum(np.maximum(np.maximum(ax, bx), cx).astype(int) + 2, size)
    miny = np.maximum(np.minimum(np.minimum(ay, by), cy).astype(int), 0)
    maxy = np.minimum(np.maximum(np.maximum(ay, by), cy).astype(int) + 2, size)
    for t in range(len(idx)):
        x0, x1, y0, y1 = minx[t], maxx[t], miny[t], maxy[t]
        if x1 <= x0 or y1 <= y0:
            continue
        p0x, p0y = ax[t], ay[t]
        p1x, p1y = bx[t], by[t]
        p2x, p2y = cx[t], cy[t]
        det = (p1y - p2y) * (p0x - p2x) + (p2x - p1x) * (p0y - p2y)
        if abs(det) < 1e-12:
            continue
        gx = (np.arange(x0, x1, dtype=np.float64) + 0.5)[None, :]
        gy = (np.arange(y0, y1, dtype=np.float64) + 0.5)[:, None]
        l0 = ((p1y - p2y) * (gx - p2x) + (p2x - p1x) * (gy - p2y)) / det
        l1 = ((p2y - p0y) * (gx - p2x) + (p0x - p2x) * (gy - p2y)) / det
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if inside.any():
            sub = comp[y0:y1, x0:x1]
            np.maximum(sub, comp_face[t], out=sub, where=inside)
    return comp


def rasterize_area_ratio(uv_tex, idx, comp_face, size, zbuf_depth):
    """区域级压缩率 = 该区域累计的 UV 面积 / 该区域「可见」的 UV 面积。

    这才是 mipmap 该用的度量：
      · 累计 UV 面积 —— 同一块贴图区域被多少层几何覆盖（细发丝层层重叠）
      · 可见 UV 面积 —— 屏幕上真正看到的那一层
    两者之比 > 1 说明这块贴图被过度采样，缩小采样必然出摩尔纹。
    """
    total = np.zeros((size, size), dtype=np.float32)
    visible = np.zeros((size, size), dtype=np.float32)
    zbuf = np.full((size, size), -np.inf, dtype=np.float32)
    t0, t1, t2 = idx[:, 0], idx[:, 1], idx[:, 2]
    ax, ay = uv_tex[t0, 0], uv_tex[t0, 1]
    bx, by = uv_tex[t1, 0], uv_tex[t1, 1]
    cx, cy = uv_tex[t2, 0], uv_tex[t2, 1]
    minx = np.maximum(np.minimum(np.minimum(ax, bx), cx).astype(int), 0)
    maxx = np.minimum(np.maximum(np.maximum(ax, bx), cx).astype(int) + 2, size)
    miny = np.maximum(np.minimum(np.minimum(ay, by), cy).astype(int), 0)
    maxy = np.minimum(np.maximum(np.maximum(ay, by), cy).astype(int) + 2, size)
    for t in range(len(idx)):
        x0, x1, y0, y1 = minx[t], maxx[t], miny[t], maxy[t]
        if x1 <= x0 or y1 <= y0:
            continue
        p0x, p0y = ax[t], ay[t]
        p1x, p1y = bx[t], by[t]
        p2x, p2y = cx[t], cy[t]
        det = (p1y - p2y) * (p0x - p2x) + (p2x - p1x) * (p0y - p2y)
        if abs(det) < 1e-12:
            continue
        gx = (np.arange(x0, x1, dtype=np.float64) + 0.5)[None, :]
        gy = (np.arange(y0, y1, dtype=np.float64) + 0.5)[:, None]
        l0 = ((p1y - p2y) * (gx - p2x) + (p2x - p1x) * (gy - p2y)) / det
        l1 = ((p2y - p0y) * (gx - p2x) + (p0x - p2x) * (gy - p2y)) / det
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        # 累计面积（所有层）
        area = comp_face[t]
        sub = total[y0:y1, x0:x1]
        np.add(sub, area * inside, out=sub)
        # 可见面积（z 缓冲取最靠近相机的一层）
        zz = l0 * zbuf_depth[t0[t]] + l1 * zbuf_depth[t1[t]] + l2 * zbuf_depth[t2[t]]
        subz = zbuf[y0:y1, x0:x1]
        upd = inside & (zz > subz)
        if upd.any():
            subv = visible[y0:y1, x0:x1]
            np.add(subv, area * upd, out=subv)
            subz[upd] = zz[upd]
    ratio = np.where(visible > 0, total / np.maximum(visible, 1e-6), 1.0)
    return np.clip(ratio, 1.0, 30.0)


def main():
    src, refpath, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 2048
    os.makedirs(outdir, exist_ok=True)

    # 1. 读源 GLB
    g, buf = load_glb(src)
    prim = g["meshes"][0]["primitives"][0]
    pos = read_accessor(g, buf, prim["attributes"]["POSITION"])[:, :3]
    idx = read_accessor(g, buf, prim["indices"]).reshape(-1, 3).astype(np.int64)
    nrm = (read_accessor(g, buf, prim["attributes"]["NORMAL"])[:, :3]
           if "NORMAL" in prim["attributes"] else None)
    rng = pos.max(axis=0) - pos.min(axis=0)
    print(f"[in ] {len(pos):,} 顶点 / {len(idx):,} 面   "
          f"bbox X{rng[0]:.2f} Y{rng[1]:.2f} Z{rng[2]:.2f} (Y 垂直 / Z 深度)")

    # 2. 参考图抠像（工作分辨率）
    ref, ref_a_full, small = ref_rgba(refpath)
    ys, xs = np.where(ref_a_full > 0.5)
    rbox = (xs.min(), xs.max(), ys.min(), ys.max())
    print(f"[ref] {ref.shape[1]}×{ref.shape[0]}  角色 bbox x[{rbox[0]},{rbox[1]}] "
          f"y[{rbox[2]},{rbox[3]}]  占比 {ref_a_full.mean()*100:.1f}%")

    # 3. 配准：在参考图画布上找最优 (fx, fy, tx, ty) 与镜像
    W = 512
    H = int(round(W * ref.shape[0] / ref.shape[1]))
    ref_mask_small = np.asarray(
        Image.fromarray((ref_a_full * 255).astype(np.uint8))
        .resize((W, H), Image.BILINEAR)) > 127
    k = W / ref.shape[1]
    best = None
    for flip in (False, True):
        fx, fy, tx, ty = fit_landmarks(ref_mask_small, pos, flip)
        cands = [(fx, fy, tx, ty)]
        # 再加一个「整体 bbox 对齐」的初值，覆盖头部对齐失效的情况
        mx0, mx1 = pos[:, 0].min(), pos[:, 0].max()
        my0, my1 = pos[:, 1].min(), pos[:, 1].max()
        sx = (rbox[1] - rbox[0]) / max(mx1 - mx0, 1e-6)
        sy = -(rbox[3] - rbox[2]) / max(my1 - my0, 1e-6)
        # 镜像时模型的 x 被取反 → 中心项符号相反
        sgn = -1.0 if flip else 1.0
        tx2 = (rbox[0] + rbox[1]) / 2 - sx * sgn * (mx0 + mx1) / 2
        # 垂直：模型头顶(my1)对齐参考图顶部(rbox[2])，脚底(my0)对齐底部(rbox[3])
        ty2 = rbox[2] - sy * my1
        cands.append((sx, sy, tx2, ty2))
        for c in cands:
            f2 = (c[0] * k, c[1] * k, c[2] * k, c[3] * k)
            r = refine(pos, ref_mask_small, W, H, *f2, flip)
            print(f"[reg] 镜像={flip} 初值 IoU={silhouette_iou(pos, ref_mask_small, W, H, *f2, flip):.4f} "
                  f"→ 优化后 IoU={r[4]:.4f}")
            if best is None or r[4] > best[4]:
                best = r + (flip,)
    fx, fy, tx, ty, sc, flip = best
    fx, fy, tx, ty = fx / k, fy / k, tx / k, ty / k
    print(f"[reg] ★ 镜像={flip}  IoU={sc:.4f}  "
          f"px={fx:.4f}*x{tx:+.2f}  py={fy:.4f}*y{ty:+.2f}")

    # 4. 去光照 → albedo，并向背景扩散一圈（覆盖模型比参考图更胖的部分）
    albedo = flatten_shading(ref, ref_a_full)
    albedo, _grown = extend_outward(albedo, ref_a_full, iters=28)

    # 5. 把 albedo 掰到模型正面投影域
    #    ⚠ 行序必须与图像序一致（行 0 = 顶部 = 头顶），否则纹理上下颠倒。
    #    ⚠ flip=True 时模型的 x 要取反再采样 —— 重建网格相对参考图是镜像的，
    #      不取反的话尾巴会拿到头发的颜色。
    #    ⚠ 用「逐行轮廓对齐」而不是全局仿射 —— 重建网格的内部比例和原图并不
    #      完全一致（实测头部中心偏 0.14 BU），全局仿射会把脸错位到头发上；
    #      逐行把模型的 x 范围对齐到参考图该行的 x 范围可消除这种偏差。
    X0, X1 = pos[:, 0].min(), pos[:, 0].max()
    Y0, Y1 = pos[:, 1].min(), pos[:, 1].max()
    CELL_W = size // 2
    CELL_H = size * 3 // 4
    LOW_Y = CELL_H              # 下排格子起始行（侧/顶/底格）
    LOW_H = size - LOW_Y
    LOW_W = size // 4
    BACK_X = CELL_W             # 背面格起始列

    xf = -pos[:, 0] if flip else pos[:, 0]      # 镜像后的模型 x
    NB = 2048
    bins = np.clip(((pos[:, 1] - Y0) / max(Y1 - Y0, 1e-9) * NB).astype(int),
                   0, NB - 1)
    xm0 = np.full(NB, np.inf)     # 用 inf 而不是 NaN —— np.minimum.at 遇 NaN 会全污染
    xm1 = np.full(NB, -np.inf)
    np.minimum.at(xm0, bins, xf)
    np.maximum.at(xm1, bins, xf)
    for arr in (xm0, xm1):                      # 空行用邻近行填补
        bad = ~np.isfinite(arr)
        if bad.any():
            good = np.where(~bad)[0]
            arr[bad] = np.interp(np.where(bad)[0], good, arr[good])

    rmask = ref_a_full > 0.5
    Wref = rmask.shape[1]
    idxc = np.where(rmask, np.arange(Wref)[None, :], Wref)
    rx0 = idxc.min(axis=1)
    rx1 = np.where(rmask.any(axis=1), idxc.max(axis=1), -1)

    y_lo = Y0 + (np.arange(NB) / NB) * (Y1 - Y0)
    y_hi = Y0 + ((np.arange(NB) + 1) / NB) * (Y1 - Y0)

    # ── 纵向配准 ──────────────────────────────────────────────────
    #   单图重建的内部比例和原图不同：TripoSR 把**脸**放在了头的偏下位置，
    #   全局仿射只能对齐总高 → 脸会整体偏低（实测偏低约 38% 头高）。
    #   ⚠ 曾试过「轮廓面积剖面 DTW」，但模型的头发体量与原图差异太大，
    #     剖面匹配把头部压得更扁，反而更差 → 放弃。
    #   改用「头部区域纵向微调 + 自动搜索」：在头部整体上下平移贴图采样，
    #   取「模型正面头部顶点采到肤色的比例」最大的平移量 ——
    #   对齐正确时脸正好压在脸上，比例达到峰值；错位时脸压在头发上，比例骤降。
    rows_of_bin = fy * y_lo + ty

    # 参考图逐行的左右轮廓
    valid = rx1 >= 0
    r_idx = np.arange(len(rx0))
    rx0_f = np.interp(r_idx, r_idx[valid], rx0[valid])
    rx1_f = np.interp(r_idx, r_idx[valid], rx1[valid])

    # 头部区域：模型 y > 2.2（头顶到下巴）
    HEAD_Y = 2.2
    y_center = (y_lo + y_hi) / 2
    # ⚠ 头部的修正必须做成「拉伸」而不是「平移」：
    #   平移需要一段过渡带把位移渐隐，而位移梯度会反超基线
    #   (609 px/BU) → 映射翻折 → 贴图被复制（渲染里出现两张脸）。
    #   拉伸的梯度与基线同号，数学上不可能翻折 ✓
    #   Δ(y) = Δ_head · bump(y)：在头底(y=2.2)最大，头顶衰减为 0，
    #   向下用同样宽的过渡带渐隐，保证 C1 连续。
    #   鼓包峰值放在**脸的高度**（PEAK_Y≈2.35），而不是头底 ——
    #   峰值放在头底时脸所在的权重只有 0.09，求解会发散。
    PEAK_Y = 2.35
    TAPE = 0.55
    ramp = np.zeros(NB, dtype=np.float64)
    # ⚠ _up 必须在峰值处为 0、顶端为 1（方向写反过 → 头部区域硬跳变 → 贴图接缝）
    _up = np.clip((y_center - PEAK_Y) / max(Y1 - PEAK_Y, 1e-9), 0, 1)
    _dn = np.clip((PEAK_Y - y_center) / TAPE, 0, 1)   # ⚠ 方向：峰值在 PEAK_Y，向下衰减
    ramp = np.where(y_center >= PEAK_Y,
                     0.5 * (1 + np.cos(np.pi * _up)),
                     0.5 * (1 + np.cos(np.pi * _dn)))

    # 每个顶点在参考图上的采样位置（行、列）
    cell_rows_v = np.clip(np.round((Y1 - pos[:, 1]) / max(Y1 - Y0, 1e-9) * CELL_H - 0.5
                             ).astype(int), 0, CELL_H - 1)
    # cell 列索引 ↔ 模型 x：xj[i] = X0 + (i+0.5)/CELL_W*(X1-X0)
    # ⚠ 用**原始** pos[:,0]。翻转只发生在「参考图列 = fx*xj_f + tx」那一步；
    #   cell 网格本身建立在原始 x 网格上。
    cell_cols_v = np.clip(np.round((pos[:, 0] - X0) / max(X1 - X0, 1e-9) * CELL_W - 0.5
                             ).astype(int), 0, CELL_W - 1)
    bin_of_v = np.clip(((pos[:, 1] - Y0) / max(Y1 - Y0, 1e-9) * NB).astype(int),
                       0, NB - 1)
    # 正面头部顶点：头区域内、法线朝前（+Z）
    front_head = (pos[:, 1] > HEAD_Y) & (pos[:, 2] > 0.05)
    if nrm is not None:
        front_head &= (nrm[:, 2] > 0.35)

    # ── 头部精调：把模型的脸对齐到参考图的脸 ────────────────────────
    #   参考图里「脸」= 头部区域最大的肤色连通域；
    #   模型里「脸」  = 头部区域最靠前的顶点（鼻子）。
    #   在头部整体平移贴图采样，最大化「模型脸的顶点落进参考图脸里」的比例。
    #   ⚠ 早先用「肤色比例」当指标会被轮廓外扩伪影污染（边缘一圈假肤色），
    #     改用「脸 ↔ 脸」重叠率，峰值尖锐且方向正确。
    skin = ((albedo[..., 0] > 0.72) & (albedo[..., 0] > albedo[..., 2] + 0.04)
            & (albedo[..., 1] > 0.55) & (ref_a_full > 0.5))
    _ys, _xs = np.where(ref_a_full > 0.5)
    skin[_ys.min() + int((_ys.max() - _ys.min()) * 0.40):, :] = False
    _lab, _n = ndimage.label(skin)
    if _n > 0:
        _sz = ndimage.sum(skin, _lab, range(1, _n + 1))
        face_mask = (_lab == int(np.argmax(_sz)) + 1)
    else:
        face_mask = np.zeros_like(skin)
    _hz = pos[pos[:, 1] > HEAD_Y, 2]
    _thr = np.percentile(_hz, 97)
    face_v = (pos[:, 1] > HEAD_Y) & (pos[:, 2] >= _thr)

    xf_probe = -pos[:, 0] if flip else pos[:, 0]
    g0_probe_bin = np.interp(rows_of_bin, r_idx, rx0_f)
    dy_probe_bin = g0_probe_bin - (fx * xm0 + tx)

    def _face_hit(dy_px, dx_px):
        r = rows_of_bin[bin_of_v[face_v]] + ramp[bin_of_v[face_v]] * dy_px
        c = fx * xf_probe[face_v] + tx + dy_probe_bin[bin_of_v[face_v]] + dx_px
        ok = (r >= 0) & (r < ref.shape[0]) & (c >= 0) & (c < ref.shape[1])
        if ok.sum() < 20:
            return 0.0
        rr = np.clip(r[ok], 0, ref.shape[0] - 1).astype(int)
        cc = np.clip(c[ok], 0, ref.shape[1] - 1).astype(int)
        return float(face_mask[rr, cc].mean())
    # ── 头部对齐：用**保序的节点插值**建立纵向映射 ──────────────────
    #   节点（模型 y → 参考图行）：
    #     头顶 Y1  → 仿射行（29）
    #     鼻尖高度 → 参考图脸的中心行（几何实测）
    #     y=2.0   → 仿射行
    #     脚底 Y0  → 仿射行
    #   节点行号严格递增 → 映射严格单调 → 数学上不可能折叠 ✓
    #   ⚠ 之前用「平移 + 渐隐过渡带」导致行映射翻折，贴图被复制成两张脸；
    #     平移的梯度会反超仿射基线（609 px/BU），改节点插值后彻底规避。
    _fy, _fx_ = np.where(face_mask)
    face_cr, face_cc = float(_fy.mean()), float(_fx_.mean())
    nose_y = float(pos[face_v, 1].mean())
    r_top = fy * Y1 + ty
    r_bot = fy * Y0 + ty
    r_mid = fy * 2.0 + ty
    #   ⚠ 用 PCHIP（三次保序插值）而不是线性插值：线性会在节点处留下斜率断裂，
    #     贴图上会出现一道明显的横向接缝（脸被切成两半）。
    from scipy.interpolate import PchipInterpolator
    knots_y = np.array([Y1, nose_y, 1.8, 0.9, Y0], dtype=np.float64)
    knots_r = np.array([r_top, face_cr, fy * 1.8 + ty, fy * 0.9 + ty, r_bot],
                       dtype=np.float64)
    for _k in range(1, len(knots_y)):          # 保证行号严格递增
        if knots_r[_k] <= knots_r[_k - 1]:
            knots_r[_k] = knots_r[_k - 1] + 1.0
    if knots_r[0] > knots_r[1]:
        knots_r[0] = knots_r[1] - 1.0
    _pchip = PchipInterpolator(knots_y[::-1], knots_r[::-1])
    rows_of_bin = _pchip(y_lo)
    print(f"[head] 纵向节点(PCHIP)：" + "  ".join(
        f"y{y:.2f}→行{r:.0f}" for y, r in zip(knots_y, knots_r)))

    # 横向：让模型脸的中心列对齐参考图脸的中心列（整行平移，不会折叠）
    g0_probe_bin = np.interp(rows_of_bin, r_idx, rx0_f)
    dy_probe_bin = g0_probe_bin - (fx * xm0 + tx)
    xf_probe = -pos[:, 0] if flip else pos[:, 0]
    c_n = fx * xf_probe[face_v] + tx + dy_probe_bin[bin_of_v[face_v]]
    head_dx = float(face_cc - c_n.mean())
    print(f"[head] ★ 脸部对齐：横向微调 {head_dx:+.0f}px，"
          f"模型脸顶点落在参考图脸内 "
          f"{_face_hit(0.0, head_dx)*100:.1f}%（脸顶点 {int(face_v.sum()):,} 个）")
    # 自检：映射必须单调（否则贴图会被折叠，出现重影）
    _d = np.diff(rows_of_bin)
    print(f"[head] 纵向映射单调性检查：步长 min {_d.min():.2f} / max {_d.max():.2f} px"
          f"（max 必须 < 0，否则贴图会折叠成重影）")
    assert _d.max() < 0, "纵向映射非单调，贴图会折叠"

    ref_row_of_bin = rows_of_bin
    rx0_bin = np.interp(ref_row_of_bin, r_idx, rx0_f)
    rx1_bin = np.interp(ref_row_of_bin, r_idx, rx1_f)
    def _mem(tag):
        import resource
        print(f"[mem ] {tag}: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB", flush=True)
    _mem("warp 前后")
    print(f"[warp] 逐行轮廓对齐：模型行 bin {NB}，参考图有效行 {int((rx1 >= 0).sum())}")

    # 轮廓必须平滑，否则相邻行的横向比例会跳变 → 贴图被撕成条纹
    for arr in (xm0, xm1, rx0_bin, rx1_bin):
        sm = ndimage.median_filter(arr, size=65, mode="nearest")
        arr[:] = ndimage.uniform_filter1d(sm, size=129, mode="nearest")
    gscale = abs(fx)

    xj = X0 + (np.arange(CELL_W) + 0.5) / CELL_W * (X1 - X0)
    xj_f = -xj if flip else xj
    y_cell = Y1 - (np.arange(CELL_H) + 0.5) / CELL_H * (Y1 - Y0)
    cell_rows = np.clip(((y_cell - Y0) / max(Y1 - Y0, 1e-9) * NB).astype(int),
                        0, NB - 1)
    m0 = xm0[cell_rows][:, None]
    m1 = xm1[cell_rows][:, None]
    g0 = rx0_bin[cell_rows][:, None]
    # 只用逐行「平移」，缩放固定为全局仿射。
    # 逐行缩放会把贴图撕成条纹（尾巴把行轮廓撑宽 → 头部被压扁）；
    # 纯剪切只修正「整行偏移」（实测模型头部中心偏 0.14 BU），不会撕裂。
    dy = (g0 - (fx * m0 + tx))
    cols2 = fx * xj_f[None, :] + tx + dy + head_dx * ramp[cell_rows][:, None]
    # 纵向：改用 DTW 配准后的「模型行 → 参考图行」映射
    rows = ref_row_of_bin[cell_rows].astype(np.float64)
    grid_r = np.clip(rows, 0, ref.shape[0] - 1).astype(np.float64)
    grid_c = np.clip(cols2, 0, ref.shape[1] - 1).astype(np.float64)
    # ⚠ grid_c 已是二维（逐行对齐），不能再过 np.meshgrid —— 那会把形状撑成
    #   (CELL_H, CELL_H, CELL_W) 几十亿元素直接 OOM。直接广播。
    R = np.ascontiguousarray(np.broadcast_to(grid_r[:, None], grid_c.shape))
    C = grid_c
    front_rgb = np.stack([ndimage.map_coordinates(albedo[..., c], (R, C),
                                                  order=1, mode="nearest")
                           for c in range(3)], axis=-1)
    front_a = ndimage.map_coordinates(ref_a_full, (R, C), order=1,
                                      mode="nearest") > 0.5
    # ── 接缝诊断：找出 cell grid 里行间差异最大的行，并打印该行附近的
    #    纵向映射 / 横向对齐量，定位是「行映射」跳变还是「列对齐」跳变。
    _diff = np.abs(np.diff(front_rgb, axis=0)).mean(axis=(1, 2))
    _k = int(np.argmax(_diff[:CELL_H - 1]))
    print(f"[diag] cell grid 行间差异最大在第 {_k} 行（差 {_diff[_k]:.4f}），"
          f"模型 y≈{Y1 - (_k + 0.5) / CELL_H * (Y1 - Y0):.3f}")
    _lo = max(0, _k - 4)
    print("[diag] 该处 rows:", np.round(rows[_lo:_k + 5], 1).tolist())
    print("[diag] 该处 dy  :", np.round(dy[_lo:_k + 5, 0], 1).tolist())
    print("[diag] rows 行差:", np.round(np.diff(rows[_lo:_k + 6]), 2).tolist())
    print("[diag] dy   行差:", np.round(np.diff(dy[_lo:_k + 6, 0]), 2).tolist())
    print("[diag] ramp 附近:", np.round(ramp[cell_rows[_lo:_k + 5]], 3).tolist())

    _mem("图集前")
    # 6. 图集：上半 2 大格（正/背），下半 4 小格（左/右/顶/底）
    #    ⚠ 格子不能重叠 —— 重叠过一次：侧格从第 1024 行开始写，
    #      把正面大格（1536 行）的下半截覆盖成了白色。
    assert LOW_Y >= CELL_H, "下排格子与上排重叠"
    assert BACK_X + CELL_W <= size, "背面格超出图集"
    assert LOW_W * 2 <= size and LOW_Y + LOW_H <= size, "下排格子超出图集"
    atlas = np.zeros((size, size, 3), dtype=np.float32)

    def blit(img, alpha, x0, y0, w, h, flip_x=False):
        im = img
        if flip_x:
            im = im[:, ::-1]
        H_, W_ = im.shape[:2]
        if (W_, H_) != (w, h):
            # ⚠ PIL resize 出来是 uint8 0..255，必须换算回 0..1 再写进图集，
            #   否则图集里存的是 248 而不是 0.97，存 PNG 时 ×255 被 clip 成纯白。
            im = np.asarray(Image.fromarray((np.clip(im, 0, 1) * 255)
                                           .astype(np.uint8)).resize((w, h))
                            ).astype(np.float32) / 255.0
        atlas[y0:y0 + h, x0:x0 + w] = im

    blit(front_rgb, front_a, 0, 0, CELL_W, CELL_H)                    # 正面
    blit(front_rgb, front_a, BACK_X, 0, CELL_W, CELL_H, flip_x=True)   # 背面（镜像）

    def edge_strips(rgb, alpha, side):
        """取角色轮廓边缘的颜色，做成沿 u（深度方向）渐变的条带 ——
        侧面的真实颜色参考图里看不到，用边缘色是最合理的近似。"""
        m = alpha > 0.5
        H_, W_ = m.shape
        out = np.zeros((H_, W_, 3), dtype=np.float32)
        ramp = np.linspace(0.0, 1.0, W_, dtype=np.float32)[None, :, None]
        for r in range(H_):
            xs_ = np.where(m[r])[0]
            if len(xs_) == 0:
                continue
            if side == "L":
                c0 = int(xs_.min())
                c1 = int(min(c0 + max(3, int(0.15 * len(xs_))), xs_.max()))
            else:
                c0 = int(xs_.max())
                c1 = int(max(c0 - max(3, int(0.15 * len(xs_))), xs_.min()))
            out[r, :] = (rgb[r, c0][None, :] * (1 - ramp[0])
                         + rgb[r, c1][None, :] * ramp[0])
        return out

    def skyline_strip(rgb, alpha, top=True, n=None):
        """顶/底格的内容：每个 x 位置取角色轮廓最上/最下方的像素色。

        返回 (n, n, 3)：行索引 = 深度 z 的分箱，列索引 = x 的分箱。
        ⚠ 必须是 (z × x) 索引，和顶/底组的 UV 参数化一致 ——
          之前条带是按「cell 行(y)」建的，UV 却用 z 去索引，坐标不自洽，
          渲染出来就是一片乱纹。"""
        m = alpha > 0.5
        H_, W_ = m.shape
        out = np.zeros((n, n, 3), dtype=np.float32)
        col_rgb = np.zeros((n, 3), dtype=np.float32)
        for c in range(W_):
            ys_ = np.where(m[:, c])[0]
            if len(ys_) == 0:
                continue
            r = int(ys_.min()) if top else int(ys_.max())
            ci = int(c / W_ * n)
            col_rgb[ci] = rgb[r, c]
        out[:] = col_rgb[None, :, :]
        return out

    def side_grid(rgb, alpha, side="L", n=None):
        """侧面格内容：索引 = (高度, 深度)。

        每一高度行取正面格里该行角色的左右轮廓，在这条轮廓内按深度比例扫一遍，
        得到「从侧后方到侧前方」的颜色渐变 —— 单图没有侧视参考，
        这是最接近的近似（比纯边缘色更连续，不会出现白斑）。"""
        m = alpha > 0.5
        H_, W_ = m.shape
        out = np.zeros((n, n, 3), dtype=np.float32)
        for ri in range(n):
            cr = int(ri * H_ / n)
            if cr >= H_:
                break
            xs_ = np.where(m[cr])[0]
            if len(xs_) == 0:
                continue
            c0, c1 = int(xs_.min()), int(xs_.max())
            if side == "R":
                c0, c1 = c1, c0
            for ci in range(n):
                c = c0 + int(ci * abs(c1 - c0) / max(n - 1, 1))
                out[ri, ci] = rgb[cr, np.clip(c, 0, W_ - 1)]
        return out

    side_h = LOW_H
    blit(side_grid(front_rgb, front_a, "L", LOW_W), front_a, 0, LOW_Y, LOW_W, side_h)
    blit(side_grid(front_rgb, front_a, "R", LOW_W), front_a, LOW_W, LOW_Y, LOW_W, side_h)
    blit(skyline_strip(front_rgb, front_a, True, LOW_W), front_a,
         BACK_X, LOW_Y, LOW_W, LOW_W)
    blit(skyline_strip(front_rgb, front_a, False, LOW_W), front_a,
         BACK_X + LOW_W, LOW_Y, LOW_W, LOW_W)
    print(f"[dbg] atlas 下排探针 {atlas[1600,100]} {atlas[1600,1300]} {atlas[1600,1800]}")

    _mem("图集后")
    # 7. 分组 + UV
    #    分组优先级：朝上/朝下的面 → 顶/底格；其余按视线方向分正/背。
    #    ⚠ 头顶圆顶几乎与视线平行，平面投影会把它压扁成摩尔纹，
    #      所以朝上的面单独投影（内容取角色轮廓的「天际线色」）。
    #    ⚠ 也不能纯按「法线主轴」分 6 组 —— 侧脸/侧发这类面占头部近一半，
    #      投影到侧格后会变成一片糊掉的边缘色（渲染出来是白斑）。
    v0, v1, v2 = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    if nrm is None:
        nrm = np.zeros_like(pos)
        for kk in range(3):
            np.add.at(nrm, idx[:, kk], fn)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    # ⚠ 顶/底阈值不能太松：发丝是细圆柱，切向面的小角度上翘就被判成「朝上」，
    #   整片头发会被投到顶格（内容是轮廓最上像素 = 白色发箍）→ 渲染出白色拉丝。
    #   0.85 只留真正的穹顶。
    is_top = fn[:, 1] > 0.85
    is_bot = fn[:, 1] < -0.85
    # ⚠ 侧面**不单独成组**。试过按 ±X 法线主轴分侧格：侧面占 32% 面数，
    #   侧格只有 768px 宽却要铺满整个裙摆深度 → 颜色被拉成竖条纹，
    #   裙子的金刺绣和围裙的小鲸鱼全糊掉。
    #   改成只按 ±Z 主视方向分正/背（深度缓冲自然遮挡），细节保留得更好。
    is_back = (~is_top) & (~is_bot) & (fn[:, 2] < 0)
    group = np.where(is_top, 2, np.where(is_bot, 3, np.where(is_back, 5, 4)))
    print("[grp ]  顶 %.1f%%  底 %.1f%%  正 %.1f%%  背 %.1f%%" % (
        100 * is_top.mean(), 100 * is_bot.mean(),
        100 * (group == 4).mean(), 100 * (group == 5).mean()))

    n_tris = len(idx)
    new_pos = pos[idx].reshape(-1, 3)
    new_nrm = nrm[idx].reshape(-1, 3)
    new_idx = np.arange(n_tris * 3, dtype=np.uint32).reshape(n_tris, 3)
    uv = np.zeros((n_tris * 3, 2), dtype=np.float64)

    # ⚠⚠ UV 必须**直接取自 cell grid**，不能用朴素 box projection 重算：
    #   正面格里的像素是按「逐行轮廓对齐 + PCHIP 纵向拉伸」光栅化出来的，
    #   而 UV 若按 (x,y) 线性映射，两套映射根本不是一回事 →
    #   渲染出来脸会整体错位（曾经就是这样：蝴蝶结跑到头顶）。
    #   cell grid 是唯一真值来源，UV 照抄它的采样结果。
    #   UV 指向「正面格里的像素」——正面格已经把参考图 warp 到模型投影域了，
    #   所以 cell 的 (行, 列) 索引就是 UV。⚠ 不能拿 cols2（参考图列号）当列号，
    #   那是另一套坐标，会把纹理整体错位（蝴蝶结跑到头顶就是这么来的）。
    # ⚠ glTF 纹理原点在**左上**（v=0 是图像顶行）—— 写成 1.0-cr/size 会整张
    #   贴图上下颠倒，渲染时头顶显示的是胸口的蝴蝶结。
    for t in np.where(group == 4)[0]:                       # 正面 (+Z)
        for kk in range(3):
            vi = int(idx[t, kk])
            cr, cc = cell_rows_v[vi], cell_cols_v[vi]
            uv[t * 3 + kk] = (cc / size, cr / size)
    for t in np.where(group == 5)[0]:                       # 背面 (-Z)，镜像
        for kk in range(3):
            vi = int(idx[t, kk])
            cr, cc = cell_rows_v[vi], cell_cols_v[vi]
            uv[t * 3 + kk] = ((BACK_X + (CELL_W - 1 - cc)) / size, cr / size)
    zmin, zmax = pos[:, 2].min(), pos[:, 2].max()
    for t in np.where((group == 6) | (group == 7))[0]:      # 左/右侧面 (±X)
        left = group[t] == 6
        for kk in range(3):
            vi = int(idx[t, kk])
            u = (pos[vi, 2] - zmin) / max(zmax - zmin, 1e-9)     # 深度 → 列
            v = (pos[vi, 1] - Y0) / max(Y1 - Y0, 1e-9)          # 高度 → 行
            px = (0.0 if left else LOW_W) + u * LOW_W
            py = LOW_Y + (1.0 - v) * LOW_H
            uv[t * 3 + kk] = (px / size, py / size)

    for t in np.where((group == 2) | (group == 3))[0]:      # 顶/底 (±Y)
        top = group[t] == 2
        for kk in range(3):
            vi = int(idx[t, kk])
            u = (pos[vi, 0] - X0) / (X1 - X0)          # x → 列
            w = (pos[vi, 2] - zmin) / (zmax - zmin)    # z → 行
            px = (BACK_X if top else BACK_X + LOW_W) + u * LOW_W
            py = LOW_Y + (1.0 - w) * LOW_W
            uv[t * 3 + kk] = (px / size, py / size)

    # 8. 顶点色（不读贴图的查看器兜底）
    # ⚠ glTF 的 uv.y=0 在图像**底部**，而 atlas 数组行 0 在顶部。
    #   采样时必须用 (1 - v) 换算，否则顶点色上下颠倒 —— 渲染就会在头顶
    #   显示胸口的蝴蝶结。这是个静默错误：UV 全对，只有顶点色错。
    def _sample_atlas(a):
        # glTF 纹理原点在**左上**：uv.v=0 → 图像第 0 行
        _c = np.clip((uv[:, 0] * size).astype(int), 0, size - 1)
        _r = np.clip((uv[:, 1] * size).astype(int), 0, size - 1)
        return np.clip(a[_r, _c], 0, 1)

    samp = np.clip((uv * size).astype(int), 0, size - 1)
    new_col = _sample_atlas(atlas)

    # 8b. 按压缩率预滤波贴图（等价于给这张贴图生成 mipmap）
    #     度量：区域累计 UV 面积 / 可见 UV 面积 —— 细发丝层层重叠的地方
    #     贴图被过度采样，缩小采样必然出摩尔纹。
    uv_tex = uv * size
    p0 = uv_tex[idx[:, 0]]
    p1 = uv_tex[idx[:, 1]]
    p2 = uv_tex[idx[:, 2]]
    a_uv = 0.5 * np.abs((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1])
                        - (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0]))
    comp = rasterize_area_ratio(uv_tex, new_idx, a_uv, size, new_pos[:, 2])
    print(f"[flt ] 区域压缩率 最大 {comp.max():.1f} / "
          f"高压缩像素占比 {100*(comp>2.0).mean():.1f}%")
    atlas = prefilter_by_compression(atlas, comp)
    new_col = _sample_atlas(atlas)

    # 9. 贴图 PNG
    img = np.clip(atlas * 255.0 + 0.5, 0, 255).astype(np.uint8)
    png_path = os.path.join(outdir, "whale-chan-i2d-basecolor.png")
    Image.fromarray(img).save(png_path, optimize=True)
    with open(png_path, "rb") as f:
        png_bytes = f.read()
    print(f"[tex] {png_path}  {len(png_bytes):,} bytes")
    Image.fromarray((np.clip(front_rgb, 0, 1) * 255).astype(np.uint8)).save(
        os.path.join(outdir, "debug_front_aligned.png"))

    # 9b. 诊断叠加图：把模型顶点在参考图上的「实际采样位置」画出来
    #     （灰=全部顶点，红=头部顶点，蓝=采到肤色的顶点）
    _cr = np.clip(np.round((Y1 - pos[:, 1]) / max(Y1 - Y0, 1e-9) * CELL_H - 0.5
                           ).astype(int), 0, CELL_H - 1)
    _cc = np.clip(np.round((pos[:, 0] - X0) / max(X1 - X0, 1e-9) * CELL_W - 0.5
                           ).astype(int), 0, CELL_W - 1)
    _vr = ref_row_of_bin[cell_rows][_cr]
    _vc = cols2[_cr, _cc]
    _dbg = Image.fromarray((np.clip(ref, 0, 1) * 255).astype(np.uint8)).convert("RGB")
    _ov = Image.new("RGBA", _dbg.size, (0, 0, 0, 0))
    _dd = ImageDraw.Draw(_ov)
    for a, b in zip(_vc, _vr):
        _dd.ellipse([a - 0.9, b - 0.9, a + 0.9, b + 0.9], fill=(255, 255, 255, 90))
    _head = pos[:, 1] > 2.2
    for a, b in zip(_vc[_head], _vr[_head]):
        _dd.ellipse([a - 1.3, b - 1.3, a + 1.3, b + 1.3], fill=(255, 0, 0, 210))
    _skin = (_vc >= 0) & (_vc < ref.shape[1]) & (_vr >= 0) & (_vr < ref.shape[0])
    _sk = np.zeros(len(_vc), dtype=bool)
    if _skin.any():
        _c = np.clip(_vc[_skin].astype(int), 0, ref.shape[1] - 1)
        _r = np.clip(_vr[_skin].astype(int), 0, ref.shape[0] - 1)
        px = ref[_r, _c]
        _sk[_skin] = (px[:, 0] > 0.72) & (px[:, 0] > px[:, 2] + 0.05) & (px[:, 1] > 0.5)
    for a, b in zip(_vc[_sk], _vr[_sk]):
        _dd.ellipse([a - 1.6, b - 1.6, a + 1.6, b + 1.6], fill=(0, 120, 255, 230))
    Image.alpha_composite(_dbg.convert("RGBA"), _ov).convert("RGB").save(
        os.path.join(outdir, "debug_sampling_overlay.png"))
    print(f"[diag] 模型顶点 {len(_vc):,}，头部顶点 {int(_head.sum()):,}，"
          f"采到肤色的 {int(_sk.sum()):,}（{_sk.sum()/max(len(_vc),1)*100:.1f}%）")

    # 10. 组装 GLB
    N = len(new_pos)
    blobs, views = [], []

    def add_view(data, target=None):
        cur = sum(len(b) for b in blobs)
        pad = (4 - cur % 4) % 4
        if pad:
            blobs.append(b"\x00" * pad)
            cur += pad
        views.append({"buffer": 0, "byteOffset": cur,
                      "byteLength": len(data), "target": target})
        blobs.append(data)
        return len(views) - 1

    pos_bv = add_view(new_pos.astype(np.float32).tobytes(), 34962)
    nrm_bv = add_view(new_nrm.astype(np.float32).tobytes(), 34962)
    uv_bv = add_view(uv.astype(np.float32).tobytes(), 34962)
    col_b = np.empty((N, 4), dtype=np.uint8)
    col_b[:, :3] = np.clip(new_col * 255.0 + 0.5, 0, 255).astype(np.uint8)
    col_b[:, 3] = 255
    col_bv = add_view(col_b.tobytes(), 34962)
    idx_bv = add_view(new_idx.astype(np.uint32).tobytes(), 34963)
    img_bv = add_view(png_bytes)

    g["accessors"] = []

    def acc(bv, ct, count, atype, target=None, mins=None, maxs=None):
        a = {"bufferView": bv, "componentType": ct, "count": count, "type": atype}
        if target:
            a["target"] = target
        if mins is not None:
            a["min"], a["max"] = mins, maxs
        g["accessors"].append(a)
        return len(g["accessors"]) - 1

    a_pos = acc(pos_bv, 5126, N, "VEC3", 34962,
                new_pos.min(axis=0).tolist(), new_pos.max(axis=0).tolist())
    a_nrm = acc(nrm_bv, 5126, N, "VEC3", 34962)
    a_uv = acc(uv_bv, 5126, N, "VEC2", 34962)
    a_col = acc(col_bv, 5121, N, "VEC4", 34962)
    a_idx = acc(idx_bv, 5125, n_tris * 3, "SCALAR", 34963)

    g["bufferViews"] = views
    g["buffers"] = [{"byteLength": sum(len(b) for b in blobs)}]
    g["images"] = [{"bufferView": img_bv, "mimeType": "image/png"}]
    g["samplers"] = [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 10497, "wrapT": 10497}]
    g["textures"] = [{"source": 0, "sampler": 0}]
    g["materials"] = [{
        "name": "WhaleChan_ReferenceProjected",
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.0, "roughnessFactor": 0.68},
        "doubleSided": True,
    }]
    g["meshes"] = [{"name": "whale-chan-i2d", "primitives": [{
        "attributes": {"POSITION": a_pos, "NORMAL": a_nrm,
                       "TEXCOORD_0": a_uv, "COLOR_0": a_col},
        "indices": a_idx, "material": 0, "mode": 4}]}]
    g["scene"] = 0
    g["scenes"] = [{"nodes": [0]}]
    g["nodes"] = [{"mesh": 0, "name": "whale-chan-i2d"}]
    g["asset"] = {"version": "2.0",
                  "generator": "retexture_ref.py (reference-projected UV)"}

    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bb = b"".join(blobs)
    bb += b"\x00" * ((4 - len(bb) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bb)
    out_glb = os.path.join(outdir, "whale-chan-i2d.glb")
    with open(out_glb, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<II", len(js), JSON_CH)); f.write(js)
        f.write(struct.pack("<II", len(bb), BIN_CH)); f.write(bb)
    print(f"[glb] {out_glb}  {os.path.getsize(out_glb):,} bytes")

    meta = {"flip": bool(flip), "iou": round(float(sc), 4),
            "fx": fx, "fy": fy, "tx": tx, "ty": ty,
            "ref_bbox": [int(v) for v in rbox],
            "model_bbox": [float(X0), float(Y0), float(X1), float(Y1)]}
    with open(os.path.join(outdir, "registration.json"), "w") as f:
        json.dump(meta, f, indent=2)


if __name__ == "__main__":
    main()
