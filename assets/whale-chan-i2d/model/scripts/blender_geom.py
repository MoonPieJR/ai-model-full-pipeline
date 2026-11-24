import sys, os, bpy
sys.path.insert(0, "/workspace/i2d")
import blender_pipeline as bp
glb, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
bp.reset_scene()
meshes, _ = bp.import_glb(glb, "Import")
bp.orient_up(meshes); bp.normalize(meshes)
coll = bp.get_coll("Render")
cam = bp.setup_camera(coll); bp.frame_model(cam, meshes, 0)
mat = bp.build_fixed_material(meshes, "Geo", color_boost=1.0, saturation=1.0)
bp.apply_material(meshes, mat)
bp.setup_world(0.35); bp.setup_lights(coll)
bp.render_views(out, cam, meshes, [("geo-front", 0)], samples=16, res=512, transparent=False)
