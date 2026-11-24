# NOTICE — 鲸鱼娘 3D 模型衍生作品

本目录下的模型（`model/whale-chan.blend`、`model/whale-chan.glb`）与渲染图
（`renders/*.png`）是 **DeepSeek 鲸鱼娘（Whale-chan）** 社区形象的衍生作品。

---

## ⚠️ 许可总览

| 内容 | 许可 | 商业用途 |
|---|---|---|
| **模型产物**（.blend / .glb / renders） | CC BY-NC-SA 4.0 | ❌ 禁止 |
| **建模脚本**（`model/scripts/*.py`） | MIT | ✅ 允许 |
| **上游参考素材**（不随仓库分发，按需下载） | CC BY-NC-SA 4.0 | ❌ 禁止 |
| 方法论参考（`dsh-blender-plugin` 的 SOP） | BSD-3-Clause | ✅ 允许 |

> 许可**分层**：建模代码可商用，但基于鲸鱼娘形象产出的模型本身属于
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

| 素材 | 来源仓库 | 作者 |
|---|---|---|
| 基准全身设计稿 | [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4) | 社区整理，原始形象著作权归上善无形 / ZipZipPipe |
| semi-chibi 分形态参考图 | [Neko3000/deepseek-whalechan](https://github.com/Neko3000/deepseek-whalechan) | Neko3000 及社区贡献者 |
| 角色规范与配色 | [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4) | 同上 |

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
3. **注明修改**（本作品为三维参数化重建，非原画复制）
4. **不得用于商业用途**

---

## 参考方法论

建模流程参考了 [sixtysevenlf/dsh-blender-plugin](https://github.com/sixtysevenlf/dsh-blender-plugin)
的「参考图通用还原 SOP」思路（BSD-3-Clause）：先量测比例 → 参数化放样 → 同机位渲染验收。
本项目为**独立实现**，未复制其代码；仅在流程思路上致谢。
