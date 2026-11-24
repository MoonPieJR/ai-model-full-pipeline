# 素材来源与校验

本目录存放 Image-to-3D 管线**直接产物**：`fig2.jpg` —— 它是本次构建过程中
用扩散模型生成的手办效果图，属衍生作品的一部分，随仓库分发。

上游第三方参考图（角色基准设计稿、分形态参考图）**不在此目录**，请到
`../whale-chan-3d/reference/` 按其 `fetch_reference.py` 拉取校验。

## 1. 手办效果图（TripoSR 唯一输入）

| 项 | 值 |
|---|---|
| 文件 | `fig2.jpg` |
| 来源 | 本次构建经 MiniMax image generation 生成（参考图 + prompt 见 `figurine-prompt.md`） |
| Drive node_id | `466702376399188` |
| 尺寸 | 3552 × 4736 |
| 大小 | 2,473,280 bytes |
| SHA-256 | `d7c407c019f6cfa3cb0188e5f0aefbbbc02fd4c19364d5ea9ccab9bdd92bf0c2` |
| 许可 | CC BY-NC-SA 4.0（继承鲸鱼娘角色形象） |
| 用途 | TripoSR 单图前馈重建的唯一输入 |

> 另有一张备选 `fig1.jpg`（node `466701893927214`，SHA-256 `0db7632eea4c1372eef7ae1173c5b5ebebcee505443c73cd40a263e6d6376cdf`）
> 未入库 —— 选片判据见 `figurine-prompt.md`。

## 2. 上游第三方参考图（不随仓库分发）

| 素材 | 上游 | SHA-256 |
|---|---|---|
| 基准全身设计稿 `whale-design.png` | `Mizimo/whale-girl-visual-language-v4` | `04aa326d4e19c4c303a7d0c504805e43b7813f6f838a49cbf48af0b6e502c7a7` |
| semi-chibi 正面参考图 `semi-chibi-front.webp` | `Neko3000/deepseek-whalechan` | `e27638afe71cbc7edfa770b2f21201b627c7fb10f92d532a91f5e99563d24824` |
| 角色规范与配色 `CHARACTER.md` | `Mizimo/whale-girl-visual-language-v4` | `dff00a1d9dffa180a9e165fef076c8757e891b57e4aa006f63ae55b2a07735b8` |

拉取方式见 `../whale-chan-3d/reference/fetch_reference.py`（HTTPS → git/SSH 自动回退，逐文件校验）。

## 3. 转模引擎

| 项目 | 角色 | 许可 |
|---|---|---|
| [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 单图 → 三维前馈重建（权重 `model.ckpt`） | MIT |
| [facebookresearch/dinov2](https://github.com/facebookresearch/dinov2) | TripoSR 内部特征编码器（`dinov2` 目录本地化） | Apache-2.0 |

> 注意：TripoSR 官方仓库为 `VAST-AI-Research/TripoSR`（非 Stability-AI 同名旧仓库）。
> 权重经 `https://hf-mirror.com` 镜像获取，HF 官方域名在部分沙箱环境不可达。

## 4. 上游项目

| 项目 | 角色 | 许可 |
|---|---|---|
| [Neko3000/deepseek-whalechan](https://github.com/Neko3000/deepseek-whalechan) | 角色规范、分形态参考图 | 代码 MIT / 文档与美术 CC BY-NC-SA 4.0 |
| [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4) | 基准设计稿、配色规范 | CC BY-NC-SA 4.0 |
| [Fini.Yang 的 X 帖子](https://x.com/FiniYang/status/2097527014375002196) | 「先生图 → 转模型 → Blender 修整」工作流出处 | 方法论参考 |
