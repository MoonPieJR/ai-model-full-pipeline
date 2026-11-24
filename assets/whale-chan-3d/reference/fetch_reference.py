#!/usr/bin/env python
"""按 SHA-256 校验拉取建模参考素材。

第三方图片不入库本仓库，改为按需下载 + 校验，避免许可叠加。
用法:
    python3 fetch_reference.py --dest ./reference
"""
import argparse
import hashlib
import os
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com"

ASSETS = [
    {
        "name": "whale-design.png",
        "url": f"{RAW}/Mizimo/whale-girl-visual-language-v4/main/assets/original-design/whale-design.png",
        "sha256": "04aa326d4e19c4c303a7d0c504805e43b7813f6f838a49cbf48af0b6e502c7a7",
        "bytes": 1576721,
    },
    {
        "name": "semi-chibi-front.webp",
        "url": f"{RAW}/Neko3000/deepseek-whalechan/main/skills/whalechan-image-character/"
               f"assets/reference-images/semi-chibi/neutral_standing_front_isolated.webp",
        "sha256": "e27638afe71cbc7edfa770b2f21201b627c7fb10f92d532a91f5e99563d24824",
        "bytes": 96320,
    },
    {
        "name": "CHARACTER.md",
        "url": f"{RAW}/Mizimo/whale-girl-visual-language-v4/main/docs/CHARACTER.md",
        "sha256": "dff00a1d9dffa180a9e165fef076c8757e891b57e4aa006f63ae55b2a07735b8",
        "bytes": 6439,
    },
    {
        "name": "original-design-assets.json",
        "url": f"{RAW}/Mizimo/whale-girl-visual-language-v4/main/assets/original-design/assets.json",
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


def fetch(a, dest, retries=4):
    path = os.path.join(dest, a["name"])
    if os.path.exists(path) and sha256_of(path) == a["sha256"]:
        print(f"  ✓ {a['name']:<28} 已存在且校验通过")
        return True
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(a["url"], headers={"User-Agent": "whale-chan-3d/fetch"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            got = hashlib.sha256(data).hexdigest()
            if got != a["sha256"]:
                print(f"  ✗ {a['name']:<28} SHA-256 不匹配")
                print(f"      期望 {a['sha256']}")
                print(f"      实际 {got}")
                return False
            with open(path, "wb") as f:
                f.write(data)
            print(f"  ✓ {a['name']:<28} {len(data)} bytes  SHA-256 校验通过")
            return True
        except Exception as e:
            if attempt == retries:
                print(f"  ✗ {a['name']:<28} 下载失败: {e}")
                return False
            print(f"  … {a['name']:<28} 第 {attempt} 次失败，重试中")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="reference")
    args = ap.parse_args()
    os.makedirs(args.dest, exist_ok=True)
    print(f"拉取参考素材 → {os.path.abspath(args.dest)}")
    ok = all(fetch(a, args.dest) for a in ASSETS)
    print("\n全部校验通过。" if ok else "\n存在校验失败项，请检查网络或上游变更。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
