"""torchmcubes 兼容 shim —— 用 scikit-image 的纯 Python marching cubes 顶替。

为什么不用官方 torchmcubes：
  torchmcubes 需要编译 CUDA 扩展，而本沙箱无 CUDA、无 Python 开发头文件
  （Python.h 缺失，apt 装不了 python3-dev）。
  scikit-image 的 measure.marching_cubes 是纯 numpy 实现，CPU 可跑，
  且索引约定与 torchmcubes 一致：
      volume[i, j, k]  ↔  verts[:, 0]=i, verts[:, 1]=j, verts[:, 2]=k

torchmcubes.marching_cubes(vol, thresh) -> (verts float32 [V,3], faces int64 [F,3])
"""
import numpy as np
import torch
from skimage import measure


def marching_cubes(vol, thresh=0.0, max_corner=8, **kwargs):
    if torch.is_tensor(vol):
        arr = vol.detach().cpu().numpy()
    else:
        arr = np.asarray(vol)
    arr = np.ascontiguousarray(arr, dtype=np.float32)

    # skimage 的 'descent' 是默认方向；TripoSR 的顶点色依赖表面法线指向外侧，
    # 若渲染出来颜色左右镜像，把这里改成 'ascent'。
    direction = kwargs.pop("gradient_direction", "descent")
    verts, faces, _normals, _values = measure.marching_cubes(
        arr, level=float(thresh), gradient_direction=direction,
        allow_degenerate=True, method="lewiner",
    )
    return (torch.from_numpy(np.ascontiguousarray(verts, dtype=np.float32)),
            torch.from_numpy(np.ascontiguousarray(faces, dtype=np.int64)))
