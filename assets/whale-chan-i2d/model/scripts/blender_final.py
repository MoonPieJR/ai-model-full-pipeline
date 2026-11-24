#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blender_final.py —— Image-to-3D 版最终产物生成（Blender 侧）

输入：已经过「分带色彩迁移 + 色点抹平」的 GLB（带 COLOR_0 顶点色）
输出：
  renders/{front,side,back,three-quarter}.png   1024² / 64 samples / 带降噪
  video/whale-chan-turntable.mp4                 720² / 32 samples / 6s / 24fps
  whale-chan-i2d.blend                           工程文件

两个关键设置：
1. **背景用 compositor 做 Alpha Over 到精确米白**（sRGB 240,226,215），
   而不是靠 World 背景色 —— World 强度会同时改变环境光和背景色，
   两者解不开：背景想准就得压暗环境光，压暗环境光模型就没层次了。
2. **转台视频关闭降噪**（denoise=False）—— 本沙箱 2 核无 AVX，
   OpenImageDenoise 每帧重载内核要 30~50 秒，144 帧会被拖到 2 小时以上。

用法：
  python blender_final.py <in.glb> <outdir> [samples] [res] [tt_sec] [tt_fps] [tt_res]
                           [sat] [key] [fill] [rim] [world]
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_pipeline as bp

BG_SRGB = (240 / 255, 226 / 255, 215 / 255)   # 参考图的米白背景


def srgb2lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def setup_composite(bg_srgb):
    """透明渲染 + Alpha Over 到精确米白背景"""
    sc = bpy.context.scene
    sc.use_nodes = True
    nt = sc.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new("CompositorNodeRLayers")
    rl.location = (-500, 0)
    rgb = nt.nodes.new("CompositorNodeRGB")
    rgb.location = (-500, -220)
    rgb.outputs[0].default_value = (*[srgb2lin(c) for c in bg_srgb], 1.0)
    ao = nt.nodes.new("CompositorNodeAlphaOver")
    ao.location = (-150, 0)
    comp = nt.nodes.new("CompositorNodeComposite")
    comp.location = (150, 0)
    nt.links.new(rgb.outputs[0], ao.inputs[1])
    nt.links.new(rl.outputs["Image"], ao.inputs[2])
    nt.links.new(ao.outputs[0], comp.inputs[0])


def main():
    glb = sys.argv[1]
    out = sys.argv[2]
    samples = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    res = int(sys.argv[4]) if len(sys.argv) > 4 else 1024
    tt_sec = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    tt_fps = int(sys.argv[6]) if len(sys.argv) > 6 else 24
    tt_res = int(sys.argv[7]) if len(sys.argv) > 7 else 720
    sat = float(sys.argv[8]) if len(sys.argv) > 8 else 1.75
    key = float(sys.argv[9]) if len(sys.argv) > 9 else 80
    fill = float(sys.argv[10]) if len(sys.argv) > 10 else 28
    rim = float(sys.argv[11]) if len(sys.argv) > 11 else 60
    world = float(sys.argv[12]) if len(sys.argv) > 12 else 0.30
    tt_samples = int(sys.argv[13]) if len(sys.argv) > 13 else 32

    os.makedirs(out, exist_ok=True)
    bp.reset_scene()
    meshes, _ = bp.import_glb(glb, "Import")
    bp.orient_up(meshes)
    bp.normalize(meshes)
    # Laplacian 平滑依赖**顶点邻接关系**。带 UV 的 GLB 为了承载 per-face
    # box-mapping UV 必须按 face-corner 拆点（49,577 → 297,462），
    # 拆点后每个顶点只属于一个三角形、邻接全断 —— 此时再平滑会把几何打散成点阵。
    # 而拆点版的几何在生成 GLB 之前就已经平滑过了，这里直接跳过。
    nv = sum(len(m.data.vertices) for m in meshes)
    if os.environ.get("SKIP_SMOOTH") == "1" or nv > 100000:
        print(f"[model] {len(meshes)} 对象 / {nv} 顶点  "
              f"（拆点版，跳过 Laplacian 平滑）")
    else:
        bp.laplacian_smooth(meshes, 0.25, 2)
        print(f"[model] {len(meshes)} 对象 / {nv} 顶点")

    coll = bp.get_coll("Render")
    cam = bp.setup_camera(coll)
    bp.frame_model(cam, meshes, 0)

    # 若 GLB 自带 PBR 贴图材质（baseColorTexture），就沿用它 ——
    # 否则会用顶点色材质覆盖掉贴图，交付的 GLB 与渲染图就对不上了。
    has_tex = False
    for o in meshes:
        if o.type != "MESH":
            continue
        for m in o.data.materials:
            if m and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image:
                        has_tex = True
    if has_tex:
        print("[mat]  沿用 GLB 自带 baseColorTexture 材质")
    else:
        mat = bp.build_fixed_material(meshes, "WhaleChan_Fixed",
                                      color_boost=1.0, saturation=sat)
        bp.apply_material(meshes, mat)
    bp.setup_world(world)
    bp.setup_lights(coll)
    for ob in coll.objects:
        if ob.type != "LIGHT":
            continue
        for tag, base, sc in (("Key", 120.0, key), ("Fill", 40.0, fill),
                              ("Rim", 90.0, rim)):
            if tag in ob.name:
                ob.data.energy = base * sc / 100.0
    setup_composite(BG_SRGB)

    # ── 透明底渲染 + compositor 合成 ──
    views = [("front", 0), ("side", 90), ("back", 180), ("three-quarter", 35)]
    if os.environ.get("SKIP_PNG") == "1":
        print("[png ]  跳过（SKIP_PNG=1）")
    else:
        bp.render_views(os.path.join(out, "renders"), cam, meshes, views,
                        samples=samples, res=res, transparent=True)

    # ── 转台 ──
    if os.environ.get("SKIP_VIDEO") != "1":
        print(f"[turntable] {tt_sec}s @ {tt_fps}fps = {tt_sec*tt_fps} 帧")
        bp.render_turntable(os.path.join(out, "video"), cam, meshes,
                            name="whale-chan-turntable", seconds=tt_sec,
                            fps=tt_fps, res=tt_res, samples=tt_samples,
                            transparent=True)

    # ── 存工程 ──
    blend = os.path.join(out, "whale-chan-i2d.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print(f"[blend] {blend}  {os.path.getsize(blend):,} bytes")

    # ── 报告 ──
    lo, hi = bp.model_bounds(meshes)
    rep = {
        "source_glb": os.path.abspath(glb),
        "vertices": sum(len(m.data.vertices) for m in meshes),
        "faces": sum(len(m.data.polygons) for m in meshes),
        "bbox": {"min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi]},
        "height_bu": round(hi[2] - lo[2], 4),
        "width_bu": round(hi[0] - lo[0], 4),
        "depth_bu": round(hi[1] - lo[1], 4),
        "render": {"samples": samples, "res": res,
                   "bg_srgb": list(BG_SRGB),
                   "sat": sat, "key": key, "fill": fill, "rim": rim,
                   "world": world},
        "turntable": {"seconds": tt_sec, "fps": tt_fps, "res": tt_res,
                      "samples": 32, "denoise": False},
        "outputs": {
            "blend": "whale-chan-i2d.blend",
            "glb": os.path.basename(glb),
            "renders": [f"renders/{n}.png" for n, _ in views],
            "video": "video/whale-chan-turntable.mp4",
        },
    }
    with open(os.path.join(out, "final_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("[report]", os.path.join(out, "final_report.json"))


if __name__ == "__main__":
    main()
    os._exit(0)
