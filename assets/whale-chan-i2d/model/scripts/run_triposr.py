"""TripoSR 单图转 3D —— CPU 推理管线（沙箱无 GPU 的适配版）

与官方 run.py 的差异：
  1. 背景抠除改用 PIL ImageDraw.floodfill（从画布边缘泛洪），
     不依赖 rembg / onnxruntime —— 角色内部的米白色不会被误抠，
     因为 floodfill 只填充与种子连通的区域。
  2. 不做 texture baking（需要 kaolin + CUDA），输出顶点色网格。
  3. 直接导出 GLB。
"""
import os
import sys
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
sys.path.insert(0, "/workspace/i2d/stubs")
sys.path.insert(0, "/workspace/i2d/TripoSR")

import numpy as np
import torch
from PIL import Image, ImageDraw

from tsr.system import TSR
from tsr.utils import resize_foreground


def strip_background(im, thresh=34):
    """从画布四边泛洪，把连通的背景抠成透明。"""
    im = im.convert("RGBA")
    w, h = im.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for pt in seeds:
        try:
            ImageDraw.floodfill(im, pt, (255, 255, 255, 0), thresh=thresh)
        except Exception:
            pass
    return im


def preprocess(path, fg_ratio=0.85, out_png=None, work_px=1024):
    im = Image.open(path).convert("RGB")
    # 先降到工作分辨率：抠图与 floodfill 都在像素级跑，原图 3552×4736 太慢
    if max(im.size) > work_px:
        s = work_px / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    im = strip_background(im)
    im = resize_foreground(im, fg_ratio)
    arr = np.array(im).astype(np.float32) / 255.0
    # 透明区域填中性灰（TripoSR 训练时的约定）
    arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
    out = Image.fromarray((arr * 255.0).astype(np.uint8))
    if out_png:
        out.save(out_png)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default="/workspace/i2d/out")
    ap.add_argument("--model-dir", default="/workspace/i2d/TripoSR")
    ap.add_argument("--mc-resolution", type=int, default=256)
    ap.add_argument("--fg-ratio", type=float, default=0.85)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--smooth", type=float, default=0.8, help="密度场高斯平滑 sigma")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    device = args.device if torch.cuda.is_available() else "cpu"
    print(f"[device] {device}  torch {torch.__version__}")

    t0 = time.time()
    img = preprocess(args.image, args.fg_ratio,
                     out_png=os.path.join(args.out, "input_preprocessed.png"))
    print(f"[preprocess] {img.size}  {time.time()-t0:.1f}s")

    print("[load] TSR.from_pretrained ...")
    t0 = time.time()
    model = TSR.from_pretrained(args.model_dir, "config.yaml", "model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to(device)
    print(f"[load] ok  {time.time()-t0:.1f}s")

    print("[infer] forward ...")
    t0 = time.time()
    with torch.no_grad():
        scene_codes = model([img], device=device)
    print(f"[infer] ok  {time.time()-t0:.1f}s")

    print("[mesh] marching cubes ...")
    t0 = time.time()
    if args.smooth > 0:
        # 密度场平滑：skimage 的 marching cubes 在带噪声的等值面上会切出碎面。
        # 在提取等值面前做一次高斯平滑，表面会干净很多。
        from scipy.ndimage import gaussian_filter
        import tsr.system as tsr_sys
        orig_extract = tsr_sys.TSR.extract_mesh

        def smooth_extract(self, sc, has_vertex_color, resolution=256, threshold=25.0):
            return orig_extract(self, sc, has_vertex_color, resolution, threshold)

        # 直接在 model 上包一层：对 density 做平滑后再走原逻辑
        _orig_qt = model.renderer.query_triplane
        sigma = args.smooth

        def qt(decoder, pts, scene_code, **kw):
            out = _orig_qt(decoder, pts, scene_code, **kw)
            if "density_act" in out:
                d = out["density_act"].detach().cpu().numpy()
                out["density_act"] = torch.from_numpy(
                    gaussian_filter(d, sigma=sigma)).to(out["density_act"].device)
            return out

        model.renderer.query_triplane = qt
        print(f"       密度场高斯平滑 sigma={sigma}")

    meshes = model.extract_mesh(scene_codes, True, resolution=args.mc_resolution)
    mesh = meshes[0]
    print(f"[mesh] ok  {time.time()-t0:.1f}s")
    print(f"       verts={len(mesh.vertices)} faces={len(mesh.faces)}")

    glb = os.path.join(args.out, "triposr_raw.glb")
    mesh.export(glb)
    print(f"[export] {glb}  {os.path.getsize(glb):,} bytes")

    npz = os.path.join(args.out, "scene_codes.npz")
    np.savez(npz, scene_codes=scene_codes.detach().cpu().numpy())
    print(f"[export] {npz}")
    print(f"\n总耗时 {time.time()-t0:.1f}s (mesh 段)")


if __name__ == "__main__":
    main()
