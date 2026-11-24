#!/usr/bin/env bash
# TripoSR CPU 环境搭建
set -euo pipefail
export HOME=/workspace/.home
TS=/workspace/i2d/TripoSR
V=/workspace/i2d/venv
PY=$V/bin/pip
TSRC="https://pypi.tuna.tsinghua.edu.cn/simple"
CPU="https://download.pytorch.org/whl/cpu"

echo "═══ [1/5] torch 纯依赖（清华源）═══"
$PY install --no-cache-dir -i $TSRC \
    filelock typing-extensions sympy networkx jinja2 fsspec numpy pillow \
    safetensors huggingface-hub 2>&1 | tail -2

echo "═══ [2/5] torch / torchvision CPU（官方 CPU 轮子，--no-deps）═══"
$PY install --no-cache-dir --no-deps --index-url $CPU torch torchvision 2>&1 | tail -3

echo "═══ [3/5] TripoSR 核心依赖 ════"
$PY install --no-cache-dir -i $TSRC \
    "transformers==4.35.0" "trimesh==4.0.5" "einops==0.7.0" "omegaconf==2.3.0" \
    "Pillow==10.1.0" "imageio[ffmpeg]" 2>&1 | tail -3

echo "═══ [4/5] torchmcubes（CPU 版；无 CUDA 时自动回退）═══"
$PY install --no-cache-dir -i $TSRC \
    "git+ssh://git@github.com/tatsy/torchmcubes.git" 2>&1 | tail -6

echo "═══ [5/5] 校验 ════"
$V/bin/python - <<'PY'
import torch, torchvision, transformers, trimesh
print("torch      ", torch.__version__, "cuda:", torch.cuda.is_available())
print("torchvision", torchvision.__version__)
print("transformers", transformers.__version__)
print("trimesh    ", trimesh.__version__)
try:
    from torchmcubes import marching_cubes
    print("torchmcubes OK (CPU)")
except Exception as e:
    print("torchmcubes FAIL:", e)
PY
echo "═══ 完成 ═══"
