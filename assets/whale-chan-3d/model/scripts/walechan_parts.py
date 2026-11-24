"""鲸鱼娘 semi-chibi —— 部件装配层

严格按 SPEC.md 的 BU 尺寸构建。28 个部件。
"""
import math
from mathutils import Vector

import bpy

from walechan_geom import (
    add_mesh, bead_arc, bow, cyl_patch, join_parts, lathe, lathe_wave, ribbon,
    sphere, tube,
)

# ── SPEC §0 关键锚点 (z) ────────────────────────────────────────────────
Z_TOP       = 2.649      # 头顶发际
Z_CHIN      = 1.647      # 下巴
Z_EYE       = 1.883      # 眼心
Z_SHOULDER  = 1.588
Z_WAIST_TOP = 1.368
Z_WAIST_BOT = 1.235
Z_SKIRT     = 0.603      # 裙摆底
Z_FOOT      = 0.0

HEAD_C, HEAD_R = 2.150, (0.50, 0.46, 0.50)


# ── 辅助：鳍耳（扁平薄片，带下缘浅色边） ────────────────────────────────
def fin_blade(name, base, tip, half_w, thickness, mat, waves=3):
    """圆润波浪的鱼鳍片（参考图里鲸鱼娘的鳍状耳）。

    宽度沿轴向按 sin 曲线起伏，上下缘再叠一层小波浪；前后有厚度。
    """
    base, tip = Vector(base), Vector(tip)
    axis = tip - base
    an = axis.normalized()
    wdir = Vector((0, 0, 1))
    wdir = (wdir - an * wdir.dot(an)).normalized()
    tdir = an.cross(wdir).normalized()

    N = 10
    top, bot = [], []
    for i in range(N + 1):
        t = i / N
        c = base + axis * t
        w = half_w * (math.sin(math.pi * (t ** 0.62)) ** 0.75)
        rip = 1.0 + 0.20 * math.sin(waves * math.pi * t * 2)
        top.append(c + wdir * (w * rip))
        bot.append(c - wdir * (w * rip))

    verts, faces = [], []
    for sgn in (1, -1):
        for p in top:
            verts.append(tuple(p + tdir * (thickness * 0.5 * sgn)))
        for p in bot:
            verts.append(tuple(p + tdir * (thickness * 0.5 * sgn)))
    off = (N + 1) * 2
    for i in range(N):
        a, b = i, i + 1
        faces.append((a, b, b + off, a + off))                      # 上缘
        faces.append((off + N + 1 + a, off + N + 1 + b, b, a))      # 下缘
    for i in range(N):
        a, b = i, i + 1
        faces.append((a, a + 1, b + 1, b))                          # 封边 A
        faces.append((off + a, off + b, off + b + 1, off + a + 1))  # 封边 B
    return add_mesh(name, verts, faces, mat, smooth=True)


# ── 各部件 ──────────────────────────────────────────────────────────────

def build_head(M):
    out = {}
    # 下巴收窄：球体下半部横向压缩
    head = sphere("Head", (0, 0, HEAD_C), HEAD_R, M["SKIN"], segs=48, rings=28)
    for v in head.data.vertices:
        if v.co.z < Z_CHIN:
            t = (Z_CHIN - v.co.z) / max(Z_CHIN - (HEAD_C - HEAD_R[2]), 1e-4)
            v.co.x *= 1.0 - 0.42 * t
            v.co.y *= 1.0 - 0.30 * t
    out["Head"] = head

    # 眼睛：鼓起的椭球嵌进脸面 + 虹膜 + 双高光
    # Y 向深度给到 0.062 —— 压太扁的话侧视图完全看不到眼睛的弧线。
    eyes = []
    for sx in (-1, 1):
        x = sx * 0.170
        e = sphere(f"Eye_{'L' if sx < 0 else 'R'}", (x, -0.352, Z_EYE),
                   (0.146, 0.062, 0.162), M["EYE"], segs=32, rings=20)
        eyes.append(e)
        eyes.append(sphere(f"EyeGloss1_{sx}", (x - 0.042, -0.400, Z_EYE + 0.058),
                           (0.046, 0.026, 0.046), M["WHITE"], segs=16, rings=10))
        eyes.append(sphere(f"EyeGloss2_{sx}", (x + 0.054, -0.400, Z_EYE - 0.034),
                           (0.026, 0.018, 0.026), M["WHITE"], segs=16, rings=10))
        # 眉
        eyes.append(sphere(f"Brow_{sx}", (x, -0.372, Z_EYE + 0.212),
                           (0.098, 0.028, 0.020), M["HAIR"], segs=20, rings=10))
    out["Eyes"] = eyes

    # 腮红：两颊淡粉
    for sx in (-1, 1):
        eyes.append(sphere(f"Blush_{sx}", (sx * 0.285, -0.300, Z_EYE - 0.145),
                           (0.082, 0.030, 0.046), M["BLUSH"], segs=16, rings=10))

    # 嘴：小弧
    mouth = []
    for i, (dx, dz) in enumerate([(-0.042, 0.0), (0.0, -0.014), (0.042, 0.0)]):
        mouth.append(sphere(f"Mouth_{i}", (dx, -0.430, Z_CHIN + 0.062 + dz),
                            (0.028, 0.016, 0.018), M["OUTLINE"], segs=12, rings=8))
    out["Mouth"] = mouth
    return out


def build_hair(M):
    out = {}
    # ── 发帽：上半球壳，前额开口露脸 ──
    cap = sphere("HairCap", (0, 0, HEAD_C), (0.528, 0.492, 0.530), M["HAIR"],
                 segs=48, rings=28)
    bm = cap.data
    import bmesh
    bmesh_mesh = bmesh.new()
    bmesh_mesh.from_mesh(bm)
    kill = []
    for f in bmesh_mesh.faces:
        c = f.calc_center_median()
        # 以「正前方为 0°」的角度判据开口，而不是平面切。
        # 平面切会让侧脸整块裸露（侧视图变成一颗光秃秃的脸蛋）；
        # 角度开口则保留两侧鬓发，脸只从正面 ±44° 扇区露出。
        ang = math.degrees(math.atan2(c.x, -c.y))
        if c.z < 2.34 and abs(ang) < 44:
            kill.append(f)          # 前额露脸
        elif c.z < 1.78:
            kill.append(f)          # 下缘开口（脖颈侧）
    bmesh.ops.delete(bmesh_mesh, geom=kill, context="FACES")
    bmesh_mesh.to_mesh(bm)
    bmesh_mesh.free()
    out["HairCap"] = cap

    # ── 刘海：额前弧线垂下的连续曲面帘（侧分，左长右短） ──
    bangs = []
    arc, widths = [], []
    for i in range(15):
        t = i / 14.0
        th = (t - 0.5) * math.radians(124)
        arc.append((0.452 * math.sin(th), -0.300 - 0.075 * math.cos(th), 2.372))
        # 侧分：靠左（约 t=0.32）最长，两端收短
        p = math.sin(math.pi * t) ** 0.75
        skew = 1.0 + 0.55 * math.exp(-((t - 0.30) ** 2) / 0.028)
        widths.append(0.125 + 0.175 * p * skew)
    bangs.append(ribbon("BangCurtain", arc, widths, M["HAIR"],
                        normal=(0, -1, 0), thick=0.022))
    # 帘前的 3 束立体发束，增加体积感
    for i, (x0, y0, z0, x1, y1, z1) in enumerate([
            (-0.40, -0.34, 2.38, -0.47, -0.42, 2.10),
            (-0.24, -0.42, 2.38, -0.33, -0.49, 2.07),
            (0.16, -0.41, 2.38, 0.10, -0.47, 2.24)]):
        path = [(x0, y0, z0),
                ((x0 + x1) / 2, (y0 + y1) / 2 - 0.015, (z0 + z1) / 2 + 0.02),
                (x1, y1, z1)]
        bangs.append(tube(f"BangLock_{i}", path, [0.058, 0.044, 0.007],
                          M["HAIR"], segs=14))
    out["Bangs"] = bangs

    # ── 两侧长发：每侧 3 束带卷曲的锥管 ──
    # 发束必须落在身体两侧偏后（y ≈ +0.06），末端收到臀部高度；
    # 若落在中平面（y≈0），侧视图会看成一束头发垂在身体正前方。
    sides = []
    for sx in (-1, 1):
        for k, (spread, phase, r0) in enumerate([(0.00, 0.0, 0.185),
                                                 (0.075, 1.1, 0.150),
                                                 (0.145, 2.2, 0.120)]):
            path, radii = [], []
            for i in range(13):
                t = i / 12.0
                z = 2.44 - t * (1.28 + 0.11 * k)
                wave = math.sin(t * math.pi * 3.1 + phase) * 0.078
                x = sx * (0.425 + spread + t * 0.115 + wave * 0.55)
                y = 0.088 + wave * 1.15 - t * 0.045
                path.append((x, y, z))
                # 尖梢：收成 0.004 半径，不做成等粗的管子
                radii.append(r0 * (1.0 - t) ** 0.85 + 0.004)
            sides.append(tube(f"HairSide_{'L' if sx < 0 else 'R'}_{k}",
                              path, radii, M["HAIR"], segs=18))
    out["HairSides"] = sides

    # ── 呆毛 ──
    out["Ahoge"] = tube("Ahoge",
                        [(0.08, -0.26, 2.60), (0.20, -0.38, 2.70),
                         (0.32, -0.44, 2.80), (0.26, -0.42, 2.868)],
                        [0.052, 0.046, 0.030, 0.007], M["HAIR"], segs=14)
    return out


def build_fin_ears(M):
    fins = []
    for sx in (-1, 1):
        base = (sx * 0.40, -0.02, 2.26)
        tip = (sx * 0.90, -0.10, 2.06)
        fins.append(fin_blade(f"FinEar_{'L' if sx < 0 else 'R'}", base, tip, 0.20, 0.055, M["FIN"]))
        # 下缘浅色边：沿鳍耳下缘的贴合细条（贴着鳍形走，不能悬空）
        base_v = Vector(base); tip_v = Vector(tip)
        axis = tip_v - base_v; an = axis.normalized()
        wdir = Vector((0, 0, 1)); wdir = (wdir - an * wdir.dot(an)).normalized()
        mid_v = base_v + axis * 0.45
        edge_path, edge_r = [], []
        for i in range(5):
            t = i / 4.0
            p = mid_v + (tip_v - mid_v) * (0.15 + t * 0.55) - wdir * (0.185 * (1.0 - 0.40 * t))
            edge_path.append(tuple(p))
            edge_r.append(0.017 - 0.008 * t)
        fins.append(tube(f"FinEdge_{sx}", edge_path, edge_r, M["FIN_LIGHT"], segs=8))
    return fins


def build_headband(M):
    """白色荷叶边头饰 + 头侧天蓝小蝴蝶结。

    头饰是一条**横向绕过额头**的弧（在 XY 平面张开、Z 略拱），
    不是竖直倒 U —— 否则会变成刺猬头。
    """
    path = []
    for i in range(21):
        t = i / 20.0
        th = (t - 0.5) * math.radians(152)      # -76° .. +76°
        path.append((0.452 * math.sin(th),
                     -0.238 - 0.055 * math.cos(th),
                     2.462 + 0.108 * math.cos(th)))
    band = bead_arc("Headband", path, 0.050, M["WHITE"], segs=14, rings=9)
    # 天蓝蝴蝶结（画面右 = +X）
    side_bow = bow("SideBow", (0.452, -0.300, 2.232), 0.100, M["BOW_SKY"], depth=0.55)
    return band + side_bow


def build_body(M):
    out = {}
    out["Torso"] = lathe("Torso", [
        (1.225, 0.150), (1.270, 0.149), (1.330, 0.152), (1.375, 0.163),
        (1.440, 0.207), (1.500, 0.252), (1.556, 0.279), (1.600, 0.290),
        (1.634, 0.264), (1.652, 0.212),
    ], M["DRESS_DEEP"], segs=48)

    out["Neck"] = lathe("Neck", [(1.575, 0.108), (1.680, 0.100)], M["SKIN"], segs=32)

    # 胸衣（白）+ 荷叶边
    out["Bustier"] = lathe("Bustier", [
        (1.372, 0.171), (1.430, 0.216), (1.490, 0.257), (1.545, 0.281), (1.588, 0.285),
    ], M["BUSTIER"], segs=48)
    frill = []
    for i in range(16):
        a = math.pi * 2 * i / 16
        frill.append(sphere(f"BustFrill_{i}", (0.178 * math.cos(a), 0.178 * math.sin(a), 1.386),
                            (0.046, 0.046, 0.034), M["WHITE"], segs=12, rings=8))
    for i in range(18):
        a = math.pi * 2 * i / 18
        frill.append(sphere(f"BustFrillTop_{i}", (0.292 * math.cos(a), 0.292 * math.sin(a), 1.586),
                            (0.040, 0.040, 0.032), M["WHITE"], segs=12, rings=8))
    out["BustierFrill"] = frill

    # 束腰（深蓝）
    out["Corset"] = lathe("Corset", [
        (1.230, 0.154), (1.270, 0.151), (1.320, 0.150), (1.368, 0.158),
    ], M["DRESS_DEEP"], segs=48)
    # 金纽扣 4 颗
    for i in range(4):
        for sx in (-1, 1):
            out.setdefault("Buttons", []).append(
                sphere(f"Btn_{i}_{sx}", (sx * 0.072, -0.152, 1.262 + i * 0.030),
                       (0.017, 0.017, 0.017), M["GOLD"], segs=10, rings=6))

    # 领口蝴蝶结 + 蓝宝石
    cb = bow("CollarBow", (0, -0.262, 1.598), 0.135, M["BOW_DARK"], depth=0.5)
    cb.append(sphere("CollarGem", (0, -0.305, 1.598), (0.034, 0.028, 0.034),
                     M["BOW_SKY"], segs=16, rings=10))
    out["CollarBow"] = cb
    return out


def build_arms(M):
    arms = []
    for sx in (-1, 1):
        path = [(sx * 0.262, -0.010, 1.556),
                (sx * 0.318, -0.040, 1.420),
                (sx * 0.336, -0.075, 1.240),
                (sx * 0.330, -0.115, 1.080),
                (sx * 0.328, -0.135, 1.020)]
        radii = [0.118, 0.104, 0.082, 0.062, 0.055]
        arms.append(tube(f"Sleeve_{'L' if sx < 0 else 'R'}", path, radii, M["DRESS_DEEP"], segs=18))
        # 蕾丝袖口
        for i in range(5):
            a = math.pi * 2 * i / 5
            arms.append(sphere(f"Cuff_{sx}_{i}",
                               (sx * 0.330 + 0.062 * math.cos(a), -0.128 + 0.062 * math.sin(a), 1.052),
                               (0.040, 0.040, 0.036), M["WHITE"], segs=12, rings=8))
        # 手
        arms.append(sphere(f"Hand_{sx}", (sx * 0.330, -0.150, 0.972),
                           (0.070, 0.052, 0.085), M["SKIN"], segs=18, rings=12))
    return arms


def build_skirt(M):
    out = {}
    # 主裙：周向带波浪，模拟裙摆起伏
    out["Skirt"] = lathe_wave("Skirt", [
        (1.238, 0.156), (1.180, 0.205), (1.100, 0.288), (1.000, 0.376),
        (0.900, 0.456), (0.800, 0.526), (0.700, 0.579), (0.640, 0.610),
        (0.603, 0.620),
    ], M["DRESS_DEEP"], segs=96, amp=0.026, waves=14)

    # 白色荷叶边：两道波浪薄裙边（比珠串更接近真实花边）
    out["SkirtTrim"] = [
        lathe_wave("SkirtFrillOuter", [(0.582, 0.634), (0.614, 0.652), (0.632, 0.660)],
                   M["WHITE"], segs=96, amp=0.048, waves=14),
        lathe_wave("SkirtFrillInner", [(0.616, 0.596), (0.648, 0.622)],
                   M["WHITE"], segs=96, amp=0.040, waves=14),
    ]

    # 金色刺绣带（圆环）
    ring_path = [(0.596 * math.cos(math.pi * 2 * i / 72),
                  0.596 * math.sin(math.pi * 2 * i / 72), 0.664) for i in range(73)]
    out["GoldBand"] = tube("GoldBand", ring_path, [0.012] * 73, M["GOLD"], segs=8)

    # 裙摆蝴蝶结 ×2
    for sx in (-1, 1):
        out.setdefault("SkirtBows", []).extend(
            bow(f"SkirtBow_{'L' if sx < 0 else 'R'}", (sx * 0.415, -0.250, 0.688),
                0.098, M["BOW_DARK"], depth=0.45))
    return out


def build_apron(M):
    """白色围裙 —— 贴合裙子前表面的曲面带，中央有小鲸鱼刺绣。"""
    out = {}
    # (z, 贴合半径)
    # 半径必须避开裙面 lathe_wave 的周向波峰（峰 = r * 1.026），否则裙面
    # 会在若干 z 区间穿透围裙 → 正面看是一道道横向条纹（z-fighting）。
    # 净空统一取 ≈0.018 BU。
    stations = [(0.717, 0.607), (0.820, 0.547), (0.950, 0.449), (1.100, 0.317),
                (1.230, 0.185), (1.300, 0.170), (1.372, 0.190), (1.452, 0.226)]
    half = math.radians(24)
    out["Apron"] = cyl_patch("Apron", stations, -math.pi / 2 - half, -math.pi / 2 + half,
                             M["WHITE"], segs=28, thickness=0.018, subdiv=4)
    # 围裙下摆荷叶边
    hem = []
    for i in range(15):
        t = i / 14.0
        x = -0.168 + t * 0.336
        hem.append(sphere(f"ApronHem_{i}", (x, -0.583, 0.708),
                          (0.034, 0.028, 0.030), M["WHITE"], segs=10, rings=7))
    out["ApronHem"] = hem
    # 围裙小鲸鱼刺绣：身体 + 竖立尾鳍 + 喷水 + 眼睛点
    wy = -0.366
    fish = [sphere("ApronWhale_Body", (0, wy, 1.046), (0.056, 0.016, 0.034),
                   M["BOW_DARK"], segs=20, rings=12)]
    fish.append(ribbon("ApronWhale_Fin",
                       [(0.046, wy, 1.046), (0.062, wy, 1.070), (0.073, wy, 1.090)],
                       [0.030, 0.022, 0.005], M["BOW_DARK"],
                       normal=(0, -1, 0), thick=0.010))
    fish.append(sphere("ApronWhale_Spout", (-0.046, wy + 0.002, 1.072),
                       (0.014, 0.011, 0.015), M["BOW_DARK"], segs=10, rings=7))
    for sx in (-1, 1):
        fish.append(sphere(f"ApronWhale_Eye_{'L' if sx < 0 else 'R'}",
                           (sx * 0.018, wy - 0.013, 1.053),
                           (0.008, 0.006, 0.008), M["WHITE"], segs=8, rings=6))
    out["ApronWhale"] = fish
    return out


def build_legs(M):
    out = {}
    for sx in (-1, 1):
        x = sx * 0.108
        out.setdefault("Legs", []).append(
            tube(f"Leg_{'L' if sx < 0 else 'R'}",
                 [(x, 0.005, 0.860), (x, 0.005, 0.700), (x, 0.005, 0.520),
                  (x, 0.005, 0.340), (x, 0.005, 0.160), (x, 0.005, 0.095)],
                 [0.118, 0.112, 0.100, 0.088, 0.070, 0.064], M["SKIN"], segs=20))
        # 过膝袜
        out.setdefault("Socks", []).append(
            tube(f"Sock_{'L' if sx < 0 else 'R'}",
                 [(x, 0.005, 0.585), (x, 0.005, 0.480), (x, 0.005, 0.340),
                  (x, 0.005, 0.200), (x, 0.005, 0.115)],
                 [0.104, 0.098, 0.088, 0.074, 0.068], M["SOCK"], segs=20))
        # 玛丽珍鞋
        out.setdefault("Shoes", []).append(
            sphere(f"Shoe_{'L' if sx < 0 else 'R'}", (x, -0.038, 0.052),
                   (0.092, 0.148, 0.052), M["SHOE"], segs=24, rings=14))
        out.setdefault("Shoes", []).append(
            sphere(f"ShoeStrap_{'L' if sx < 0 else 'R'}", (x, -0.055, 0.098),
                   (0.086, 0.120, 0.018), M["SHOE"], segs=20, rings=10))
    return out


def build_tail(M):
    out = []
    path = [(0.10, 0.235, 1.020), (0.26, 0.290, 0.955), (0.44, 0.305, 0.865),
            (0.60, 0.295, 0.775), (0.70, 0.275, 0.720)]
    radii = [0.135, 0.122, 0.104, 0.080, 0.055]
    out.append(tube("WhaleTail", path, radii, M["TAIL"], segs=20))
    # 分岔尾鳍（上下两瓣）
    out.append(fin_blade("TailFlukeUpper", (0.70, 0.275, 0.720), (0.90, 0.250, 0.845),
                         0.115, 0.040, M["TAIL"]))
    out.append(fin_blade("TailFlukeLower", (0.70, 0.275, 0.720), (0.86, 0.290, 0.600),
                         0.105, 0.038, M["TAIL"]))
    return out


# ── 总装 ────────────────────────────────────────────────────────────────

def build_all(M):
    groups = {}
    groups.update(build_legs(M))
    groups.update(build_body(M))
    groups.update(build_skirt(M))
    groups.update(build_apron(M))
    groups["Arms"] = build_arms(M)
    groups.update(build_head(M))
    groups.update(build_hair(M))
    groups["FinEars"] = build_fin_ears(M)
    groups["Headband"] = build_headband(M)
    groups["Tail"] = build_tail(M)
    return groups


def collect(groups):
    """把所有部件按名字收集成扁平列表。"""
    flat = []
    for k, v in groups.items():
        if isinstance(v, list):
            flat.extend([x for x in v if x])
        elif v:
            flat.append(v)
    return flat


def group_into_objects(groups):
    """按逻辑组合并成独立物体（便于检查与导出）。"""
    names = {
        "Legs": "WhaleChan_Legs", "Socks": "WhaleChan_Socks", "Shoes": "WhaleChan_Shoes",
        "Torso": "WhaleChan_Torso", "Neck": "WhaleChan_Neck",
        "Bustier": "WhaleChan_Bustier", "BustierFrill": "WhaleChan_BustierFrill",
        "Corset": "WhaleChan_Corset", "Buttons": "WhaleChan_Buttons",
        "CollarBow": "WhaleChan_CollarBow", "Arms": "WhaleChan_Arms",
        "Head": "WhaleChan_Head", "Eyes": "WhaleChan_Eyes", "Mouth": "WhaleChan_Mouth",
        "HairCap": "WhaleChan_HairCap", "Bangs": "WhaleChan_Bangs",
        "HairSides": "WhaleChan_HairSides", "Ahoge": "WhaleChan_Ahoge",
        "FinEars": "WhaleChan_FinEars", "Headband": "WhaleChan_Headband",
        "Skirt": "WhaleChan_Skirt", "SkirtTrim": "WhaleChan_SkirtTrim",
        "GoldBand": "WhaleChan_GoldBand", "SkirtBows": "WhaleChan_SkirtBows",
        "Apron": "WhaleChan_Apron", "ApronHem": "WhaleChan_ApronHem",
        "ApronWhale": "WhaleChan_ApronWhale", "Tail": "WhaleChan_Tail",
    }
    out = []
    for key, objname in names.items():
        v = groups.get(key)
        if v is None:
            continue
        lst = v if isinstance(v, list) else [v]
        lst = [x for x in lst if x]
        if not lst:
            continue
        if len(lst) == 1:
            lst[0].name = objname
            out.append(lst[0])
        else:
            joined = join_parts(lst, objname)
            if joined:
                out.append(joined)
    return out
