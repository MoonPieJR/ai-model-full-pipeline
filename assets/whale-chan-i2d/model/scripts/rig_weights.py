#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
权重计算：Blender 内置 bone heat 在密集网格上会静默失败
（顶点组建好了、权重全 0），所以自己算。

算法：点到骨骼线段的距离 → 距离高次反比 → 归一化 → 取前 4 根
      → 量化到 1/255 批量写入（1.2M 次逐点 API 调用会慢到不可用）

距离反比幂次越高，骨骼间的"抢夺"越少（幂 6 时相邻骨骼基本各管各的）。
"""
import numpy as np


def _seg_dist(verts, A, C):
    """verts:(V,3) → 到每条骨骼线段的距离 (V,B)"""
    AB = C - A
    L2 = np.maximum((AB * AB).sum(1), 1e-12)
    P = verts[:, None, :] - A[None, :, :]
    t = np.clip((P * AB[None, :, :]).sum(2) / L2[None, :], 0.0, 1.0)
    D = verts[:, None, :] - (A[None, :, :] + t[:, :, None] * AB[None, :, :])
    return np.linalg.norm(D, axis=2), t


def compute_weights(verts, bones, power=6.0, chunk=40000, top_n=4,
                    quant=255):
    """返回 (idx[V,top_n], w[V,top_n])。

    bones: [(head_xyz, tail_xyz), ...] 世界坐标
    """
    A = np.array([b[0] for b in bones], dtype=np.float32)
    C = np.array([b[1] for b in bones], dtype=np.float32)
    V = verts.shape[0]
    B = len(bones)
    out_idx = np.zeros((V, top_n), dtype=np.int32)
    out_w = np.zeros((V, top_n), dtype=np.float32)

    for s in range(0, V, chunk):
        e = min(s + chunk, V)
        v = verts[s:e]
        d, _ = _seg_dist(v, A, C)
        w = 1.0 / np.maximum(d, 1e-3) ** power
        # 只保留最近 top_n 根
        if B > top_n:
            part = np.argpartition(-w, top_n - 1, axis=1)[:, :top_n]
        else:
            part = np.tile(np.arange(B), (e - s, 1))
        rows = np.arange(e - s)[:, None]
        pw = w[rows, part]
        # 归一化
        pw = pw / np.maximum(pw.sum(axis=1, keepdims=True), 1e-12)
        out_idx[s:e] = part
        out_w[s:e] = pw
    return out_idx, out_w


def write_to_vertex_groups(obj, idx, w, quant=255):
    """量化权重后批量写入 vertex groups（避免 120 万次单点 API 调用）。"""
    vgs = [obj.vertex_groups.new(name=n) for n in
           sorted({g.name for g in obj.vertex_groups}, key=lambda s: s)]
    name2idx = {g.name: g.index for g in obj.vertex_groups}
    vids = np.arange(idx.shape[0])
    # 量化到 1/quant
    qw = np.clip(np.rint(w * quant), 0, quant).astype(np.int32)
    calls = 0
    for b in range(idx.shape[1]):
        for gi in range(len(vgs)):
            sel = (idx[:, b] == vgs[gi].index) & (qw[:, b] > 0)
            if not sel.any():
                continue
            ids = vids[sel]
            ws = qw[sel, b]
            # 相同权重的顶点合并成一次调用
            for val in np.unique(ws):
                m = ws == val
                vgs[gi].add(ids[m].tolist(), float(val) / quant, "REPLACE")
                calls += 1
    return calls
