# NOTICE — 鲸鱼娘 Image-to-3D 版衍生作品

本目录下的模型（`model/whale-chan-i2d.blend`、`model/whale-chan-i2d.glb`）、
渲染图（`renders/*.png`）与转台视频（`video/whale-chan-turntable.mp4`）是
**DeepSeek 鲸鱼娘（Whale-chan）** 社区形象的衍生作品。

---

## ⚠️ 许可总览

| 内容 | 许可 | 商业用途 |
|---|---|---|
| **模型产物**（.blend / .glb / renders / video） | CC BY-NC-SA 4.0 | ❌ 禁止 |
| **管线脚本**（`model/scripts/*.py`、`*.sh`） | MIT | ✅ 允许 |
| **转模引擎** TripoSR | MIT | ✅ 允许 |
| **上游角色素材**（不随仓库分发，按需下载） | CC BY-NC-SA 4.0 | ❌ 禁止 |

> 许可**分层**：管线代码与第三方引擎可商用，但基于鲸鱼娘形象产出的模型本身属于
> CC BY-NC-SA 4.0 衍生品，**禁止商业使用**。二者不可混淆。

---

## 署名链（必须完整保留）

鲸鱼娘形象并非原创，创作链如下：

| 阶段 | 作者 | 时间 | 贡献 |
|---|---|---|---|
| **一创** | 上善无形 | 2025-06 | 原创角色「溟月」——确立蓝色渐变长发、头顶呆毛、鲸类鳍耳、鲸鱼尾等基础特征 |
| **二创** | ZipZipPipe | 2026-04-25 | 基于「溟月」加入 DeepSeek 元素，改造为深蓝白女仆裙的「女仆鲸鱼娘」，正式定型 |
| **三创** | 社区创作者 | 2026-07 起 | 表情包、桌宠、皮肤、3D 打印手办等大量衍生作品 |

### 参考素材署名

| 素材 | 来源 | 作者 |
|---|---|---|
| 角色基准形象 | [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4) | 社区整理，原始形象著作权归上善无形 / ZipZipPipe |
| semi-chibi 分形态参考图 | [Neko3000/deepseek-whalechan](https://github.com/Neko3000/deepseek-whalechan) | Neko3000 及社区贡献者 |

---

## 本版方法论出处

本版按 **Fini.Yang** 发布的「先生图 → 转模型 → Blender 修整」工作流复现：

| 项目 | 链接 |
|---|---|
| 教程原文 | [x.com/FiniYang/status/2097527014375002196](https://x.com/FiniYang/status/2097527014375002196) |
| 教程作者 | Fini.Yang |

教程中给出的三条在线转模路线（TRELLIS.2 / Tripo / 混元 3D）在本次构建环境内
**均不可用**（详见 `model/scripts/README-i2d.md`），因此本版改用
**[VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR)**（MIT）
在本地 CPU 上完成单图前馈重建，**流程结构与教程完全一致**，仅替换了转模后端。

### 各环节工具

| 环节 | 工具 | 许可 |
|---|---|---|
| 角色参考图 | `Mizimo/whale-girl-visual-language-v4` | CC BY-NC-SA 4.0 |
| 手办效果图生成 | MiniMax image generation（Matrix 连接器） | 见平台条款 |
| 单图转 3D | [TripoSR](https://github.com/VAST-AI-Research/TripoSR) | MIT |
| 几何修整 / 渲染 / 转台 | Blender 4.2 LTS | GPL（仅作工具使用，不分发） |

---

## 修改说明（CC BY-NC-SA 4.0 要求）

本作品**并非**原画的像素级复制，而是：

1. 以参考图经**扩散模型重绘**生成的手办效果图作为中间输入；
2. 由 TripoSR 做**单图前馈三维重建**，背面、底部为模型推测；
3. 在 Blender 中做**朝向矫正、顶点色重建（CORNER→VERTEX 聚合）、Laplacian 平滑、
   灯光与构图调整**；
4. 顶点色再经**分带色调迁移**与**色点抹平**，随后用自写的 box projection 烘焙成
   **2048² UV 纹理贴图**（UV + baseColorTexture + COLOR_0 三通道齐备）。

原画的著作权与署名权归上述作者所有。

### 产物清单

| 文件 | 内容 |
|---|---|
| `model/whale-chan-i2d.blend` | Blender 工程（材质/灯光/相机） |
| `model/whale-chan-i2d.glb` | 带 UV + 内嵌 baseColorTexture + 顶点色的 GLB |
| `model/whale-chan-i2d-basecolor.png` | 独立贴图（2048²） |
| `renders/*.png` | 四视角 1024² 渲染图 |
| `video/whale-chan-turntable.mp4` | 转台动画 |

---

## 商标声明

**DeepSeek** 名称、蓝色鲸鱼 logo 及相关品牌归其各自权利人所有。
本项目为**非官方**社区衍生创作，与 DeepSeek（杭州深度求索人工智能基础技术研究有限公司）
无隶属关系，不代表其认可。

---

## 内容准则

本模型及配套渲染图应遵循健康、合规、积极的创作准则，
严禁用于任何违法违规、侵犯第三方合法权益或违反各模型供应商使用政策的场景。

---

## 分发要求

依据 CC BY-NC-SA 4.0，再分发本目录内容时必须：

1. **保留本 NOTICE 与署名链**
2. **以相同许可（CC BY-NC-SA 4.0）共享**衍生作品
3. **注明修改**（本作品为三维重建 + 修整，非原画复制）
4. **不得用于商业用途**
