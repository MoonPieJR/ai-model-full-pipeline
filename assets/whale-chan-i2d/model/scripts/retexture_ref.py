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
    r_lo = np.clip(np.round(fy * y_hi + ty).astype(int), 0, len(rx0) - 1)
    r_hi = np.clip(np.round(fy * y_lo + ty).astype(int), 0, len(rx0) - 1)
    rx0_bin = np.full(NB, np.nan)
    rx1_bin = np.full(NB, np.nan)
    for i in range(NB):
        a, b = min(r_lo[i], r_hi[i]), max(r_lo[i], r_hi[i])
        seg0, seg1 = rx0[a:b + 1], rx1[a:b + 1]
        ok = seg1 >= 0
        if ok.any():
            rx0_bin[i] = seg0[ok].min()
            rx1_bin[i] = seg1[ok].max()
    for arr in (rx0_bin, rx1_bin):
        bad = ~np.isfinite(arr)
        if bad.any():
            good = np.where(~bad)[0]
            arr[bad] = np.interp(np.where(bad)[0], good, arr[good])
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
    cols2 = fx * xj_f[None, :] + tx + dy
    rows = fy * (Y1 - (np.arange(CELL_H) + 0.5) / CELL_H * (Y1 - Y0)) + ty
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

    def skyline_strips(rgb, alpha, top=True):
        """每个 x 位置取角色轮廓最上/最下方的像素色 —— 顶/底格的内容。
        参考图只有正面视角，顶面只能这样近似（头顶=呆毛/发箍色，底部=鞋色）。"""
        m = alpha > 0.5
        H_, W_ = m.shape
        out = np.zeros((H_, W_, 3), dtype=np.float32)
        for c in range(W_):
            ys_ = np.where(m[:, c])[0]
            if len(ys_) == 0:
                continue
            r = int(ys_.min()) if top else int(ys_.max())
            out[:, c] = rgb[r, c]
        return out

    side_h = LOW_H
    blit(edge_strips(front_rgb, front_a, "L"), front_a, 0, LOW_Y, LOW_W, side_h)
    blit(edge_strips(front_rgb, front_a, "R"), front_a, LOW_W, LOW_Y, LOW_W, side_h)
    blit(skyline_strips(front_rgb, front_a, True), front_a,
         BACK_X, LOW_Y, LOW_W, LOW_W)
    blit(skyline_strips(front_rgb, front_a, False), front_a,
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
    is_top = fn[:, 1] > 0.60
    is_bot = fn[:, 1] < -0.60
    is_back = (~is_top) & (~is_bot) & (fn[:, 2] < -0.05)
    group = np.where(is_top, 2, np.where(is_bot, 3, np.where(is_back, 5, 4)))
    print("[grp ]  顶 %.1f%%  底 %.1f%%  正 %.1f%%  背 %.1f%%" % (
        100 * is_top.mean(), 100 * is_bot.mean(),
        100 * (group == 4).mean(), 100 * (group == 5).mean()))

    n_tris = len(idx)
    new_pos = pos[idx].reshape(-1, 3)
    new_nrm = nrm[idx].reshape(-1, 3)
    new_idx = np.arange(n_tris * 3, dtype=np.uint32).reshape(n_tris, 3)
    uv = np.zeros((n_tris * 3, 2), dtype=np.float64)

    for t in np.where(group == 4)[0]:                       # 正面 (+Z)
        for kk in range(3):
            vi = int(idx[t, kk])
            u = (pos[vi, 0] - X0) / (X1 - X0)
            w = (pos[vi, 1] - Y0) / (Y1 - Y0)
            px, py = u * CELL_W, (1.0 - w) * CELL_H
            uv[t * 3 + kk] = (px / size, 1.0 - py / size)
    for t in np.where(group == 5)[0]:                       # 背面 (-Z)，镜像
        for kk in range(3):
            vi = int(idx[t, kk])
            u = 1.0 - (pos[vi, 0] - X0) / (X1 - X0)
            w = (pos[vi, 1] - Y0) / (Y1 - Y0)
            px, py = BACK_X + u * CELL_W, (1.0 - w) * CELL_H
            uv[t * 3 + kk] = (px / size, 1.0 - py / size)
    zmin, zmax = pos[:, 2].min(), pos[:, 2].max()
    for t in np.where((group == 2) | (group == 3))[0]:      # 顶/底 (±Y)
        top = group[t] == 2
        for kk in range(3):
            vi = int(idx[t, kk])
            u = (pos[vi, 0] - X0) / (X1 - X0)
            w = (pos[vi, 2] - zmin) / (zmax - zmin)
            px = (BACK_X if top else BACK_X + LOW_W) + u * LOW_W
            py = LOW_Y + (1.0 - w) * LOW_W
            uv[t * 3 + kk] = (px / size, 1.0 - py / size)

    # 8. 顶点色（不读贴图的查看器兜底）
    samp = np.clip((uv * size).astype(int), 0, size - 1)
    new_col = np.clip(atlas[samp[:, 1], samp[:, 0]], 0, 1)

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
    samp = np.clip((uv * size).astype(int), 0, size - 1)
    new_col = np.clip(atlas[samp[:, 1], samp[:, 0]], 0, 1)

    # 9. 贴图 PNG
    img = np.clip(atlas * 255.0 + 0.5, 0, 255).astype(np.uint8)
    png_path = os.path.join(outdir, "whale-chan-i2d-basecolor.png")
    Image.fromarray(img).save(png_path, optimize=True)
    with open(png_path, "rb") as f:
        png_bytes = f.read()
    print(f"[tex] {png_path}  {len(png_bytes):,} bytes")
    Image.fromarray((np.clip(front_rgb, 0, 1) * 255).astype(np.uint8)).save(
        os.path.join(outdir, "debug_front_aligned.png"))

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
