#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
despeckle_glb.py —— 清除三角网格顶点色里的孤立"色点"

问题：TripoSR 单图重建会在肩胸/领口位置留下少量高饱和洋红色顶点
     （实测 126 个 / 49,577，占 0.3%）。数量虽少，但因顶点色在渲染时按面插值，
     它们会染出一大片紫红斑块，把脸和白色蕾丝领口搞脏。

做法（纯 numpy，不依赖 Blender）：
  1. 从 GLB 的 indices 建顶点邻接表（三角面共享边）
  2. 判定"洋红色点"：色相落在洋红/品红区 且 饱和度高于阈值
     —— 角色的合法暖色只有皮肤（低饱和淡粉，S<0.30）与金色（S 更低），
        所以 S>0.30 的洋红一定是错误色
  3. 用**邻居顶点的平均色**替换这些色点（抹平，而非硬改成某个颜色）
  4. 直接写回 GLB 的 COLOR_0

用法：python despeckle_glb.py <in.glb> <out.glb> [s_thresh]
"""
import json
import os
import struct
import sys

import numpy as np

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
    return arr.reshape(a["count"], _NC[a["type"]]).astype(np.float64)


def write_glb(path, g, bin_chunk):
    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bb = bytes(bin_chunk) + b"\x00" * ((4 - len(bin_chunk) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bb)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<II", len(js), JSON_CH)); f.write(js)
        f.write(struct.pack("<II", len(bb), BIN_CH)); f.write(bb)


def set_colors(g, buf, prim, colors):
    ai = prim["attributes"]["COLOR_0"]
    a = g["accessors"][ai]
    bv = g["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ct, nc = a["componentType"], _NC[a["type"]]
    if ct == 5126:
        arr = np.empty((a["count"], nc), dtype=np.float32)
        arr[:, :3] = colors.astype(np.float32)
        if nc >= 4: arr[:, 3] = 1.0
        new = arr.tobytes()
    elif ct == 5121:
        arr = np.empty((a["count"], nc), dtype=np.uint8)
        arr[:, :3] = np.clip(colors * 255.0, 0, 255).astype(np.uint8)
        if nc >= 4: arr[:, 3] = 255
        new = arr.tobytes()
    else:
        raise RuntimeError(f"COLOR_0 componentType={ct}")
    b = bytearray(buf)
    b[off:off + len(new)] = new
    return bytes(b)


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
    return h, s, mx


def main():
    src, dst = sys.argv[1], sys.argv[2]
    s_thresh = float(sys.argv[3]) if len(sys.argv) > 3 else 0.30

    g, buf = load_glb(src)
    prim = g["meshes"][0]["primitives"][0]
    col = read_accessor(g, buf, prim["attributes"]["COLOR_0"])[:, :3]
    if col.max() > 1.5:
        col = col / 255.0
    col = np.clip(col, 0, 1)
    idx = read_accessor(g, buf, prim["indices"]).reshape(-1, 3).astype(np.int64)

    # ── 顶点邻接表（三角面共享边）──
    nbr = [[] for _ in range(len(col))]
    for t in idx:
        a, b, c = int(t[0]), int(t[1]), int(t[2])
        nbr[a] += (b, c); nbr[b] += (a, c); nbr[c] += (a, b)

    h, s, v = rgb2hsv(col)
    # 判定规则（基于实测色相直方图）：
    #   主色是蓝 H 0.55~0.65（占 76%）；
    #   H>=0.68 的紫/洋红 一定是错误色 —— 参考图里没有紫；
    #   H<=0.05 的暖色要分情况：S>0.35 的饱和红是错误，S 低的是皮肤，保留。
    mag = ((h >= 0.68) & (s > s_thresh)) | ((h <= 0.05) & (s > 0.35))
    bad = np.where(mag)[0]
    print(f"[scan]  错误色点 {len(bad)} / {len(col):,} ({100*mag.mean():.2f}%)  "
          f"[紫洋红 {(s_thresh):.2f}]")

    fixed = 0
    for vi in bad:
        nb = [n for n in nbr[vi] if not mag[n]]
        if nb:
            col[vi] = col[nb].mean(axis=0)
            fixed += 1
        else:
            # 整圈都是洋红 → 拉向蓝并降饱和
            col[vi] = (col[vi][0] * 0.6, col[vi][1] * 0.75, col[vi][2] * 1.0)
            fixed += 1
    print(f"[fix ]  已抹平 {fixed} 个色点")

    buf2 = set_colors(g, buf, prim, col)
    write_glb(dst, g, buf2)
    print(f"[out ]  {dst}  {os.path.getsize(dst):,} bytes")


if __name__ == "__main__":
    main()
