import sys, os, bpy, json
sys.path.insert(0, "/workspace/i2d")
import blender_pipeline as bp
glb, out = sys.argv[1], sys.argv[2]
key = float(sys.argv[3]); fill = float(sys.argv[4]); rim = float(sys.argv[5]); world = float(sys.argv[6])
res = int(sys.argv[7]) if len(sys.argv) > 7 else 768
os.makedirs(out, exist_ok=True)
bp.reset_scene()
meshes, _ = bp.import_glb(glb, "Import")
bp.orient_up(meshes); bp.normalize(meshes)
coll = bp.get_coll("Render")
cam = bp.setup_camera(coll); bp.frame_model(cam, meshes, 0)
bp.setup_world(world); bp.setup_lights(coll)
for ob in coll.objects:
    if ob.type != "LIGHT": continue
    for tag, base, sc in (("Key", 120.0, key), ("Fill", 40.0, fill), ("Rim", 90.0, rim)):
        if tag in ob.name: ob.data.energy = base * sc / 100.0
bp.render_views(out, cam, meshes, [("front", 0)], samples=24, res=res, transparent=False)
