#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鲸鱼娘 Image-to-3D 版 —— 独立验收脚本

不依赖 Blender，直接对最终产物做结构级检查。
用法： python3 verify_i2d.py [--root <目录>]
"""
import argparse
import hashlib
import json
import os
import struct
import sys

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def check(name, ok, detail="", level=None):
    level = level or (PASS if ok else FAIL)
    results.append((level, name, detail))
    print(f"  [{level}] {name}" + (f"  — {detail}" if detail else ""))
    return ok


# ── GLB 解析 ──
def parse_glb(path):
    with open(path, "rb") as f:
        magic, version, length = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError(f"bad magic {magic!r}")
        chunks = {}
        while f.tell() < length:
            clen, ctype = struct.unpack("<II", f.read(8))
            chunks[ctype] = f.read(clen)
        return version, json.loads(chunks[0x4E4F534A].decode("utf-8"))


def glb_stats(path):
    version, g = parse_glb(path)
    prims = []
    for mesh in g.get("meshes", []):
        for p in mesh.get("primitives", []):
            prims.append(p)
    nverts = ntris = 0
    has_color = False
    for p in prims:
        attrs = p.get("attributes", {})
        if "COLOR_0" in attrs:
            has_color = True
            nverts = max(nverts, g["accessors"][attrs["COLOR_0"]]["count"])
        if "POSITION" in attrs:
            nverts = max(nverts, g["accessors"][attrs["POSITION"]]["count"])
        if "indices" in p:
            ntris += g["accessors"][p["indices"]]["count"] // 3
    mats = [m.get("name", "?") for m in g.get("materials", [])]
    has_uv = any("TEXCOORD_0" in p.get("attributes", {}) for p in prims)
    has_tex = any("baseColorTexture" in
                  m.get("pbrMetallicRoughness", {}) for m in g.get("materials", []))
    embedded = any("bufferView" in im for im in g.get("images", []))
    tex_names = [str(t) for t in g.get("textures", [])]
    return dict(version=version, nprims=len(prims), nverts=nverts, ntris=ntris,
                has_color=has_color, nmat=len(mats), mats=mats,
                nmesh=len(g.get("meshes", [])), nimg=len(g.get("images", [])),
                has_uv=has_uv, has_tex=has_tex, embedded_tex=embedded,
                tex_names=tex_names)


# ── PNG 尺寸 ──
def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not png")
    w, h = struct.unpack(">II", head[16:24])
    return w, h


# ── MP4 box 探测（不依赖 ffprobe）──
def mp4_probe(path):
    boxes = []
    with open(path, "rb") as f:
        data = f.read()
    off = 0
    while off + 8 <= len(data):
        size = struct.unpack(">I", data[off:off + 4])[0]
        btype = data[off + 4:off + 8].decode("latin1")
        if size == 0:
            size = len(data) - off
        elif size == 1:
            size = struct.unpack(">Q", data[off + 8:off + 16])[0]
        boxes.append((btype, size))
        if size < 8:
            break
        off += size
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/workspace/i2d/final")
    ap.add_argument("--ref", default="/workspace/i2d")
    args = ap.parse_args()
    R = args.root

    print(f"\n═══ 鲸鱼娘 Image-to-3D 版验收 ═══\n根目录: {R}\n")

    # G1 blend
    print("── G1 Blender 工程 ──")
    # 兼容两种布局：开发态（blend 在根目录）与发布态（blend 在 model/ 下）
    blend = os.path.join(R, "whale-chan-i2d.blend")
    if not os.path.exists(blend):
        blend = os.path.join(R, "model", "whale-chan-i2d.blend")
    if os.path.exists(blend):
        with open(blend, "rb") as f:
            head = f.read(12)
        ok = head[:7] == b"BLENDER" or head.startswith(b"BLENDER")
        check("blend 文件存在且为 Blender 格式", ok,
              f"{os.path.getsize(blend):,} bytes")
    else:
        check("blend 文件存在", False, blend)

    # G2 GLB
    print("\n── G2 GLB（带顶点色）──")
    glb = os.path.join(R, "model", "whale-chan-i2d.glb")
    if os.path.exists(glb):
        st = glb_stats(glb)
        check("GLB 可解析 (glTF v%d)" % st["version"], True,
              f"{os.path.getsize(glb):,} bytes")
        check("含 COLOR_0 顶点色（贴图已烘焙）", st["has_color"],
              f"primitive×{st['nprims']}, mesh×{st['nmesh']}")
        check("顶点数 > 20000", st["nverts"] > 20000, f"{st['nverts']:,}")
        check("三角面数 > 50000", st["ntris"] > 50000, f"{st['ntris']:,}")
        # 贴图通道
        check("含 TEXCOORD_0（UV 通道）", st["has_uv"], "")
        check("含 baseColorTexture 贴图", st["has_tex"], f"image×{st['nimg']}")
        check("贴图已嵌入 GLB（非外链）", st["nimg"] > 0 and st["embedded_tex"],
              st["tex_names"])
    else:
        check("GLB 存在", False, glb)

    # G3 渲染图
    print("\n── G3 高清渲染图 ──")
    for name in ("front", "side", "back", "three-quarter"):
        p = os.path.join(R, "renders", f"{name}.png")
        if os.path.exists(p):
            w, h = png_size(p)
            check(f"{name}.png", w == 1024 and h == 1024, f"{w}×{h}")
        else:
            check(f"{name}.png 存在", False, p)

    # G4 转台视频
    print("\n── G4 转台 MP4 ──")
    mp4 = os.path.join(R, "video", "whale-chan-turntable.mp4")
    if os.path.exists(mp4):
        boxes = mp4_probe(mp4)
        types = [b[0] for b in boxes]
        size = os.path.getsize(mp4)
        check("MP4 存在且非空", size > 10000, f"{size:,} bytes")
        check("含 ftyp/moov/mdat 结构", {"ftyp", "moov", "mdat"} <= set(types),
              " ".join(f"{t}({s:,})" for t, s in boxes[:6]))
    else:
        check("MP4 存在", False, mp4)

    # G5 许可与归档
    print("\n── G5 许可与归档 ──")
    notice = os.path.join(args.ref, "NOTICE.md")
    check("NOTICE.md 存在", os.path.exists(notice))
    if os.path.exists(notice):
        s = open(notice, encoding="utf-8").read()
        for kw in ("CC BY-NC-SA 4.0", "上善无形", "ZipZipPipe",
                   "FiniYang", "TripoSR"):
            check(f"NOTICE 含「{kw}」", kw in s)
    fp = os.path.join(args.ref, "reference", "figurine-prompt.md")
    check("生图 prompt 归档存在", os.path.exists(fp))
    fig2 = os.path.join(args.ref, "fig2.jpg")
    if os.path.exists(fig2):
        h = hashlib.sha256(open(fig2, "rb").read()).hexdigest()
        src = open(os.path.join(args.ref, "reference", "SOURCES.md"),
                   encoding="utf-8").read()
        check("SOURCES.md 中 fig2.jpg SHA-256 匹配", h in src, h[:16] + "…")

    # 汇总
    nfail = sum(1 for r in results if r[0] == FAIL)
    nwarn = sum(1 for r in results if r[0] == WARN)
    npass = sum(1 for r in results if r[0] == PASS)
    print(f"\n═══ 结果: {npass} PASS / {nfail} FAIL / {nwarn} WARN ═══\n")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
