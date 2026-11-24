"""阶段①：导入 TripoSR 产物 → 归一化 → 材质/灯光 → 三视角检查渲染

对应教程第 ⑥ 步的前半段：「拿到 GLB 后先渲染几个角度找问题」。
原始 GLB 文件原样保留，所有修改都发生在 Blender 工程里。
"""
import json
import os
import sys

sys.path.insert(0, "/workspace/i2d")
import bpy

import blender_pipeline as bp

GLB = sys.argv[1] if len(sys.argv) > 1 else "/workspace/i2d/out/triposr_raw.glb"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/workspace/i2d/blender_stage1"
SAMPLES = int(sys.argv[3]) if len(sys.argv) > 3 else 24
RES = int(sys.argv[4]) if len(sys.argv) > 4 else 640

os.makedirs(OUT, exist_ok=True)
print(f"[input] {GLB}")

bp.reset_scene()

# 原始模型单独放一个集合，随时可切回
objs, raw_coll = bp.import_glb(GLB, "WhaleChan_RAW")
meshes = [o for o in objs if o.type == "MESH"]
print(f"[import] {len(objs)} 个对象 / {len(meshes)} 个网格")

lo, hi = bp.model_bounds(objs)
print(f"[bbox] {[round(v, 3) for v in lo]} -> {[round(v, 3) for v in hi]}")
print(f"[bbox] 尺寸 {round(hi[0]-lo[0],3)} x {round(hi[1]-lo[1],3)} x {round(hi[2]-lo[2],3)}")

# 顶点色信息
for o in meshes[:3]:
    attrs = [a.name for a in o.data.attributes]
    print(f"  {o.name}: verts={len(o.data.vertices)} faces={len(o.data.polygons)} attrs={attrs}")

bp.orient_up(objs)
face = bp.detect_face_azimuth(objs)
s = bp.normalize(objs, target_h=2.87)
lo, hi = bp.model_bounds(objs)
print(f"[normalize] 缩放 {s:.4f}  →  高度 {round(hi[2]-lo[2], 4)}  脚底 z={round(lo[2],4)}")

mat = bp.build_fixed_material(meshes, roughness=0.58, color_boost=1.06, saturation=1.14)
if mat:
    bp.apply_material(meshes, mat)

bp.setup_world(strength=0.45)
bp.setup_lights(bp.get_coll("Stage"))
cam = bp.setup_camera(bp.get_coll("Stage"))

views = [("front", face), ("side", face + 90), ("back", face + 180),
         ("three-quarter", face + 35), ("top-back", face + 145)]
print(f"[render] {SAMPLES} samples @ {RES}²")
bp.render_views(OUT, cam, meshes, views, samples=SAMPLES, res=RES)

# 存工程
blend = os.path.join(OUT, "whale-chan-triposr-stage1.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
print(f"[save] {blend}  {os.path.getsize(blend):,} bytes")

report = {
    "glb": GLB,
    "objects": len(objs),
    "meshes": len(meshes),
    "verts": sum(len(o.data.vertices) for o in meshes),
    "faces": sum(len(o.data.polygons) for o in meshes),
    "bbox_after_normalize": {"min": [round(v, 4) for v in lo],
                              "max": [round(v, 4) for v in hi]},
    "height_BU": round(hi[2] - lo[2], 4),
    "scale_applied": round(s, 6),
    "face_azimuth": face,
    "has_vertex_color": any("Col" in [a.name for a in o.data.attributes] for o in meshes),
}
with open(os.path.join(OUT, "stage1_report.json"), "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print(json.dumps(report, indent=2, ensure_ascii=False))

bpy.ops.wm.quit_blender()
PY
import sys
sys.stdout.flush()
import os
os._exit(0)
