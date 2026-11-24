#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
band_transfer.py —— 按高度分带把参考图色调迁移到模型顶点色，并直接改写 GLB

三个关键设计（都是踩过坑换来的）：

1. **分带迁移**：模型与参考图都按归一化高度切 8 带，每带独立迁移。
   顶部=呆毛/发饰，中段=女仆装，底部=袜/鞋，各带的明暗与饱和度各自对齐，
   不会出现"裙摆压暗了脸"。

2. **剔除近白**：参考图里蕾丝/围裙/袜子是大面积白色，计入统计会把目标明度
   拉高，迁移方向反过来（越迁越亮）。两边都按亮度阈值剔除后再统计。

3. **直接在 GLB 二进制层改写 COLOR_0**，再用 Blender 导入渲染。
   原因：Blender 的 glTF 导出器会丢顶点色（实测警告
   `The active Vertex Color will not be exported, as it is not used in the
   node tree of the material`），而"带贴图 GLB"正是本项目的核心交付物。
   自己改写 buffer 既保住顶点色，也保证**渲染用的就是最终交付的那个 GLB**。

不需要任何空间对齐 —— 只依赖"模型 z 高度 ↔ 参考图像素 y"这个竖直对应。

用法：python band_transfer.py <in.glb> <outdir> <ref.jpg> [samples]
"""
import json
import os
import struct
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp

NB = 8              # 高度分带数
WHITE_LUM = 0.86    # 亮度阈值：超过视为近白（蕾丝/围裙/高光）
GLB_MAGIC = 0x46546C67
JSON_CH = 0x4E4F534A
BIN_CH = 0x004E4942


# ── GLB 读写 ──
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_CT = {5121: np.uint8, 5123: np.uint16, 5126: np.float32}


def load_glb(path):
    with open(path, "rb") as f:
        _, _, length = struct.unpack("<4sII", f.read(12))
        chunks = {}
        while f.tell() < length:
            cl, ct = struct.unpack("<II", f.read(8))
            chunks[ct] = f.read(cl)
    return json.loads(chunks[JSON_CH]), chunks[BIN_CH], chunks


def read_accessor(g, buf, idx):
    a = g["accessors"][idx]
    bv = g["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    n = a["count"] * _NC[a["type"]]
    arr = np.frombuffer(buf, dtype=_CT[a["componentType"]], count=n, offset=off)
    return arr.reshape(a["count"], _NC[a["type"]]).astype(np.float64)


def write_glb(path, g, bin_chunk):
    """重新打包 GLB（JSON chunk 需 4 字节对齐）"""
    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    bb = bytes(bin_chunk) + b"\x00" * ((4 - len(bin_chunk) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bb)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<II", len(js), JSON_CH))
        f.write(js)
        f.write(struct.pack("<II", len(bb), BIN_CH))
        f.write(bb)


def set_vertex_colors(g, buf, prim, colors):
    """把 (N,3) 0..1 的颜色写进 COLOR_0 accessor（保持原 componentType）"""
    ai = prim["attributes"]["COLOR_0"]
    a = g["accessors"][ai]
    bv = g["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    ct = a["componentType"]
    nc = _NC[a["type"]]
    if ct == 5126:
        arr = np.empty((a["count"], nc), dtype=np.float32)
        arr[:, :3] = colors.astype(np.float32)
        if nc >= 4:
            arr[:, 3] = 1.0
        new = arr.tobytes()
    elif ct == 5121:
        arr = np.empty((a["count"], nc), dtype=np.uint8)
        arr[:, :3] = np.clip(colors * 255.0, 0, 255).astype(np.uint8)
        if nc >= 4:
            arr[:, 3] = 255
        new = arr.tobytes()
    else:
        raise RuntimeError(f"COLOR_0 componentType={ct} 不支持")
    buf = bytearray(buf)
    if len(buf) < off + len(new):
        buf.extend(b"\x00" * (off + len(new) - len(buf)))
    buf[off:off + len(new)] = new
    return bytes(buf), a["count"]


# ── 色彩 ──
def lin2srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


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


def ring_mean(h):
    return float((np.angle(np.mean(np.exp(2j * np.pi * h))) / (2 * np.pi)) % 1.0)


def band_stats(rgb, band_idx, nbands):
    out = []
    for b in range(nbands):
        sel = rgb[band_idx == b]
        if len(sel) < 30:
            out.append(None); continue
        lum = sel.mean(axis=1)
        core = sel[lum < WHITE_LUM]
        if len(core) < 30:
            core = sel
        hsv = rgb2hsv(core)
        out.append((ring_mean(hsv[:, 0]), float(hsv[:, 1].mean()),
                    float(hsv[:, 2].mean()), len(core)))
    return out


def load_ref_srgb(path):
    """Blender 的 image.pixels 返回的已是 sRGB 编码值（不再做色彩空间转换），
    实测：参考图角色暗部 V≈0.46 与 PIL 直读一致；若再过一遍 lin2srgb
    会升到 0.71，迁移方向就会反。"""
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "sRGB"
    W, H = img.size
    buf = np.empty(W * H * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(H, W, 4)[:, :, :3][::-1], W, H


def main():
    glb, outdir, ref_path = sys.argv[1], sys.argv[2], sys.argv[3]
    samples = int(sys.argv[4]) if len(sys.argv) > 4 else 48
    # mode: global | band     ks / kv / dh 为手动覆盖（None=自动统计）
    mode = sys.argv[5] if len(sys.argv) > 5 else "global"
    ks_ov = float(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] != "-" else None
    kv_ov = float(sys.argv[7]) if len(sys.argv) > 7 and sys.argv[7] != "-" else None
    dh_ov = float(sys.argv[8]) if len(sys.argv) > 8 and sys.argv[8] != "-" else None
    os.makedirs(outdir, exist_ok=True)

    # ── 1. 模型几何与顶点色 ──
    g, buf, _ = load_glb(glb)
    prim = g["meshes"][0]["primitives"][0]
    pos = read_accessor(g, buf, prim["attributes"]["POSITION"])
    col = read_accessor(g, buf, prim["attributes"]["COLOR_0"])[:, :3]
    if col.max() > 1.5:
        col = col / 255.0
    col = np.clip(col, 0, 1)
    z = pos[:, 2]
    zn = (z - z.min()) / max(z.max() - z.min(), 1e-9)
    m_band = np.clip((zn * NB).astype(int), 0, NB - 1)

    # ── 2. 参考图 ──
    ref, RW, RH = load_ref_srgb(ref_path)
    bg = ref[0, 0]
    rmask = np.abs(ref - bg).sum(axis=2) > 0.12
    ys, xs = np.where(rmask)
    ry0, ry1, rh = ys.min(), ys.max(), ys.max() - ys.min()
    rp = ref[rmask]
    r_band = np.clip((((ys - ry0) / rh) * NB).astype(int), 0, NB - 1)

    # ── 3. 逐带统计 ──
    ms = band_stats(col, m_band, NB)
    rs = band_stats(rp, r_band, NB)
    print(f"{'带':>3} {'模型 HSV':>26} {'参考 HSV':>26}    ΔH      kS      kV")
    # ── 3b. 系数：global 模式用全带加权平均（更保守，不会放大局部色斑）──
    if mode == "global":
        def wavg(src):
            num = sum(src[b][1] for b in range(NB) if src[b])
            den = sum(src[b][3] for b in range(NB) if src[b])
            return num / den
        gS_m = wavg(ms); gV_m = wavg(ms)
        gS_r = wavg(rs); gV_r = wavg(rs)
        gH_m = ring_mean(np.concatenate([rgb2hsv(col[m_band == b])[:, 0]
                                         for b in range(NB)
                                         if ms[b] and (m_band == b).sum() > 30]))
        gH_r = ring_mean(rp_hsv_h) if False else ring_mean(
            np.concatenate([rgb2hsv(rp[r_band == b])[:, 0]
                            for b in range(NB)
                            if rs[b] and (r_band == b).sum() > 30]))
        plan = [None] * NB
        p0 = (0.0 if dh_ov is None else dh_ov,
              (gS_r / max(gS_m, 1e-3)) if ks_ov is None else ks_ov,
              (gV_r / max(gV_m, 1e-3)) if kv_ov is None else kv_ov)
        for b in range(NB):
            plan[b] = p0
        print(f"[global] 模型 H{gH_m:.3f} S{gS_m:.3f} V{gV_m:.3f} | "
              f"参考 H{gH_r:.3f} S{gS_r:.3f} V{gV_r:.3f}")
        print(f"[plan ]  ΔH={p0[0]:+.3f}  kS={p0[1]:.2f}  kV={p0[2]:.2f}")
    else:
        plan = []
        for b in range(NB):
            if ms[b] is None or rs[b] is None:
                plan.append(None)
                print(f"{b:>3} {'—':>26} {'—':>26}")
                continue
            dH = rs[b][0] - ms[b][0]
            kS = rs[b][1] / max(ms[b][1], 1e-3)
            kV = rs[b][2] / max(ms[b][2], 1e-3)
            plan.append((dH, kS, kV))
            print(f"{b:>3} H{ms[b][0]:.3f} S{ms[b][1]:.3f} V{ms[b][2]:.3f}      "
                  f"H{rs[b][0]:.3f} S{rs[b][1]:.3f} V{rs[b][2]:.3f}      "
                  f"{dH:+.3f}  {kS:5.2f}  {kV:5.2f}")

    # ── 4. 应用迁移 ──
    hsv = rgb2hsv(col)
    for b in range(NB):
        if plan[b] is None:
            continue
        dH, kS, kV = plan[b]
        m = m_band == b
        if not m.any():
            continue
        hsv[m, 0] = (hsv[m, 0] + dH) % 1.0
        hsv[m, 1] = np.clip(hsv[m, 1] * kS, 0, 1)
        hsv[m, 2] = np.clip(hsv[m, 2] * kV, 0, 1)
    new_col = hsv2rgb(hsv)

    # ── 5. 改写 GLB（保住顶点色）──
    buf2, ncol = set_vertex_colors(g, buf, prim, new_col)
    out_glb = os.path.join(outdir, "whale-chan-i2d.glb")
    write_glb(out_glb, g, buf2)
    print(f"[glb]   写回 {ncol} 个顶点色 → {out_glb} "
          f"{os.path.getsize(out_glb):,} bytes")

    # ── 6. 导入改写后的 GLB 渲染（保证渲染物 == 交付物）──
    bp.reset_scene()
    meshes, _ = bp.import_glb(out_glb, "Import")
    bp.orient_up(meshes)
    bp.normalize(meshes)
    bp.laplacian_smooth(meshes, 0.25, 2)
    coll = bp.get_coll("Render")
    cam = bp.setup_camera(coll)
    bp.frame_model(cam, meshes, 0)
    mat = bp.build_fixed_material(meshes, "WhaleChan_Fixed",
                                  color_boost=1.0, saturation=1.0)
    bp.apply_material(meshes, mat)
    bp.setup_world(0.38)
    bp.setup_lights(coll)
    bp.setup_render(samples, 1024)
    bp.render_to(os.path.join(outdir, "front_band.png"))
    print("[done]  ", os.path.join(outdir, "front_band.png"))


if __name__ == "__main__":
    main()
    os._exit(0)
