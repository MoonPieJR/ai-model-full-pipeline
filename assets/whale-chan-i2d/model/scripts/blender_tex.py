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
# ⚠ 不用 build_fixed_material（那会换成顶点色通道）—— 保留 GLB 自带的 baseColorTexture
for o in meshes:
    print("  [mat]", o.name, [m.name for m in o.data.materials],
          [(n.name, n.type) for m in o.data.materials for n in m.node_tree.nodes] if o.data.materials and o.data.materials[0].use_nodes else "")
bp.setup_world(0.35); bp.setup_lights(coll)
bp.render_views(out, cam, meshes, [("tex-front", 0)], samples=16, res=512, transparent=False)
