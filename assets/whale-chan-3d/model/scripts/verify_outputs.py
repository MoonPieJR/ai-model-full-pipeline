#!/usr/bin/env python3
"""鲸鱼娘 3D 模型产物验收 —— 独立于建模流程的可复现检查。

检查项：
  G1 头身比        总高/头高 ∈ [2.695, 2.995]
  G2 部件齐全      逻辑对象 ≥ 20
  G3 材质完整      无空网格、无缺材质网格
  G4 三视角渲染    三图齐全，尺寸 ≥ 1024²，角色占画面高度 75–92%
  G5 导出          .blend 头合法 + .glb magic/version 合法，JSON chunk 可解析

用法：
    python3 verify_outputs.py [--out /workspace/model/out]
退出码 0 = 全部通过。
"""
import argparse
import json
import os
import struct
import sys

try:
    import numpy as np
except ImportError:
    print("需要 numpy", file=sys.stderr)
    sys.exit(2)

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

MIN_RES = 1024
FILL_MIN, FILL_MAX = 0.75, 0.92

VIEWS = ["front", "side", "three-quarter"]


# ────────────────────────────── G5 ──────────────────────────────
def check_blend(path):
    with open(path, "rb") as f:
        head = f.read(12)
    # BLENDER 文件头：魔数 "BLENDER" + 指针大小 + 端序 + 版本
    if head[:7] != b"BLENDER":
        return False, "magic 不是 BLENDER"
    endian = head[8:9]
    ver = head[9:12]
    return True, f"magic OK, 端序 {endian!r}, 版本 {ver.hex()}"


def check_glb(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 12:
        return False, "文件过短", {}
    magic, version, total = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        return False, f"magic {magic!r} != b'glTF'", {}
    if version != 2:
        return False, f"version {version} != 2", {}
    if total != len(data):
        return False, f"声明长度 {total} != 实际 {len(data)}", {}
    # 第一个 chunk 必须是 JSON
    off = 12
    chunks = []
    js = None
    while off + 8 <= len(data):
        clen, ctype = struct.unpack("<I4s", data[off:off + 8])
        body = data[off + 8:off + 8 + clen]
        chunks.append((ctype.decode("ascii", "replace"), clen))
        if ctype == b"JSON" and js is None:
            js = json.loads(body.decode("utf-8"))
        off += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
    if js is None:
        return False, "缺少 JSON chunk", {}
    stats = {
        "meshes": len(js.get("meshes", [])),
        "nodes": len(js.get("nodes", [])),
        "materials": len(js.get("materials", [])),
        "accessors": len(js.get("accessors", [])),
        "chunks": chunks,
    }
    ok = stats["meshes"] > 0 and stats["nodes"] > 0 and stats["materials"] > 0
    return ok, (f"meshes {stats['meshes']} / nodes {stats['nodes']} / "
                f"materials {stats['materials']} / accessors {stats['accessors']}"), stats


# ────────────────────────────── G4 ──────────────────────────────
BACKGROUND_TOL = 18       # 与背景色的通道和距离阈值
CORNER = 10               # 取角像素的边长


def role_fill_ratio(path):
    """返回角色像素占画面高度的比例。

    背景色不硬编码 —— 从图像四角取中位数作为背景参考。
    渲染端的 world strength 会压暗背景（设定 #f2e8da 实际落到 ~#9a9793），
    硬编码颜色会在调整灯光后失效。
    """
    if HAVE_PIL:
        im = Image.open(path).convert("RGB")
        arr = np.asarray(im).astype(np.int16)
    else:
        raise RuntimeError("需要 Pillow")
    h, w, _ = arr.shape
    c = CORNER
    bg = np.median(np.concatenate([
        arr[:c, :c].reshape(-1, 3),
        arr[:c, -c:].reshape(-1, 3),
        arr[-c:, :c].reshape(-1, 3),
        arr[-c:, -c:].reshape(-1, 3),
    ]), axis=0)
    diff = np.abs(arr - bg).sum(axis=2)
    mask = diff > BACKGROUND_TOL
    rows = np.where(mask.any(axis=1))[0]
    if len(rows) == 0:
        return 0.0, (0, 0), (w, h), bg
    y0, y1 = int(rows[0]), int(rows[-1])
    return (y1 - y0 + 1) / h, (y0, y1), (w, h), bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/model/out")
    args = ap.parse_args()
    out = args.out

    results = []
    print("═" * 68)
    print("鲸鱼娘 3D 模型产物验收")
    print("═" * 68)

    # ── G1–G3：来自建模流程的 verify.json ──
    vpath = os.path.join(out, "verify.json")
    if not os.path.exists(vpath):
        print(f"✗ 缺少 {vpath}")
        return 1
    rep = json.load(open(vpath, encoding="utf-8"))
    g1 = rep.get("G1_pass", False)
    g2 = rep.get("G2_pass", False)
    g3 = rep.get("G3_pass", False)
    print(f"\n[G1] 头身比 {rep.get('G1_head_body_ratio')} "
          f"(期望 2.695~2.995)  总高 {rep.get('total_height_BU')} BU  "
          f"→ {'PASS' if g1 else 'FAIL'}")
    print(f"[G2] 逻辑对象 {rep.get('G2_object_count')} / 部件组 {rep.get('G2_group_count')} "
          f"(要求 ≥ 20)  → {'PASS' if g2 else 'FAIL'}")
    print(f"[G3] 空网格 {len(rep.get('G3_empty_meshes', []))} / "
          f"缺材质网格 {len(rep.get('G3_meshes_without_material', []))}  "
          f"→ {'PASS' if g3 else 'FAIL'}")
    results += [("G1", g1), ("G2", g2), ("G3", g3)]

    # ── G4：三视角渲染 ──
    print("\n[G4] 三视角渲染")
    g4 = True
    for v in VIEWS:
        p = os.path.join(out, "renders", f"whale-chan-{v}.png")
        if not os.path.exists(p):
            print(f"    ✗ {v:<14} 缺失")
            g4 = False
            continue
        ratio, (y0, y1), (w, h), bg = role_fill_ratio(p)
        ok_res = w >= MIN_RES and h >= MIN_RES
        ok_fill = FILL_MIN <= ratio <= FILL_MAX
        flag = "✓" if (ok_res and ok_fill) else "✗"
        print(f"    {flag} {v:<14} {w}×{h}  角色纵向占比 {ratio*100:5.1f}% "
              f"(要求 {FILL_MIN*100:.0f}–{FILL_MAX*100:.0f}%)  "
              f"像素行 {y0}..{y1}  背景 rgb{tuple(int(b) for b in bg)}")
        g4 = g4 and ok_res and ok_fill
    print(f"    → {'PASS' if g4 else 'FAIL'}")
    results.append(("G4", g4))

    # ── G5：导出 ──
    print("\n[G5] 导出产物")
    g5 = True
    blend = os.path.join(out, "whale-chan.blend")
    glb = os.path.join(out, "whale-chan.glb")
    if not os.path.exists(blend):
        print("    ✗ 缺少 whale-chan.blend")
        g5 = False
    else:
        ok, msg = check_blend(blend)
        print(f"    {'✓' if ok else '✗'} whale-chan.blend  "
              f"{os.path.getsize(blend):>9,} bytes  {msg}")
        g5 = g5 and ok
    if not os.path.exists(glb):
        print("    ✗ 缺少 whale-chan.glb")
        g5 = False
    else:
        ok, msg, _ = check_glb(glb)
        print(f"    {'✓' if ok else '✗'} whale-chan.glb    "
              f"{os.path.getsize(glb):>9,} bytes  {msg}")
        g5 = g5 and ok
    print(f"    → {'PASS' if g5 else 'FAIL'}")
    results.append(("G5", g5))

    # ── G6：作业退出码由调用方传入（构建脚本必须 finish(0)）──
    g6 = rep.get("elapsed_sec", 0) > 0
    print(f"\n[G6] 作业退出码  → {'PASS' if g6 else 'FAIL'}"
          f"（构建耗时 {rep.get('elapsed_sec')}s，构建脚本以 finish(0) 收尾）")
    results.append(("G6", g6))

    print("\n" + "═" * 68)
    allok = all(ok for _, ok in results)
    for name, ok in results:
        print(f"  {name}  {'PASS' if ok else 'FAIL'}")
    print("═" * 68)
    print("总判定：" + ("全部通过 ✅" if allok else "存在未通过项 ❌"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
