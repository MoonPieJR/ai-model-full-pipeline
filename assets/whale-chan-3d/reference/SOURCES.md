# 参考素材来源与校验

本目录**不存放**第三方图片。建模所需的参考图全部从上游仓库按 SHA-256 校验后拉取，
以避免在衍生仓库内叠加他人美术素材的许可。

## 素材清单

### 1. 基准全身设计稿

| 项 | 值 |
|---|---|
| 文件 | `whale-design.png` |
| 上游 | `Mizimo/whale-girl-visual-language-v4` |
| 路径 | `assets/original-design/whale-design.png` |
| 原始 URL | `https://raw.githubusercontent.com/Mizimo/whale-girl-visual-language-v4/main/assets/original-design/whale-design.png` |
| 尺寸 | 937 × 1678 |
| 大小 | 1,576,721 bytes |
| SHA-256 | `04aa326d4e19c4c303a7d0c504805e43b7813f6f838a49cbf48af0b6e502c7a7` |
| 许可 | CC BY-NC-SA 4.0 |
| 用途 | 全身造型基准：服装层次、裙摆结构、配色分区 |

> SHA-256 与上游仓库自带的 `assets/original-design/assets.json` 记录一致，可验证文件未被改动。

### 2. semi-chibi 正面孤立参考图（**主要建模输入**）

| 项 | 值 |
|---|---|
| 文件 | `semi-chibi-front.webp` |
| 上游 | `Neko3000/deepseek-whalechan` |
| 路径 | `skills/whalechan-image-character/assets/reference-images/semi-chibi/neutral_standing_front_isolated.webp` |
| 原始 URL | `https://raw.githubusercontent.com/Neko3000/deepseek-whalechan/main/skills/whalechan-image-character/assets/reference-images/semi-chibi/neutral_standing_front_isolated.webp` |
| 尺寸 | 1024 × 1024 |
| 大小 | 96,320 bytes |
| SHA-256 | `e27638afe71cbc7edfa770b2f21201b627c7fb10f92d532a91f5e99563d24824` |
| 许可 | 见上游仓库 LICENSE-CC-BY-NC-SA-4.0 |
| 用途 | 比例测量、轮廓比对、头身比验收 |

### 3. 角色规范与配色表

| 项 | 值 |
|---|---|
| 文件 | `CHARACTER.md` |
| 上游 | `Mizimo/whale-girl-visual-language-v4` |
| 路径 | `docs/CHARACTER.md` |
| 大小 | 6,439 bytes |
| SHA-256 | `dff00a1d9dffa180a9e165fef076c8757e891b57e4aa006f63ae55b2a07735b8` |
| 许可 | CC BY-NC-SA 4.0 |
| 用途 | 配色十六进制值、不可变识别点清单 |

### 4. 上游授权记录

| 项 | 值 |
|---|---|
| 文件 | `original-design-assets.json` |
| 来源 | `Mizimo/whale-girl-visual-language-v4` → `assets/original-design/assets.json` |
| 大小 | 1,013 bytes |
| SHA-256 | `fe4f5cdaa25f00660d3414a546de13f2992da79fbae5c90255eb2ec3d6124b07` |
| 用途 | 上游对每个文件的 SHA-256 与元数据清理声明，用于交叉验证 |

## 拉取方式

```bash
python3 fetch_reference.py --dest ./reference
```

脚本会逐个下载并 **校验 SHA-256**，不匹配即报错退出。

### 双通道自动回退

| 通道 | 用途 |
|---|---|
| HTTPS → `raw.githubusercontent.com` | 通用环境走这条 |
| git/SSH → `git@github.com:<repo>.git` + sparse-checkout | 沙箱 / 内网常封禁 443 出网，但 SSH 通常可用 |

HTTPS 失败时脚本自动切换到 git/SSH，无需手动干预。两条通道拿到的文件
都经过同一套 SHA-256 校验。

> 本次交付时沙箱环境即属后者（HTTPS 443 被阻断），脚本已实测走 git/SSH 通道完成全部四个文件的校验拉取。

## 上游项目

| 项目 | 角色 | 许可 |
|---|---|---|
| [Neko3000/deepseek-whalechan](https://github.com/Neko3000/deepseek-whalechan) | 角色规范、分形态参考图、Agent Skill | 代码 MIT / 文档与美术 CC BY-NC-SA 4.0 |
| [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4) | 基准设计稿、配色规范 | CC BY-NC-SA 4.0 |
| [sixtysevenlf/dsh-blender-plugin](https://github.com/sixtysevenlf/dsh-blender-plugin) | 参考图还原方法论（SOP）参考 | BSD-3-Clause |
