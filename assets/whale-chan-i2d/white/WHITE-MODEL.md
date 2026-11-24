# 鲸鱼娘白模（White Model）—— 几何层交付

> 这一份**只管几何**：贴图与骨骼由你接手。
> 源自 TripoSR 单图重建的裸网格，经清理 / 归一化 / 重网格优化。

---

## 一、结论先说：选哪个版本

| 版本 | 顶点 | 三角面 | GLB | **头部** | 适合 |
|---|---|---|---|---|---|
| `white-high` | 49,449 | 98,922 | 1.78 MB | ❌ 发丝帘子 | 只做参考 / 细节比对，**不能贴脸** |
| `white-voxel0014` | 10,344 | 20,688 | 373 KB | ✅ 干净曲面 | **主推**：贴图 + 绑骨 |
| `white-voxel002` | 4,826 | 9,648 | 175 KB | ✅ 干净曲面 | 实时引擎 / 手机端 / 3D 打印 |
| `white-quad` | 29,559 | 29,562 四边面 | 1.07 MB | ✅ 干净曲面 | 想手工雕刻 / 改脸型再贴图 |

**关键发现（必须知道）**：

TripoSR 从单张正面图重建出的头部，**正面根本没有脸面几何** ——
纯白几何渲染放大后能看到，整颗头是一整块**竖向发丝帘子**（头发的沟槽），
没有任何五官凹陷。所以：

- 往 `white-high` 上贴脸 → 脸会被发丝沟槽**涂抹成条纹**（这就是之前渲染里脸花的根因）
- 往 `white-voxel*` / `white-quad` 上贴脸 → 头部是**连续光滑曲面**，贴图能干净落上去

见 `renders/head_compare.png`（左=高模头部，右=voxel 头部，同一角度同一尺度）。

---

## 二、四个版本各做了什么

### 处理链（`scripts/optimize_white.py`）

```
TripoSR 直出裸网格 (49,577 v / 99,154 f)
  ↓ 删碎屑        7 个连通分量，丢掉 6 个（24/8/48/8/136 面，共 232 面）
  ↓ 朝向矫正      最长轴 X → Z，绕 Y −90°
  ↓ 归一化        高 2.87 BU，脚底落在 Z=0，原点在脚底中心
  ↓ Laplacian ×2  纯 numpy 一环邻域均值（factor 0.45）—— Blender 的
  ↓               LAPLACIANSMOOTH modifier 会段错误
  ↓ 重网格        Voxel / Quad（各自再归一化一次，体素化会内缩 ~1.4%）
  ↓ Cube UV       Edit Mode → Cube Projection（每个版本都带 UV，可直接贴）
  ↓ 逐对象导出    use_selection=True，避免把整个场景打进一个文件
```

### 各版本的取舍

**`white-high`（原拓扑高模）**
保留了全部细节：裙子褶皱、蕾丝边、发饰、呆毛。但：
- 拓扑是 marching cubes 的产物，**不可雕刻、不可编辑**
- 面面积最大/最小比 **3957 万倍**（发丝尖端的极小面 vs 裙摆的大平面）→ 绑骨权重会很难受
- 头部不可贴脸

**`white-voxel0014`（主推）**
体素 0.014 BU。拓扑完全均匀、面尺寸一致，头部变成光滑曲面。
体素越小越贴近原形，0.014 是「脸部够干净」与「裙子褶皱还在」的平衡点。

**`white-voxel002`**
体素 0.02 BU。更轻（9,648 面），适合实时引擎。裙子基本被抹成锥形。

**`white-quad`**
在 voxel0014 基础上做 Quad（四边面）重网格。
**如果要手工改脸型、加眼睛凹陷、调整裙摆** —— 用这个。边流干净，四边面好控。
（Blender 4.2 的 `Remesh` modifier 在 SHARP 模式下没有 `target_faces`，
用的是 `octree_depth=7` + `scale=0.99`。）

---

## 三、坐标与单位约定

| 项 | 值 |
|---|---|
| 朝向 | **Z-up**，脚底在 Z=0，原点在脚底中心 |
| 正面朝 | **−Y**（Blender 惯例；glTF 导出后自动转成 Y-up） |
| 身高 | **2.87 BU**（各版本统一，体素化后已重新归一化） |
| 包围盒 | X 1.92 / Y 1.47 / Z 2.87 |
| UV | 每个版本都带 **Cube Projection** UV（Edit Mode → U → Cube Projection） |
| 顶点色 | 已移除（白模不带颜色，避免误导后续贴图） |
| 材质 | 单个灰模材质 `WM`（Principled，灰 0.72/0.74/0.78，roughness 0.55） |

> 尺寸 2.87 BU 是 Blender 单位。若导入 UE/Unity，按你的标准缩放
> （UE 常用 1 单位 = 1 cm，角色高 180 cm → 缩放 62.7；Unity 同理）。

---

## 四、你接手时要注意的

### 贴图
- 头部用 `white-voxel0014` 或 `white-quad`
- Cube UV 是盒式投影，**脸在 UV 上会有拉伸**（曲面法线越偏离投影轴越拉）
  → 想精细的话在 Blender 里对脸部区域单独 unwrap，或者用 triplanar 投影
- 裙子/褶皱的细节在 voxel 版里已经没了，贴图**要自己画上去**（原图里的金刺绣、蕾丝都是平面的，盒式投影正好够用）

### 绑骨
- 拓扑均匀 + 四边面（`white-quad`）最适合绑骨，权重不会撕裂
- 裙子：建议**给裙摆单独一组骨骼**，或者让裙面顶点绑到髋骨而不是腿骨 ——
  否则抬腿时裙摆会跟着甩
- 尾巴：TripoSR 重建出的鲸鱼尾在 −X 侧、z ≈ 0.38–0.45 H，需要 3 根尾骨
- 骨架建议用 **Mixamo 命名**（`mixamorig:Hips / Spine / ...`），游戏引擎直接能用
  （参考实现见 `scripts/rig_whalechan.py` 里的 `BONES` 表，已含 Mixamo 命名 + 3 节尾骨）

### 可选的进阶
`white-high` 和 `white-voxel0014` 可以**叠起来用**：
高模负责细节、voxel 负责干净的头 —— 但需要自己写 transfer，
多数情况下不值得，直接用 voxel 版更快。

---

## 五、想要更精细的几何？自己重跑就行

我们那个 patch 过的 `extract_mesh` **没有做 TripoSR 官方默认的 `rmesh=10` 简化**
（官方那步会把网格砍到约 1/10）。所以 49,449 顶点**已经是 256³ 的完整输出**，
不是被简化过的残次品。

要更精细只有一条路 —— **提高 marching cubes 分辨率**：

```bash
# 有 N 卡的话（本沙箱 2 核 CPU + 3GB 内存跑不动 512³）
cd scripts/
python run_triposr.py <你的参考图> --out out512 --mc-resolution 512 --device cuda
```

| 分辨率 | 预计顶点数 | 显存需求 | 说明 |
|---|---|---|---|
| 256（本仓库） | 49,449 | 3 GB 可跑（CPU） | 已交付 |
| 384 | ~17 万 | ~8 GB | 细节明显变多 |
| 512 | ~40 万 | ~12 GB+ | 脸部沟槽/发丝保留更多，但仍不是"脸" |

跑完再走一遍 `optimize_white.py` 就能得到同规格的高精白模。

> ⚠️ 即便 512³，**脸部依然不会有五官几何** —— 那是单图重建的信息上限，
> 不是分辨率问题。重网格出干净曲面 + 自己贴图/雕刻才是正解。

---

## 六、已知限制（如实说明）

1. **单图重建的固有上限**：背面、裙子内侧、尾巴根部都是 TripoSR 的推测，不是真实数据
2. **没有五官几何**：即使重网格后头部是干净曲面，**眼睛/鼻子/嘴仍然要靠贴图或手工雕刻**
3. **裙子细节丢失**：voxel 版把褶皱和蕾丝抹平了
4. **体素化会让形状略收**：已重新归一化到 2.87，但局部轮廓比高模「胖」一点点
5. **尾巴与身体是一体的**：TripoSR 把尾巴和裙子缝在了一起，需要分离的话得手动切

---

## 七、文件清单

```
white/
├── white-clean.blend          干净工程（4 个版本都在里面 + 灰材质 + 相机灯光）
├── white-high.{glb,fbx,obj}  原拓扑高模
├── white-voxel0014.{glb,fbx,obj}   ★ 主推
├── white-voxel002.{glb,fbx,obj}    轻量版
├── white-quad.{glb,fbx,obj}        四边面版
├── renders/
│   ├── white_high.png / white_voxel0014.png / white_voxel002.png / white_quad.png
│   ├── white_compare.png      四版本并排
│   └── head_compare.png       高模头部 vs voxel 头部（关键证据）
├── white_report.json          各版本顶点/面数/尺寸统计
└── WHITE-MODEL.md             本文件
```

复现脚本在 `scripts/`：
`optimize_white.py`（主流程）、`export_white.py`（导出+UV）、
`rig_whalechan.py` + `rig_weights.py`（绑骨参考实现）、
`diag_layers.py` / `diag_rig.py` / `diag_rig2.py` / `diag_markers.py`（诊断工具）。

---

## 署名与许可

本目录下的几何数据是 [DeepSeek 鲸鱼娘（DeepSeek-WhaleChan）](https://github.com/Neko3000/deepseek-whalechan)
衍生作品，角色原作者 **上善无形 / ZipZipPipe**，
源角色设定见 [Mizimo/whale-girl-visual-language-v4](https://github.com/Mizimo/whale-girl-visual-language-v4)。

> 本项目以 **CC BY-NC-SA 4.0** 发布：**禁止商用**，需署名并以相同方式共享。
> 详见同目录 `../NOTICE.md`。
>
> 重建后端 [TripoSR](https://github.com/VAST-AI-Research/TripoSR)（Stability AI + Tripo AI，MIT）。
