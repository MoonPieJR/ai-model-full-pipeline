#!/usr/bin/env python3
"""按 SHA-256 校验拉取建模参考素材。

第三方图片不入库本仓库，改为按需下载 + 校验，避免许可叠加。

两条传输通道，自动回退：
  1. HTTPS  → raw.githubusercontent.com（通用环境走这条）
  2. git/SSH → git@github.com:<repo>.git + sparse-checkout
     （沙箱 / 内网环境常封禁 443 出网，但 SSH 通常可用）

用法:
    python3 fetch_reference.py --dest ./reference
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

RAW = "https://raw.githubusercontent.com"

ASSETS = [
    {
        "name": "whale-design.png",
        "repo": "Mizimo/whale-girl-visual-language-v4",
        "path": "assets/original-design/whale-design.png",
        "sha256": "04aa326d4e19c4c303a7d0c504805e43b7813f6f838a49cbf48af0b6e502c7a7",
        "bytes": 1576721,
    },
    {
        "name": "semi-chibi-front.webp",
        "repo": "Neko3000/deepseek-whalechan",
        "path": ("skills/whalechan-image-character/assets/reference-images/"
                 "semi-chibi/neutral_standing_front_isolated.webp"),
        "sha256": "e27638afe71cbc7edfa770b2f21201b627c7fb10f92d532a91f5e99563d24824",
        "bytes": 96320,
    },
    {
        "name": "CHARACTER.md",
        "repo": "Mizimo/whale-girl-visual-language-v4",
        "path": "docs/CHARACTER.md",
        "sha256": "dff00a1d9dffa180a9e165fef076c8757e891b57e4aa006f63ae55b2a07735b8",
        "bytes": 6439,
    },
    {
        "name": "original-design-assets.json",
        "repo": "Mizimo/whale-girl-visual-language-v4",
        "path": "assets/original-design/assets.json",
        "sha256": "fe4f5cdaa25f00660d3414a546de13f2992da79fbae5c90255eb2ec3d6124b07",
        "bytes": 1013,
    },
]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _accept(dest, name, data, sha):
    """校验并落盘。"""
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        print(f"      SHA-256 不匹配：期望 {sha} / 实际 {got}")
        return False
    with open(os.path.join(dest, name), "wb") as f:
        f.write(data)
    print(f"  ✓ {name:<28} {len(data):>9,} bytes  SHA-256 校验通过")
    return True


def fetch_https(a, dest):
    url = f"{RAW}/{a['repo']}/main/{a['path']}"
    req = urllib.request.Request(url, headers={"User-Agent": "whale-chan-3d/fetch"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    return _accept(dest, a["name"], data, a["sha256"])


def fetch_git(a, dest):
    """SSH + sparse-checkout 拉取单个文件。"""
    url = f"git@github.com:{a['repo']}.git"
    tmp = tempfile.mkdtemp(prefix="wc-fetch-")
    try:
        r = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none",
             "--sparse", url, tmp],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"      git clone 失败: {r.stderr.strip()[:200]}")
            return False
        sub = os.path.dirname(a["path"])
        r = subprocess.run(["git", "-C", tmp, "sparse-checkout", "set", sub],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"      sparse-checkout 失败: {r.stderr.strip()[:200]}")
            return False
        src = os.path.join(tmp, a["path"])
        if not os.path.exists(src):
            print(f"      上游不存在该路径: {a['path']}")
            return False
        with open(src, "rb") as f:
            data = f.read()
        return _accept(dest, a["name"], data, a["sha256"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fetch(a, dest):
    path = os.path.join(dest, a["name"])
    if os.path.exists(path) and sha256_of(path) == a["sha256"]:
        print(f"  ✓ {a['name']:<28} 已存在且校验通过")
        return True
    try:
        return fetch_https(a, dest)
    except Exception as e:
        print(f"  … {a['name']:<28} HTTPS 不可用 ({type(e).__name__})，改走 git/SSH")
    try:
        return fetch_git(a, dest)
    except Exception as e:
        print(f"  ✗ {a['name']:<28} git/SSH 也失败: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="reference")
    args = ap.parse_args()
    os.makedirs(args.dest, exist_ok=True)
    print(f"拉取参考素材 → {os.path.abspath(args.dest)}")
    ok = True
    for a in ASSETS:
        ok = fetch(a, args.dest) and ok
    print("\n全部校验通过。" if ok else "\n存在校验失败项，请检查网络或上游变更。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
