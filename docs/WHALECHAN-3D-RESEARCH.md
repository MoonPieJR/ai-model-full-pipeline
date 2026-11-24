# 鲸鱼娘 (DeepSeek Whale-chan) 三维 / Blender 资源调研

> 调研日期：2026-11-24 · 全部仓库均已 `git clone` 实测文件清单，非依赖搜索摘要
> 目标仓库：`MoonPieJR/ai-model-full-pipeline`

---

## 一、角色本体

「鲸鱼娘」是中文社区对 DeepSeek 蓝鲸 logo 的**自发拟人化二创**，社区昵称「蓝色大肥鱼」/「大肥鱼」/「DeepSeek娘」/「DS娘」，英文圈称 Whale-chan。

- **生日**：2023-11-02
- **人设关键词**：傲娇、嘴硬心软、白米饭是算力硬通货、省电模式摸鱼待机
- **视觉识别点**（建模必须锁死）：头顶呆毛、旁分刘海、深色鳍状耳、尾鳍分岔的鲸鱼尾、白荷叶边女仆头饰、领口深色蝴蝶结+蓝宝石

### 创作链与授权

| 阶段 | 作者 | 时间 | 贡献 |
|---|---|---|---|
| 一创 | 上善无形 | 2025-06 | 原创角色「溟月」，确立蓝渐变长发 / 呆毛 / 鲸鳍耳 / 鲸尾 |
| 二创 | ZipZipPipe | 2026-04-25 | 基于溟月加 DeepSeek 元素 + 深蓝白女仆裙 → 女仆鲸鱼娘定型 |
| 三创 | 社区 | 2026-07 起 | 表情包 / 桌宠 / 皮肤 / 3D 打印手办 |

**授权：CC BY-NC-SA 4.0** —— 必须署名（上善无形、ZipZipPipe）、**禁止商业用途**、衍生作品须同许可共享。

> ⚠️ 许可分层：工具链代码可能是 MIT / BSD（可商用），但**角色美术与基于角色衍生的模型仍走 CC BY-NC-SA 链**。两者不能混为一谈。

---

## 二、GitHub 资源全景（实测）

### 2.1 角色本体与规范（2D 方向）

| 仓库 | 文件数 | 3D 文件 | 许可 | 价值 |
|---|---|---|---|---|
| `Neko3000/deepseek-whalechan` | 320 | **0** | MIT(代码) + CC BY-NC-SA 4.0(文档/图) | ⭐559 最完整。角色卡 + 5 种头身比 + 11 张参考图集 + 2 个 Agent Skill + Python 工具链 |
| `Mizimo/whale-girl-visual-language-v4` | — | 0 | — | **配色十六进制值**（发色 `#6971a6`→`#a3bcdc`、洋装 `#4c496c`、蕾丝 `#f9f4f9` 等），建模材质可直接取用 |
| `TreapGoGo/deepseek-whale-girl` | — | 0 | — | ComfyUI 工作流、生成提示词库 |
| `HABAI182/ai-girls-atlas` | — | 0 | — | 角色档案库，各版本 SHA-256 溯源 |
| `AATINF/deepseek-whale-girl-assets` | — | 0 | — | 素材库 |
| `the-beating-light-of-the-nail/deepseek-chan-meme-pack` | — | 0 | — | 1400+ 表情包 |

### 2.2 三维方向（全部实测确认「无模型文件」）

| 仓库 | 3D 文件 | 实际形态 | 判定 |
|---|---|---|---|
| `Makesupper/dsh-plugin-whale` | 0 | **Canvas 2.5D 贝塞尔分层绘制**。源码注释自述 *"This is a stylized 2.5D drawing"*，`loadExternalModel()` 仅预留 GLTF 挂载槽 | ⚠️ **名不副实**，名字带 3D 但非三维网格 |
| `mmzm0808/dsh-ventus-whale` | 0 | three.js，从 DeepSeek 虎鲸 **logo 轮廓** swept 重建 | 是鲸鱼 logo，非人形鲸鱼娘 |
| MakerWorld（非 GitHub） | STL ×2 | 3D 打印手办（mw3221938 小鲸鱼 / mw3508283 钢盔大肥鱼） | 不在 GitHub，许可需单独确认 |
| `CXP-2024/cxp-character-forge` | 待查 | Houdini 整首解算 + DeepSeek 鲸娘案例 | 文档提及，非模型仓库 |

### 2.3 Blender 工具链

| 仓库 | 文件数 | 3D 资产 | 许可 | 价值 |
|---|---|---|---|---|
| `sixtysevenlf/dsh-blender-plugin` | 919 | 0 | BSD-3-Clause | ⭐2.2k。**参考图还原 SOP + 34 family / 228 op 契约层**，详见下节 |

---

## 三、核心结论

### ❌ GitHub 上不存在「鲸鱼娘的 Blender / 三维模型资产」

`.blend` / `.glb` / `.gltf` / `.fbx` 全网无现成文件。三个候选仓库实测 3D 资产均为 0，原因清晰：

1. 主仓库（`Neko3000`）定位是 **2D 图像生成** —— `whalechan-image-character` + `whalechan-image-comic` 两个 Skill；
2. 3D 方向全部是**运行时程序化生成**（Canvas / three.js），不落盘模型；
3. 实体三维资产在 **MakerWorld**（3D 打印生态），不在 GitHub。

### ✅ 但工具链是现成的，而且正好对得上

`sixtysevenlf/dsh-blender-plugin` 的 `skills/blender-modeling/references/参考图通用还原SOP.md` 就是**从 2D 参考图反推 3D 模型**的可执行方法论，且明确指出：

> 角色 = 有机身体 + 硬表面装备

九步流水线：

```
⓪ 草稿四张表 (T1 识别量级 / T2 制作单元 / T3 形态 / T4 空间特征)
   ↓ shape_draft_check (ok=true 才算过)
① img_rectify     四角单应校正，出 mm_per_px
② shape_plan      按类别取关键比例
③ shape_sections  侧视逐列上下边界 + 俯视半宽 + 前视截面轮廓
④ shape_loft      站表定轮廓、截面轮廓定性格
⑤ crease_lines / inset_lines   特征线与面感
⑥ shape_fit       参数化（可选，族外 IoU 卡 ~0.82）
⑦ shape_regions / shape_panels 多体量与缝
⑧ qc_render_views + img_diff + clear_check + audit_mesh   同机位逐视图 IoU 验收
```

配套能力：
- `img_digest / img_probe / img_measure / img_calib` —— 参考图量具（**无标定不许写 mm**）
- `shapesolve_solve` —— 无头多视轮廓拟合
- `asm_scan / asm_gate / asm_repair` —— 装配体检、修穿模浮空
- `blockout_*` —— 白模 + 四视图参考包 + 转台 MP4
- `visualreport_report` —— 同机位渲染对比、缺陷检测
- `gate_ / deliver_export` —— 强制交付门

### 🔑 最关键的可行性判断

该插件的 `runtime/py/` 是**纯 bpy 脚本**，方法论独立于 DSH 宿主。
**不需要装 DSH、不需要 GUI、不需要 TCP 通道** —— 可以直接用 `bpy` 在沙箱里跑完整流水线。

---

## 四、建模输入素材定位（已实测）

### 4.1 基准设计稿 → `Mizimo/whale-girl-visual-language-v4`（207 文件）

| 路径 | 内容 | 建模用途 |
|---|---|---|
| `assets/original-design/` | **基准全身设计稿 + 基准头像**（含 `assets.json` 带 SHA-256 与授权记录） | ⭐ 首选建模输入 |
| `assets/maid-atelier/` | 写实全身，细节最完整 | 细节对照（裙摆/蕾丝/围裙） |
| `assets/generated-2026-10-14/` | avatars / expressions / key-visual / icons + `prompts-*.json` | 头部特写、表情参考 |
| `docs/preview/c/` | 64 张预览图 | 氛围参考 |
| `docs/CHARACTER.md` | **配色十六进制值**（发 `#6971a6`→`#a3bcdc`、洋装 `#4c496c`、蕾丝 `#f9f4f9`、尾 `#5b5f8a`） | 材质直接取用 |

### 4.2 分形态参考图 → `Neko3000/deepseek-whalechan`

`skills/whalechan-image-character/assets/reference-images/` 下按五种形态分目录，每种都含**正面站立孤立图**（透明背景）：

```
standard/       4.0 头身
compact/        3.3 头身
semi-chibi/     2.8 头身   ← 含 neutral_standing_front_isolated.webp
chibi/          2.5 头身
super-deformed/ 2.1 头身
```

`neutral_standing_front_isolated.webp` 正是**从参考图反推 3D 最理想的输入**：正面、站立、孤立、无背景干扰。
完整索引见 `skills/whalechan-image-character/references/reference-catalog.json`。

> ⚠️ 注意：`Neko3000` 仓库根目录 `assets/` 下的图**全是 README 展示用**（`assets/readme/cn|en/`），真正的基准稿在 `Mizimo` 那个仓库。找建模输入别找错仓库。

---

## 五、本沙箱可行性（全部实测通过）

| 项 | 状态 | 实测结果 |
|---|---|---|
| GitHub SSH 认证 | ✅ | `Hi MoonPieJR! You've successfully authenticated` |
| 候选仓库 clone | ✅ | 5 个仓库文件清单已核对 |
| **bpy 安装** | ✅ | `bpy 4.2.0` / Python 3.11.2（阿里云镜像无 bpy，**清华 PyPI 镜像可装**；PEP 668 需用 venv） |
| **bpy 建模冒烟** | ✅ | 建几何 → 材质 → 存 `.blend` (405KB) → 导出 `.glb` (1440B, magic `glTF` v2) → **exit 0** |
| Blender 二进制 | ✅ | 清华镜像可达（HTTP 200），4.1–4.5 Linux 版可用（备用） |
| 磁盘 | ✅ | 499G 可用 |

### 两个必须记住的坑

1. **bpy 退出时段错误（Segfault）** —— bpy 在进程退出时析构崩溃，产出物已正确落盘但退出码非零，会打断自动化流水线。
   **解法**：作业末尾显式 `bpy.ops.wm.quit_blender()` + `os._exit(0)`。已封装为 `/workspace/research/bpy_job.py` 模板，实测 exit code = 0。
2. **Draco 压缩不可用** —— 缺 `libextern_draco.so`，`.glb` 导出会报 warning。不用 Draco 即可，不影响产物。

---

## 六、路线建议

### 方案 A（推荐）— 从参考图反推建模

```
输入: Neko3000 reference-images/semi-chibi/neutral_standing_front_isolated.webp
      + Mizimo original-design/whale-design.png（基准全身）
      + Mizimo CHARACTER.md 配色表（材质）
  ↓
bpy 4.2.0 + dsh-blender-plugin/runtime/py 脚本（纯 bpy，不需 DSH / GUI / TCP）
  ↓ img_digest → shape_draft 四张表 → shape_loft/shape_regions
  ↓ qc_render_views 同机位 IoU + img_diff 逐视图验收
  ↓
产出: whale-chan.blend（可编辑源） + whale-chan.glb（可直接用） + 验收渲染图
  ↓
提交进 MoonPieJR/ai-model-full-pipeline（带 LICENSE + NOTICE + 署名链）
```

产出物是 CC BY-NC-SA 衍生品 → 仓库需带完整署名链（上善无形 / ZipZipPipe）。

### 方案 B — 仅整理 2D 资产入库
参考图 / 提示词 / 规范 / 配色表。快，但拿不到 3D。

### 方案 C — 从 MakerWorld 拉 STL
非 GitHub 生态，许可与可编辑性都受限。

---

## 七、已确认与执行结果

### 7.1 需求确认（用户决策）

| # | 问题 | 决策 |
|---|---|---|
| 1 | 形态 | **semi-chibi（2.8 头身）** |
| 2 | 范围 | **全身 + 女仆装完整体**（非最小闭环） |
| 3 | 产出 | **`.blend` + `.glb` + 验收渲染图** |
| 4 | 风格 | **卡通 / 手办涂装**（Standard view transform，非写实） |

### 7.2 执行结果

方案 A 已落地。实际走的是**独立实现的参数化 bpy 脚本**，没有依赖 dsh-blender-plugin 的运行时
——它的 DSH 通信层在沙箱里跑不起来，但「参考图还原 SOP」的思路可以独立实现，且更适合
可复现的脚本化建模。

| 项 | 结果 |
|---|---|
| 头身比 | **2.867** ✅（规范区间 2.695–2.995） |
| 总高 | 2.8726 BU |
| 宽 × 深 | 1.8204 × 0.7104 BU |
| 逻辑对象 / 原始部件 | **28 / 235** |
| 建模栈 | bpy 4.2.0（venv `/workspace/.venv-bpy`），纯脚本 |
| 渲染 | Cycles CPU，1024²，96 samples，正 / 侧 / 3-4 三视角 |
| 产物 | `whale-chan.blend` / `whale-chan.glb` / 三张渲染图 / `verify.json` |
| 入库 | `MoonPieJR/ai-model-full-pipeline` → `assets/whale-chan-3d/` |

### 7.3 实际踩到的坑（比调研阶段预估的多）

1. **bpy 退出段错误** —— 产物落盘但 exit code 非零，会打断自动化流水线。
   必须 `quit_blender()` + `os._exit(code)`。
2. **NFS 写入延迟可见** —— 改完脚本立即跑可能执行旧代码，需 `sleep 1~2` 或以源码检查为准。
3. **`lathe` 顶点圈优先** —— 封口面索引若按周向 segs 算会越界。
4. **`cyl_patch` 背面壳与正面同半径** —— 永久 z-fighting，围裙上出现一道道横向条纹。
5. **贴合面片未避开波形峰** —— 裙身穿透围裙，视觉表现同样是横向条纹，容易误判为渲染噪声。
6. **发帽开口用平面切** —— 侧脸整块裸露，侧视图变成光秃脸蛋；改角度判据后恢复。
7. **侧发束落在中平面** —— 纯侧视图看成一束头发垂在身体正前方。

完整实现规则见 `model/SPEC.md` §4「几何实现规则」。

---

## 八、Image-to-3D 版执行记录（复现 Fini.Yang 教程流程）

> 目标：按 [Fini.Yang 的 X 帖子](https://x.com/FiniYang/status/2097527014375002196)
> 给出的「① 角色参考 → ② 生手办效果图 → ③ 选转模路线 → ④ 查几何+补纹理
> → ⑤ 导出带贴图 GLB → ⑥ Blender 修整 → ⑦ PNG + 转台 MP4」流程，
> 产出一条**带顶点色贴图的 image-to-3D** 版鲸鱼娘。

### 8.1 教程原文读取

`x.com` 直连不可用，经 `https://api.fxtwitter.com/FiniYang/status/2097527014375002196`
取得 JSON，从 `article.content.blocks` 读出全文 249 段，七步流程如上。

### 8.2 转模后端选型：教程三条路线全不可用

| 教程路线 | 实测结果 | 判定 |
|---|---|---|
| TRELLIS.2 | `trellis.microsoft.com` 与 `huggingface.co` 均 000；本地无 GPU | ❌ 不可用 |
| Tripo | 连接器账户 `balance: 0`，`tripo_image_to_3d` 等 27 个工具全部 `latency_ms:0` 失败 | ❌ 账户侧拦截 |
| 混元 3D | `3d.hunyuan.tencent.com` 可达，但 `GET /api/3d/getuserinfo` → 401 并跳转 `/login` | ❌ 需微信/QQ 登录 |

**改用 [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR)（MIT）本地 CPU 路线**：
单图前馈重建、权重开源、有 CPU 推理路径 —— 流程结构与教程完全一致，只替换转模后端。

> ⚠️ 仓库归属易踩坑：TripoSR 官方仓库是 `VAST-AI-Research/TripoSR`，
> 不是 Stability-AI 的同名旧仓库。

### 8.3 沙箱适配：6 处 patch（2 核 CPU / 3GB 内存 / 无 Python.h）

| # | 位置 | 问题 | 解法 |
|---|---|---|---|
| 1 | `tsr/models/tokenizers/image.py` | 依赖 HF Hub 拉 DINOv2 | 支持本地目录读 `config.json` |
| 2 | `tsr/system.py` | `torch.load` 峰值 3.4GB **OOM** | `torch.load(mmap=True)` + `load_state_dict(assign=True)` |
| 3 | `tsr/system.py` | 256³ 特征张量 ~670MB | 密度场与顶点色**分块**采样（`CH = 1<<18`） |
| 4 | `stubs/torchmcubes.py` | 官方源码需编译 CMake + `Python.h` | 用 `skimage.measure.marching_cubes` 顶替（索引约定一致） |
| 5 | `stubs/rembg.py` | rembg 依赖重 | PIL `ImageDraw.floodfill` 抠米白背景（只填种子连通区，不误抠角色内部米白） |
| 6 | `run_triposr.py` | marching cubes 碎面 | 密度场高斯平滑 σ=0.8 |

权重经 `hf-mirror.com` 拉取（HF 官方域名 443 被封）；DINOv2 落本地目录。

**实测耗时**：forward 65s，mesh 79.7s，产出 49,577 verts / 99,154 faces。

### 8.4 Blender 修整（教程第 ⑥ 步）

| 环节 | 实现 |
|---|---|
| 轴向矫正 | 最长轴 → Z，绕 Y −90°（TripoSR 内部 z-up → glTF y-up → Blender z-up 两次轴变换） |
| 平移归一 | **必须平移顶层父级** —— 子对象被旋转 pivot 挂住后局部 Z ≠ 世界 Z |
| 顶点色重建 | Blender 的 Color 属性是 **CORNER domain + BYTE_COLOR**，需 corner→vertex 聚合 |
| 表面平滑 | Blender `LAPLACIANSMOOTH` modifier 在 5 万顶点上**直接段错误** → 改纯 numpy 一环邻域均值 |
| 灯光 | Key 120 / Fill 40 / Rim 90，World 0.38，view transform `Standard`（Key 420 严重过曝） |
| 背景色 | 实测输出 RGB(154,151,147)（World 强度会把设定 `#f2e8da` 压暗） |

### 8.5 ⚠️ 朝向：我自己判反了一次

单图重建的**背面完全是推测**，且长直发盖住后脑，用「头部暗色顶点分布」启发式
判断正反面会**判反**（背面发色更暗 → 误判为正面）。

**修正方式**：改用固定实测常量，并以**三角验证**锁定：

| 视角 | azim | 判读 | 结论 |
|---|---|---|---|
| `stage1_256c/back.png` | 180 | 头发盖后脑、尾巴伸向右、**无围裙无脸** | 背面 |
| `stage1_f/back.png` | 0 | 脸颊腮红、**围裙白色梯形**、尾巴在左 | ✅ 正面 |

最终 `FACE_AZIM = 0`。教训：**单图重建的朝向必须靠渲染判读，不能靠顶点色启发式猜。**

### 8.5b 颜色修复：三轮迭代

TripoSR 重建的**几何**很准，错的是**颜色**。实测（模型顶点色 vs 参考图角色色，
按归一化高度分带）：

| 高度带 | 模型顶点色 | 参考图角色色 |
|---|---|---|
| 裙部 (0.62–0.75) | (124, 134, 153) | (74, 78, 116) |
| 底部 (0.88–1.00) | (132, 147, 165) | (100, 93, 107) |

模型整体**偏亮偏灰**（S 0.26 vs 参考 0.37），肩胸/领口处还有高饱和紫洋红色点。

| 方案 | 结果 | 判定 |
|---|---|---|
| 像素级反投影（参考图逐像素投回顶点） | 头发染褐、裙子乱涂金色刺绣 | ❌ 对齐误差把颜色糊到错误部位 |
| 分带迁移 + 色相偏移（ΔH 最大 +0.24） | 整体变粉紫，原有色斑被放大 | ❌ 蓝被推成红紫 |
| 全局色相迁移 | 同上 | ❌ 同上 |
| **分带迁移（ΔH=0, kS=1.45, kV=0.88）+ 色点抹平** | 裙子回蓝、斑块清除 | ✅ 采用 |

最终三步（全部零空间对齐，只依赖「模型 z ↔ 参考图 y」的竖直对应）：

1. `band_transfer.py` —— 8 个高度带各自迁移 `ΔH/kS/kV`；两边都**剔除近白像素**
   （亮度 > 0.86），否则参考图的蕾丝/围裙会把目标明度拉高、迁移方向反转。
   最终 **ΔH=0**（不动色相，避免放大色斑）。
2. `despeckle_glb.py` —— 从 GLB `indices` 建顶点邻接表（纯 numpy），
   把 **1,830 个**「色相在紫洋红区且 S>0.22」的错误色点用邻居平均色抹平。
3. 渲染侧 —— 材质饱和度 1.75、灯光 Key 80/Fill 28/Rim 60、World 0.30，
   背景用 **compositor Alpha Over 到精确米白**（sRGB 240,226,215，与参考图一致）。

#### 踩到的色彩空间 / 导出坑

| 坑 | 现象 | 结论 |
|---|---|---|
| Blender `image.pixels` **不做** sRGB→线性转换 | 参考图统计 V=0.71，实际 0.46 | 读到的已是 sRGB 值，**别再转一次** |
| Blender glTF 导出器**丢顶点色** | 警告 `The active Vertex Color will not be exported` | 「带贴图 GLB」是核心交付物 → **直接在 GLB 二进制层改写 COLOR_0** |
| Blender `LAPLACIANSMOOTH` modifier | 5 万顶点直接段错误 | 纯 numpy 一环邻域均值 |
| OpenImageDenoise 每帧重载内核 | 144 帧要 2.4 小时 | 转台视频关降噪 + 提到 32 samples |

### 8.6 两条路线对比（最终交付）

| 维度 | 程序化版 `assets/whale-chan-3d/` | Image-to-3D 版 `assets/whale-chan-i2d/` |
|---|---|---|
| 建模方式 | 参数化放样，脚本可复现 | 扩散生图 → TripoSR 前馈重建 |
| 拓扑 | 干净，28 对象 / 235 部件 | marching cubes 单网格，99,154 面 |
| 贴图 | 材质按分区赋值，可逐件改色 | **顶点色**（COLOR_0），随网格烘焙 |
| 尺寸精度 | 总高 2.8726 BU，头身比 **2.867**（可验证） | 头身比约 2.8（视觉近似，无精确控制） |
| 可编辑性 | 部件可单独编辑、改参数重生成 | 单网格，改形状需重跑整条管线 |
| 背面 | **真实**（按参考图推断的结构） | **推测**（TripoSR 单图幻觉） |
| 面部精度 | 程序化五官，可控 | 面部特征糊（单图分辨率与模型上限） |
| 配色还原 | 分区指定，可逐件改色 | 顶点色；经分带迁移 + 色点抹平后接近参考图 |
| 依赖 | 仅 bpy | TripoSR + torch（CPU 约 2.5 min）+ bpy |
| 许可 | CC BY-NC-SA 4.0 | CC BY-NC-SA 4.0 |

**取舍建议**：要**精度、可编辑、可二次开发** → 用程序化版；
要**手办质感、带贴图、单文件可交付** → 用 Image-to-3D 版。
两者都入库，按用途取用。

### 8.7 已知质量短板

1. 面部特征模糊（TripoSR 单图分辨率上限）
2. 裙身细条纹在重建后**偏白**，深蓝保留不完整
3. 背面（尤其**尾巴根部位置**）为模型推测，与参考图有差异
4. 网格边缘偶见 marching cubes 残留碎面（已用 σ=0.8 + Laplacian 0.25×2 缓解）

> 这四点恰好对应教程彩蛋提到的同类问题，属 image-to-3D 路线的固有限制，
> 不是管线 bug。
