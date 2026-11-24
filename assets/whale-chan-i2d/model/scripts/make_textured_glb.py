#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_textured_glb.py —— 自包含生成「带 UV + 真实贴图」的 GLB

为什么不用 Blender 的 smart UV project：
  TripoSR 出来的是 marching cubes 网格（99,154 个碎片三角形），
  smart project 会把它拆成几万个小 UV 岛 —— 实测贴图空间利用率仅 **6.2%**，
  贴图退化成马赛克。

本脚本的做法（逐面 box projection，全 numpy，不依赖 Blender）：
  1. 读源 GLB：POSITION / NORMAL / COLOR_0 / indices
  2. 逐三角面算法线，按主轴分到 6 组（±X / ±Y / ±Z）
  3. 每组投影到对应的 2D 平面，各占贴图的 1/6 区域（2 列 × 3 行）
  4. 把顶点按 face-corner 展开（glTF 的 UV 是 per-vertex，
     而 box mapping 是 per-face → 必须拆点，否则 UV 在硬边处串味）
  5. numpy 光栅化出贴图（带深度缓冲）
  6. 组装完整 glTF：buffers / accessors / bufferViews / image / sampler /
     texture / material(baseColorTexture) / mesh / primitive
  7. 同时保留 COLOR_0 顶点色（部分查看器只读它）

  ※ 因为贴图内容是「烘焙顶点色」得来的，UV 的拉伸完全不影响正确性，
    只影响把贴图当独立图片看时的观感。

用法：python make_textured_glb.py <src.glb> <outdir> [tex_size] [sat]
"""
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_CT = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
JSON_CH = 0x4E4F534A
BIN_CH = 0x004E4942


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
    # normalized 的整数 accessor 要换算到 0..1 —— Blender 导出顶点色会用
    # UNSIGNED_SHORT normalized（值域 0..65535），漏掉这一步颜色会放大 256 倍。
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


def rgb2hsv(a):
    mx, mn = a.max(axis=1), a.min(axis=1)
    d = mx - mn
    r, g, b = a[:, 0], a[:, 1], a[:, 2]
    h = np.zeros_like(mx)
    nz = d > 1e-8
    m = nz & (mx == r); h[m] = ((g[m] - b[m]) / d[m]) % 6.0
    m = nz & (mx == g); h[m] = ((b[m] - r[m]) / d[m]) + 2.0
    m = nz & (mx == b); h[m] = ((r[m] - g[m]) / d[m]) + 4.0
    h = (h / 6.0) % 1.0
    s = np.where(mx > 1e-8, d / np.maximum(mx, 1e-8), 0.0)
    return np.stack([h, s, mx], axis=1)


def hsv2rgb(hsv):
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    i = np.floor(h * 6.0).astype(int) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    out = np.zeros_like(hsv)
    for k, (rr, gg, bb) in enumerate([(v, t, p), (q, v, p), (p, v, t),
                                      (p, q, v), (t, p, v), (v, p, q)]):
        m = i == k
        out[m, 0] = rr[m]; out[m, 1] = gg[m]; out[m, 2] = bb[m]
    return out


def main():
    src, outdir = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 2048
    sat = float(sys.argv[4]) if len(sys.argv) > 4 else 1.75
    os.makedirs(outdir, exist_ok=True)

    # ── 1. 读源 GLB ──
    g, buf = load_glb(src)
    prim = g["meshes"][0]["primitives"][0]
    pos = read_accessor(g, buf, prim["attributes"]["POSITION"])[:, :3]
    if "NORMAL" in prim["attributes"]:
        nrm = read_accessor(g, buf, prim["attributes"]["NORMAL"])[:, :3]
    else:
        nrm = None      # TripoSR 原始 GLB 没有法线，下面从面法线聚合
    col = read_accessor(g, buf, prim["attributes"]["COLOR_0"])[:, :3]
    idx = read_accessor(g, buf, prim["indices"]).reshape(-1, 3).astype(np.int64)
    if col.max() > 1.5:
        col = col / 255.0
    col = np.clip(col, 0, 1)
    print(f"[in ]   {len(pos):,} 顶点 / {len(idx):,} 面")
    rng = pos.max(axis=0) - pos.min(axis=0)
    print(f"[in ]   包围盒 X{rng[0]:.2f} Y{rng[1]:.2f} Z{rng[2]:.2f}"
          f"  → Y 垂直 / Z 深度")

    # ── 2. 逐面法线 + 主轴分组 ──
    v0, v1, v2 = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    if nrm is None:
        # 面积加权聚合面法线 → 顶点法线（TripoSR 原始 GLB 不带法线）
        nrm = np.zeros_like(pos)
        for k in range(3):
            np.add.at(nrm, idx[:, k], fn)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        print(f"[nrm ]  由 {len(fn):,} 个面法线聚合得到顶点法线")
    axis = np.argmax(np.abs(fn), axis=1)
    sign = np.sign(fn[np.arange(len(fn)), axis])
    group = axis * 2 + (sign < 0).astype(int)      # 0..5
    # 投影平面：axis0→(Y,Z) axis1→(X,Z) axis2→(X,Y)
    plane = {0: (1, 2), 1: (0, 2), 2: (0, 1)}
    # 格子：2 列 × 3 行
    CELL = [(c, r) for r in range(3) for c in range(2)]

    # ── 3. 各组 bbox ──
    bounds = {}
    for gsel in range(6):
        m = group == gsel
        if not m.any():
            continue
        a, b = plane[gsel // 2]
        p = np.concatenate([v0[m], v1[m], v2[m]])
        bounds[gsel] = (p[:, a].min(), p[:, a].max(),
                         p[:, b].min(), p[:, b].max())
    for gsel, bb in bounds.items():
        print(f"[grp ]  组{gsel}  ({'XYZ'[gsel//2]}{'+-'.split('-')[gsel%2]})  "
              f"bbox=({bb[0]:.3f},{bb[2]:.3f})-({bb[1]:.3f},{bb[3]:.3f})")

    # ── 4. 拆点（per-corner）+ box UV ──
    n_tris = len(idx)
    new_pos = pos[idx].reshape(-1, 3)
    new_nrm = nrm[idx].reshape(-1, 3)
    new_col = col[idx].reshape(-1, 3)
    new_idx = np.arange(n_tris * 3, dtype=np.uint32).reshape(n_tris, 3)

    uv = np.zeros((n_tris * 3, 2), dtype=np.float64)
    margin = 0.006
    cw = size / 2.0
    ch = size / 3.0
    for gsel, (cx, ry) in ((g, CELL[g]) for g in bounds):
        a, b = plane[gsel // 2]
        x0, x1, y0, y1 = bounds[gsel]
        ex = max(x1 - x0, 1e-6)
        ey = max(y1 - y0, 1e-6)
        m = group == gsel
        tri_idx = np.where(m)[0]
        # 这组每个三角形的 3 个 corner
        for t in tri_idx:
            for k in range(3):
                vi = int(idx[t, k])
                u = (pos[vi, a] - x0) / ex
                v = (pos[vi, b] - y0) / ey
                px = cx * cw + margin * cw + u * cw * (1 - 2 * margin)
                py = ry * ch + margin * ch + v * ch * (1 - 2 * margin)
                uv[t * 3 + k] = (px / size, py / size)

    # ── 5. 光栅化贴图 ──
    # Blender 的 Color Attribute 节点输出 **sRGB 编码值并当线性值用**
    # （实测：BYTE_COLOR=0.5 → 渲染出 130/255，未被线性化）；
    # 而 **PNG 贴图会被 Blender 线性化**（sRGB→linear）。
    # 两条路要对齐，PNG 里必须把 HSV 结果"再 sRGB 编码一次"：
    #     顶点色 sRGB → HSV(S) → res（= 顶点色版的 Base Color）
    #     PNG 存 lin2srgb(res) → Blender 线性化 → 正好还原 res
    hsv = rgb2hsv(new_col)
    hsv[:, 1] = np.clip(hsv[:, 1] * sat, 0, 1)
    new_col = lin2srgb(hsv2rgb(hsv))

    P = uv * size
    tex = np.zeros((size, size, 3), dtype=np.float32)
    # 深度：相机在 Blender -Y → export_yup 映射 (x,y,z)→(x,z,-y)
    #       ⇒ glTF Z 越大越近，z-buffer 要保留**最大** Z。
    #       （一开始写成保留最小 Z，等于留下最远的面，贴图满屏黑洞。）
    zbuf = np.full((size, size), -np.inf, dtype=np.float32)
    depth = new_pos[:, 2]

    t0, t1, t2 = new_idx[:, 0], new_idx[:, 1], new_idx[:, 2]
    px0, py0 = P[t0, 0], P[t0, 1]
    px1, py1 = P[t1, 0], P[t1, 1]
    px2, py2 = P[t2, 0], P[t2, 1]
    minx = np.maximum(np.minimum(np.minimum(px0, px1), px2).astype(int), 0)
    maxx = np.minimum(np.maximum(np.maximum(px0, px1), px2).astype(int) + 2, size)
    miny = np.maximum(np.minimum(np.minimum(py0, py1), py2).astype(int), 0)
    maxy = np.minimum(np.maximum(np.maximum(py0, py1), py2).astype(int) + 2, size)

    for t in range(n_tris):
        x0, x1, y0, y1 = minx[t], maxx[t], miny[t], maxy[t]
        if x1 <= x0 or y1 <= y0:
            continue
        ax, ay = px0[t], py0[t]
        bx, by = px1[t], py1[t]
        cx, cy = px2[t], py2[t]
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            continue
        gx = (np.arange(x0, x1, dtype=np.float64) + 0.5)[None, :]
        gy = (np.arange(y0, y1, dtype=np.float64) + 0.5)[:, None]
        l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / det
        l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / det
        l2 = 1.0 - l0 - l1
        inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        if not inside.any():
            continue
        zz = l0 * depth[t0[t]] + l1 * depth[t1[t]] + l2 * depth[t2[t]]
        sub_z = zbuf[y0:y1, x0:x1]
        upd = inside & (zz > sub_z)
        if not upd.any():
            continue
        for c in range(3):
            v = l0 * new_col[t0[t], c] + l1 * new_col[t1[t], c] + l2 * new_col[t2[t], c]
            st = tex[y0:y1, x0:x1]
            st[:, :, c][upd] = v[upd]
        sub_z[upd] = zz[upd]
        if (t + 1) % 20000 == 0:
            print(f"       {t+1:,}/{n_tris:,} 面")

    cov = (zbuf < np.inf).mean()
    print(f"[tex ]  覆盖率 {100*cov:.1f}%  ({size}²)")
    png_path = os.path.join(outdir, "whale-chan-i2d-basecolor.png")
    img = np.clip(tex * 255.0 + 0.5, 0, 255).astype(np.uint8)
    # 轻微模糊：box projection 在硬边处 UV 不连续，边缘像素插值会出彩色杂点
    from PIL import ImageFilter
    img = np.asarray(Image.fromarray(img).filter(
        ImageFilter.GaussianBlur(radius=0.7)))
    Image.fromarray(img).save(png_path, optimize=True)
    with open(png_path, "rb") as f:
        png_bytes = f.read()
    print(f"[tex ]  {png_path}  {len(png_bytes):,} bytes")

    # ── 6. 组装 GLB ──
    N = len(new_pos)
    T = len(new_idx)
    blobs = []
    views = []

    def add_view(data, target=None):
        # bufferView 的 byteOffset 必须 4 字节对齐 —— 对齐要按**字节数**算，
        # 不能按 blob 块数（踩过：len(blobs) % 4 → 产出的 GLB Blender 读不了）
        cur = sum(len(b) for b in blobs)
        pad = (4 - cur % 4) % 4
        if pad:
            blobs.append(b"\x00" * pad)
            cur += pad
        off = cur
        blobs.append(data)
        views.append({"buffer": 0, "byteOffset": off,
                      "byteLength": len(data), "target": target})
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

    def acc(bv, ct, count, atype, target, mins=None, maxs=None):
        a = {"bufferView": bv, "componentType": ct, "count": count,
             "type": atype}
        if target:
            a["target"] = target
        if mins is not None:
            a["min"] = mins
            a["max"] = maxs
        g["accessors"].append(a)
        return len(g["accessors"]) - 1

    g["accessors"] = []
    a_pos = acc(pos_bv, 5126, N, "VEC3", 34962,
                new_pos.min(axis=0).tolist(), new_pos.max(axis=0).tolist())
    a_nrm = acc(nrm_bv, 5126, N, "VEC3", 34962)
    a_uv = acc(uv_bv, 5126, N, "VEC2", 34962)
    a_col = acc(col_bv, 5121, N, "VEC4", 34962)
    a_idx = acc(idx_bv, 5125, T * 3, "SCALAR", 34963)

    g["bufferViews"] = views
    g["buffers"] = [{"byteLength": sum(len(b) for b in blobs)}]
    g["images"] = [{"bufferView": img_bv, "mimeType": "image/png"}]
    g["samplers"] = [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 10497, "wrapT": 10497}]
    g["textures"] = [{"source": 0, "sampler": 0}]
    g["materials"] = [{
        "name": "WhaleChan_Textured",
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.0, "roughnessFactor": 0.62},
        "doubleSided": True,
    }]
    g["meshes"] = [{"name": "whale-chan-i2d", "primitives": [{
        "attributes": {"POSITION": a_pos, "NORMAL": a_nrm,
                       "TEXCOORD_0": a_uv, "COLOR_0": a_col},
        "indices": a_idx, "material": 0, "mode": 4}]}]
    g["scene"] = 0
    g["scenes"] = [{"nodes": [0]}]
    g["nodes"] = [{"mesh": 0, "name": "whale-chan-i2d"}]
    # asset.version 是 glTF 规范**必填**字段 —— 漏了 Blender 会直接报
    # "Bad glTF: no version"（这个报错指的是 asset.version，不是文件头）
    g["asset"] = {"version": "2.0",
                  "generator": "make_textured_glb.py (box-projection UV)"}

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
    print(f"[glb]  {out_glb}  {os.path.getsize(out_glb):,} bytes")


if __name__ == "__main__":
    main()
