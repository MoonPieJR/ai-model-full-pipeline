# 鲸鱼娘 3D · Image-to-3D 流程（生图 → 转模 → Blender 修整）

> 本目录是 **Fini.Yang 教程流程**的沙箱内复现版。
> 参考：[别再用 GPT-Astra 从零捏人物了，这套 3D 流程更靠谱](https://x.com/FiniYang/status/2097527014375002196)
> （Fini.Yang，2026-09-09 · 文章 ID 2097259059657486336）

---

## 一、教程原流程

| 步 | 动作 | 工具 |
|---|---|---|
| ① | 准备角色参考（四视图更好） | — |
| ② | **生图**：生成单个完整的 3D 手办效果图（白底、正面略带侧角、手臂离开身体、尾巴入镜） | GPT 生图 |
| ③ | 选转模路线，先确认**能不能拿到文件** | TRELLIS.2 / Tripo 3.1 / Tripo 2.5 / 混元 3D |
| ④ | 检查几何（脸/手/头发/衣服/尾巴有没有粘连长错）→ 确认纹理真的长在模型上 | 同上 |
| ⑤ | 导出**带贴图的 GLB**，导入 Blender 确认颜色和贴图没丢 | 同上 |
| ⑥ | 保留原始 GLB → 另存工程 → 渲染多角度找问题 → 针对缺陷修一版 | Astra + Blender |
| ⑦ | 出高清 PNG + 转台 MP4，保留带材质/灯光/动画的 `.blend` | Blender |

> 教程的核心结论：**从零写代码捏人物 = 翻车；先生图 → 转模型 → Blender 修整 = 第二版终于能看。**

---

## 二、本次的实际执行路径

沙箱环境受限，教程里的三个转模服务**没有一个能直接用**：

| 教程选项 | 沙箱实测 | 结论 |
|---|---|---|
| TRELLIS.2 官方试玩 | `trellis.microsoft.com` 443 不通 | ❌ |
| TRELLIS.2 本地 | `huggingface.co` 不通；且沙箱 **2 核 CPU 无 GPU** | ❌ |
| Tripo 3.1 / 2.5 | 域名不通 | ❌ |
| Tripo 官方 API（connector） | **可用**，但该账户余额 `balance: 0`，所有生成类调用被账户侧拦截 | ❌ |
| 混元 3D 2.1 在线试玩 | 域名可达，但 `GET /api/3d/getuserinfo` → **401**，需微信/QQ 登录 | ❌ |
| **TripoSR（本地单图前馈重建）** | 权重走 `hf-mirror.com` 可达；**torchmcubes 有 CPU 版**；`run.py` 内置 CPU fallback | ✅ **采用** |

所以第 ③ 步落到 **TripoSR**（Stability AI × Tripo AI，MIT 许可，LRM 架构单图前馈重建）。
第 ② 步用 `matrix__generate_image`（走官方 image-generation skill 的参考图编辑通道）完成。

---

## 三、关键实现要点

### 3.1 生图：参考图要按「图1 / 图2」传对象，不能传裸字符串

`connector__matrix__generate_image` 的 `reference_images` 每项必须是
`{"url": ..., "mime_type": ...}`。传裸字符串数组会让 connector 在执行层崩掉
（`connector_tool_error ... latency_ms:0`），而不是返回上游的 400 校验错误。

```json
{"requests": [{"prompt": "...按图1、图2的参考...",
               "reference_images": [{"url": "<temp_url>", "mime_type": "image/png"}]}]}
```

参考图取自 `Mizimo/whale-girl-visual-language-v4` 的 `whale-design.png`
（基准设计稿）+ `Neko3000/deepseek-whalechan` 的 `neutral_standing_front_isolated.webp`
（semi-chibi 正面图），均由 `fetch_reference.py` 按 SHA-256 校验拉取。

### 3.2 抠背景：PIL `ImageDraw.floodfill` 替代 rembg

教程流程用的是 `rembg`（u2net）。沙箱里装 rembg 会带进 onnxruntime + 模型下载，
而我们的图是**纯米白背景**，用 floodfill 从画布四边泛洪即可：

```python
for pt in [(0,0), (w-1,0), (0,h-1), (w-1,h-1), ...]:
    ImageDraw.floodfill(im, pt, (255,255,255,0), thresh=34)
```

floodfill 只填充**与种子连通**的区域，所以角色内部的米白色（围裙、珍珠、眼睛高光）不会被误抠。

### 3.3 torchmcubes 装不上 → 用 scikit-image 顶替

torchmcubes 要编译 CUDA 扩展，沙箱**没有 CUDA、没有 Python 开发头文件**
（`Python.h` 缺失，`apt` 装不了 `python3-dev`）。
`skimage.measure.marching_cubes` 是纯 numpy 实现，且索引约定与 torchmcubes 一致：

```
volume[i, j, k]  ↔  verts[:, 0]=i, verts[:, 1]=j, verts[:, 2]=k
```

见 `stubs/torchmcubes.py`。

### 3.4 3GB 内存下要 mmap + 分块

| 措施 | 原因 |
|---|---|
| `torch.load(..., mmap=True)` + `load_state_dict(assign=True)` | checkpoint 1.7GB；默认 `load_state_dict` 会复制一份 → 峰值 3.4GB → OOM |
| 密度场**分块**采样（`CH = 1<<18`） | 一次性算 256³ 会让中间特征张量涨到 ~670MB |
| 顶点色同样分块 | 同上 |
| 密度场高斯平滑（σ=0.8） | marching cubes 在带噪等值面上会切出碎面 |

### 3.5 Blender 侧：朝向与标度

- TripoSR(internal z-up) → glTF(Y-up) → Blender(Z-up) 两次轴变换后，**人物正面朝世界 +Y**
  （实测常量 `FACE_AZIM = 0`）。
  曾尝试用「头部暗色顶点分布」自动探测正面，但单图重建时背面完全是推测的、
  脸又被头发遮挡，颜色启发式会判反 —— 改为固定实测值。
- **三角函数的朝向**：模型横躺时最长轴在 X，绕 Y 轴 −90° 把它转到 Z。
- **平移要作用在顶层父级**：子对象被旋转过的 pivot 挂住后，它的局部 Z 不等于世界 Z，
  直接改 `o.location.z` 会平移到错误方向。
- 改 `scale` / `location` 后必须 `bpy.context.view_layer.update()`，
  否则 `bound_box` 读到的还是旧矩阵（缩放「看起来没生效」）。

### 3.6 Laplacian 平滑用 numpy 而不是 Blender modifier

Blender 的 `LAPLACIANSMOOTH` modifier 在 5 万顶点网格上会直接**段错误**（3GB 内存）。
改成纯 numpy 的一环邻域均值迭代（`blender_pipeline.laplacian_smooth`）。

---

## 四、产物

| 文件 | 说明 |
|---|---|
| `model/whale-chan-i2d.glb` | 转模产物，10 万面，顶点色贴图 |
| `model/whale-chan-i2d.blend` | 修整后工程（含材质/灯光/转台动画设置） |
| `renders/*.png` | 1024² 四视角，Cycles 64 samples |
| `video/whale-chan-turntable.mp4` | 转台视频，720² / 24fps / 6 秒 / 匀速一圈 |
| `reference/figurine-prompt.md` | 生图用的完整 prompt（可复现） |
| `reference/figurine-front.jpg` | 生图产物（转模的输入图） |

---

## 五、两个版本的对比

同一角色的两条独立产出路线，各有取舍：

| | 程序化重建版 | Image-to-3D 版（本目录） |
|---|---|---|
| 路线 | 参考图 → 量测 → 参数化放样 | 生图 → TripoSR 转模 → Blender 修整 |
| 面数 | 28 部件 / 235 部件，干净拓扑 | 99,154 面，marching cubes 碎面已平滑 |
| 头身比 | **精确 2.867**（规格可验证） | 由单图推测，不可控 |
| 贴图 | 渐变着色器（发色 Z 轴渐变） | 顶点色（TripoSR 直接烘的） |
| 脸部细节 | 眼/腮红/嘴为独立几何 | 糊（单图重建的固有短板） |
| 背面 | 按规格构造，可控 | 推测（教程里「尾巴位置不对」的彩蛋就出在这） |
| 可编辑性 | 高（每个部件独立） | 中（单网格） |

**建议**：要做动画/打印/改细节 → 用程序化版；
要快速拿到「手办质感」的带贴图资产 → 用 Image-to-3D 版。

---

## 六、许可

- 本目录的脚本：MIT
- 产出模型与渲染图：**CC BY-NC-SA 4.0**（禁止商用）
- TripoSR 代码与权重：MIT（Stability AI × Tripo AI）
- 角色形象著作权：上善无形（一创）→ ZipZipPipe（二创）→ 社区

详见 `NOTICE.md`。

---

## 6. 颜色修复：三轮迭代与最终方案

TripoSR 重建出来的**几何**其实很准（呆毛 / 鳍耳 / 蕾丝 / 裙褶 / 围裙 / 袜 / 鞋 / 尾巴
全在），错的是**颜色**。实测数据：

| 高度带 | 模型顶点色 (0-255) | 参考图角色色 (0-255) |
|---|---|---|
| 裙部 (0.62–0.75) | (124, 134, 153) | (74, 78, 116) |
| 底部 (0.88–1.00) | (132, 147, 165) | (100, 93, 107) |

模型整体**偏亮偏灰**（饱和度 0.26 vs 参考图 0.37），且在肩胸/领口位置
残留少量高饱和紫洋红色点。

### 试过但放弃的方案

| 方案 | 结果 | 放弃原因 |
|---|---|---|
| 像素级反投影（参考图逐像素投回顶点） | 头发被染褐、裙子出现乱涂的金色刺绣线 | 空间对齐误差会把颜色"糊"到错误部位；单图重建的背面完全是推测，风险 > 收益 |
| 分带 + 色相偏移迁移 | 整体变成粉紫，**原有色斑被放大** | ΔH 最大到 +0.24，把蓝直接推成红紫 |
| 全局色相迁移 | 同上 | 同上 |

### 最终方案（三步，全部零空间对齐）

1. **`band_transfer.py` — 分带色调迁移**
   模型与参考图各按归一化高度切 8 带，每带独立算 `ΔH / kS / kV`。
   两边都**剔除近白像素**（亮度 > 0.86）—— 参考图里蕾丝/围裙/袜子是大面积白色，
   计入统计会把目标明度拉高，迁移方向会反过来（越迁越亮）。
   最终取 **ΔH = 0**（只提饱和度，不动色相，避免放大色斑）、
   **kS = 1.45**、**kV = 0.88**。

2. **`despeckle_glb.py` — 色点抹平**
   从 GLB 的 `indices` 建顶点邻接表（纯 numpy，不需要 Blender），
   把"色相落在紫洋红区且饱和度 > 0.22"的 **1,830 个错误色点**
   用邻居顶点平均色替换（抹平，而非硬改成某个颜色）。
   合法暖色只有皮肤（低饱和淡粉）与金色，故阈值取 S > 0.22 可安全区分。

3. **渲染侧** — 材质饱和度 1.75、灯光 Key 80 / Fill 28 / Rim 60、World 0.30，
   背景用 **compositor Alpha Over 到精确米白**（sRGB 240,226,215，与参考图一致）。
   World 强度同时决定环境光和背景色，两者解不开；分开后背景才能对得上参考图。

### 两个色彩空间的坑

| 坑 | 现象 | 结论 |
|---|---|---|
| Blender `image.pixels` **不做** sRGB→线性转换 | 参考图统计 V=0.71，实际应为 0.46 | 读到的已是 sRGB 值，**别再转一次** |
| Blender glTF 导出器**丢顶点色** | 警告 `The active Vertex Color will not be exported` | "带贴图 GLB"是核心交付物 → **直接在 GLB 二进制层改写 COLOR_0** |

### 剩余瑕疵

- 面部特征仍模糊（TripoSR 单图分辨率上限）
- 胸前残余少量紫调（H 0.65–0.68 区间，位于阈值边缘，再降会伤及正常蓝紫过渡）
- 裙身细条纹在重建后偏浅（原始分辨率不足，深蓝保留不完整）
- 背面（尤其尾巴根部）为模型推测

这四点属于 image-to-3D 路线的固有限制，不是管线 bug。

---

## 7. UV 贴图：把顶点色固化成真正的纹理

顶点色（COLOR_0）在 glTF 里是合法的颜色通道，但**很多查看器/引擎默认只读
baseColorTexture** —— 打开 GLB 会看到"没有贴图"。所以又做了一步：把顶点色
**烘焙成真正的 PNG 贴图**，GLB 里同时带 `TEXCOORD_0` + `baseColorTexture` + `COLOR_0`。

### 7.1 UV 方案：自己写 box projection，不用 Blender 的 smart project

TripoSR 出来的是 marching cubes 网格（99,154 个碎片三角形），Blender 的
`smart_project` 会把它拆成几万个小 UV 岛 —— 实测**贴图空间利用率只有 6.2%**，
贴图退化成马赛克。

改用逐面 box projection（`make_textured_glb.py`，全 numpy）：

| 步骤 | 做法 |
|---|---|
| 分组 | 逐三角面算法线，按主轴分到 6 组（±X / ±Y / ±Z） |
| 投影 | 每组投影到对应的 2D 平面，各占贴图的 1/6（2 列 × 3 行） |
| 拆点 | glTF 的 UV 是 per-vertex，box mapping 是 per-face → 必须按 face-corner 拆顶点（49,577 → 297,462） |
| 烘焙 | numpy 光栅化（重心坐标插值 + z-buffer），**覆盖率 100%** |

因为贴图内容是「烘焙顶点色」得来的，UV 的拉伸**不影响正确性**，只影响把贴图
当独立图片看时的观感。

### 7.2 踩过的五个坑

| 坑 | 现象 | 结论 |
|---|---|---|
| `asset.version` 漏填 | Blender 报 `Bad glTF: no version` | 这个报错指的是 **asset.version**，不是文件头 |
| bufferView 对齐按块数算 | Blender 拒绝导入 | 对齐必须按**字节数**（`len(blobs) % 4` 是错的） |
| z-buffer 方向反 | 贴图满屏黑洞、覆盖率 6.2% | 相机在 Blender −Y → export_yup 后 **glTF Z 越大越近**，要保留**最大** Z |
| 深度轴搞错 | 用高度当深度，贴图全乱 | `orient_up`/`normalize` 改的是 object transform，glTF 导出会变成 node TRS —— POSITION 仍是局部坐标。需先 `transform_apply` 把变换烘焙进 mesh |
| `normalized` accessor 未换算 | 颜色放大 256 倍 | Blender 导出顶点色会用 **UNSIGNED_SHORT normalized**（0..65535），读的时候要 `/65535` |

### 7.3 贴图版与顶点色版的颜色对齐

两条路在 Blender 里走的是不同的色彩管理路径：

- **Color Attribute**：BYTE_COLOR 存的是 sRGB 字节，但节点输出**不做线性化**，
  直接当线性值用（实测：值 0.5 → 渲染出 130/255）
- **PNG 贴图**：Blender 会做 sRGB → 线性转换

要对齐，PNG 里必须把 HSV 结果**再 sRGB 编码一次**：

```
顶点色 sRGB → HSV(S=1.75) → res        （= 顶点色版的 Base Color）
PNG 存 lin2srgb(res) → Blender 线性化 → 正好还原 res
```

实测对齐后两者渲染均值差 **< 3%**（只剩 8bit 量化误差）：
顶点色版 `(86.4, 100.8, 120.4)` vs 贴图版 `(84.1, 98.3, 117.4)`。

### 7.4 交付的 GLB 结构

| 通道 | 内容 |
|---|---|
| `POSITION` / `NORMAL` | 297,462 顶点（按 face-corner 拆点） |
| `TEXCOORD_0` | box projection UV（2×3 布局） |
| `COLOR_0` | BYTE 顶点色（供只读顶点色的查看器） |
| `baseColorTexture` | 内嵌 PNG（2048²，mipmap + Linear 过滤 + EXTEND 环绕） |
| `material` | metallic 0 / roughness 0.62 / doubleSided |

---

## 8. 重做贴图：把参考图当作唯一色彩真值（v2）

### 8.1 为什么要推翻 v1

v1 的贴图**颜色源头是 TripoSR 的顶点色**。而 TripoSR 从单图重建时，把原图里
深藏青的裙子、白围裙、蓝渐变头发全洗成了灰白，还残留紫洋红色斑；v1 做的
"分带色彩迁移 + 色点抹平"只是在这份错误色彩上打补丁，box projection 又把
少量错误顶点色斑**拉成大色块** —— 结果就是：

> 贴图既不像原图，渲染出来也不像原图。

用户反馈"这个贴图效果和原图片看起来差的太多了"，问题不在贴图格式，
**在颜色源头**。

### 8.2 v2 做法：把参考图正交投影回网格

不再修顶点色，直接把 `fig2.jpg` 当作**唯一色彩真值**投到模型上
（`retexture_ref.py`，全 numpy/scipy，不依赖 Blender）：

| 步骤 | 做法 |
|---|---|
| 抠像 | 背景是**柔和渐变**，全局阈值切不掉 → 用 PIL `ImageDraw.floodfill` 从画布四边泛洪 |
| 配准 | 把模型剪影投到参考图画布，与参考图 alpha 做 **IoU 优化**（scale_x/scale_y/tx/ty + 是否镜像）。**单图重建无法靠启发式猜朝向**，只能让数据说话 |
| 镜像判定 | IoU 自动判定：镜像 0.803 vs 不镜像 0.584 → **重建网格相对原图是镜像的**（尾巴在右 vs 在左） |
| 去光照 | 原图是「渲染图」，明暗烘焙在里面 → 低频压平（retinex 式）得到干净 albedo，否则模型会被二次打光 |
| 外扩 | 模型剪影比参考图胖 → 用「最近角色像素色」向外延伸 28px，边缘不出现背景米白 |
| 投影 | **逐行轮廓对齐**：每行把模型的 x 范围对齐到参考图该行的 x 范围（重建网格内部比例与原图有偏差，实测头部中心偏 0.14 BU，全局仿射会把脸错位到头发上）。只用**平移**、缩放保持全局，避免逐行缩放把贴图撕成条纹 |
| UV | 正面 / 背面用 XY 平面投影，朝上朝下的面单独投影到顶/底格（内容取角色轮廓的"天际线色"） |
| 预滤波 | 按**区域压缩率**（累计 UV 面积 / 可见 UV 面积）做变半径模糊，等价于自己给贴图生成 mipmap —— 细发丝层层重叠处贴图被过度采样，不滤波就会出摩尔纹横条纹 |

### 8.3 结果

- 贴图本体**就是原图**（正面大格 = 参考图正交投影），独立看也是原图
- 深藏青裙子 + 金色刺绣 + 白色蕾丝围裙 + 小鲸鱼徽章 + 蓝渐变头发全部还原
- 贴图尺寸 3072²，GLB 内嵌 PNG，另发一份独立 PNG

### 8.4 已知短板（如实说明）

| 短板 | 原因 |
|---|---|
| 头部仍有横条纹、看不到五官 | TripoSR 单图重建的脸是**无五官的平滑块**，细发丝几何在平面投影下被扭曲 —— 属于 image-to-3D 固有限制，不是贴图错 |
| 背面/侧面为推测 | 单张正面图没有背面信息，背面用镜像正面填充，侧面用轮廓边缘色 |
| 局部比例与原图有偏差 | 重建网格与原图轮廓 IoU 0.803，逐行平移已修正大部分，残余部分无法完全消除 |

**若要真正接近原图**：需要更好的转模服务（Tripo 3.1 / TRELLIS.2 有 GPU 的环境）
拿到带五官的网格，再用本仓库的投影贴图流程合成 —— 投影部分可以原样复用。
