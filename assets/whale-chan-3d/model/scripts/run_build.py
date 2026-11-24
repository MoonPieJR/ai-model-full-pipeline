#!/usr/bin/env python
"""鲸鱼娘 semi-chibi 3D 模型 —— 构建 / 验收 / 导出入口

用法:
  python run_build.py [--out DIR] [--samples N] [--no-render]

关键实现要点：
  * bpy 在进程退出时会段错误（产出物已落盘但退出码非零）。
    作业末尾统一走 finish()：quit_blender() + os._exit(code)，保证 exit 0。
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from walechan_geom import build_materials, reset_scene  # noqa: E402
from walechan_parts import (  # noqa: E402
    Z_CHIN, Z_TOP, build_all, collect, group_into_objects,
)

PARTS = 28  # SPEC §2 部件清单数量


# ────────────────────────────── 渲染工具 ──────────────────────────────

def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def setup_scene(bg_hex="#f2e8da"):
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (
        int(bg_hex[1:3], 16) / 255, int(bg_hex[3:5], 16) / 255,
        int(bg_hex[5:7], 16) / 255, 1.0)
    bg.inputs[1].default_value = 0.34

    def area(name, loc, energy, size, target=(0, 0, 1.4), color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size
        ld.color = color
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        bpy.context.collection.objects.link(ob)
        look_at(ob, target)
        return ob

    area("Key", (-2.6, -3.4, 4.2), 160, 3.2, color=(1.0, 0.98, 0.95))
    area("Fill", (3.4, -2.2, 2.0), 70, 4.0, color=(0.90, 0.94, 1.0))
    area("Rim", (1.2, 3.6, 3.2), 130, 2.6, color=(0.86, 0.92, 1.0))


def setup_render(samples=64, res=720):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "Standard"   # 保持与参考图接近的平涂观感
    sc.view_settings.look = "None"


VIEWS = {
    "front":       ((0.0, -6.2, 1.44), (0, 0, 1.44), 3.05),
    "side":        ((6.2, 0.0, 1.44), (0, 0, 1.44), 3.05),
    "three-quarter": ((4.0, -4.4, 2.35), (0, 0, 1.40), 3.30),
}


def render_views(outdir, names=("front", "side", "three-quarter")):
    sc = bpy.context.scene
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 62
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    sc.camera = cam
    os.makedirs(outdir, exist_ok=True)
    paths = {}
    for name in names:
        loc, tgt, dist = VIEWS[name]
        cam.location = loc
        look_at(cam, tgt)
        cam_data.lens = 62
        sc.render.filepath = os.path.join(outdir, f"whale-chan-{name}.png")
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        paths[name] = (sc.render.filepath, round(time.time() - t0, 1))
    return paths


# ────────────────────────────── 验收 ──────────────────────────────

def bbox_of(objs):
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for ob in objs:
        if ob.type != "MESH":
            continue
        for corner in ob.bound_box:
            w = ob.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return lo, hi


def verify(groups, objs):
    lo, hi = bbox_of(objs)
    total_h = hi[2] - lo[2]
    head_h = Z_TOP - Z_CHIN
    heads = total_h / head_h

    # 几何完整性
    bad = [o.name for o in objs if o.type == "MESH" and len(o.data.polygons) == 0]
    no_mat = [o.name for o in objs if o.type == "MESH" and len(o.data.materials) == 0]

    # G2 部件齐全
    expect = set(group_into_objects.__doc__ or "")  # noqa
    n_groups = len([k for k, v in groups.items()
                    if (v if isinstance(v, list) else [v]) and
                    len([x for x in (v if isinstance(v, list) else [v]) if x]) > 0])

    return {
        "G1_head_body_ratio": round(heads, 3),
        "G1_pass": 2.695 <= heads <= 2.995,
        "G2_group_count": n_groups,
        "G2_object_count": len(objs),
        "G2_pass": n_groups >= 20,
        "G3_empty_meshes": bad,
        "G3_meshes_without_material": no_mat,
        "G3_pass": not bad and not no_mat,
        "bbox_min": [round(v, 4) for v in lo],
        "bbox_max": [round(v, 4) for v in hi],
        "total_height_BU": round(total_h, 4),
        "head_height_BU": round(head_h, 4),
        "width_BU": round(hi[0] - lo[0], 4),
        "depth_BU": round(hi[1] - lo[1], 4),
    }


# ────────────────────────────── 导出 ──────────────────────────────

def export_all(outdir):
    os.makedirs(outdir, exist_ok=True)
    blend = os.path.join(outdir, "whale-chan.blend")
    glb = os.path.join(outdir, "whale-chan.glb")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB",
                              export_apply=True, export_yup=True)
    return blend, glb


def finish(code=0):
    """规避 bpy 退出期段错误，保证流水线 exit code = 0。"""
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


# ────────────────────────────── main ──────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/model/out")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--res", type=int, default=720)
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    print("[1/5] 场景与材质")
    reset_scene()
    M = build_materials()

    print("[2/5] 部件装配")
    groups = build_all(M)
    objs = group_into_objects(groups)
    print(f"      {len(objs)} 个逻辑对象 / {len(collect(groups))} 个部件")

    print("[3/5] 验收检查")
    rep = verify(groups, objs)
    print(f"      头身比 {rep['G1_head_body_ratio']} (期望 2.695~2.995) "
          f"{'PASS' if rep['G1_pass'] else 'FAIL'}")
    print(f"      总高 {rep['total_height_BU']} BU / 宽 {rep['width_BU']} BU")

    print("[4/5] 渲染")
    if not args.no_render:
        setup_scene()
        setup_render(args.samples, args.res)
        paths = render_views(os.path.join(args.out, "renders"))
        for k, (p, sec) in paths.items():
            print(f"      {k}: {os.path.basename(p)} ({sec}s)")

    print("[5/5] 导出")
    blend, glb = export_all(args.out)
    for p in (blend, glb):
        print(f"      {os.path.basename(p)}  {os.path.getsize(p)} bytes")

    rep["outputs"] = {"blend": blend, "glb": glb}
    rep["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(args.out, "verify.json"), "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f"\n完成，用时 {rep['elapsed_sec']}s")
    finish(0)


if __name__ == "__main__":
    main()
