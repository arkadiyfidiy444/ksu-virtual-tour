#!/usr/bin/env python3
"""Генерує data/collision.bin з GLB (модель не змінюється).
Сітка 2D (клітинки CS м): gh = висота поверхні для ходьби, zmin/zmax = діапазон висот перешкоди.
Запуск: python tools/build_collision.py  (потрібні numpy, scipy; Pillow — для debug-картинки)"""
import sys, re, struct, json, gzip, time, os
import numpy as np
from scipy import ndimage
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from glb import GLB

GLB_PATH = os.path.join(ROOT, 'models', 'KSU_campus_clean.glb')
CS = 0.2                                 # розмір клітинки, м
X0, Z0, X1, Z1 = -157.5, -150.0, 240.0, 190.0   # межі ділянки Ground (gltf, Y вгору)
W = int(np.ceil((X1 - X0) / CS)); H = int(np.ceil((Z1 - Z0) / CS))
STEP = 0.09                              # крок вибірки точок на поверхні
HARD_TOP = 1.3                           # «непрохідні» дрібні об'єкти: висота, яку не перестрибнути

def rx(p): return re.compile(p)
# --- правила за назвою вузла ---
SOLID = rx(r'^(AdmissionsBuilding_body|Court_[BCD]_body|DormA_body|Main_body|Main_tower|South_dorm_[AB]|South_univer_body|South_univer_tower|SignBuilding_body|Annex|BG_building(\.\d+)?|Sport_hall|Courtyard_shed|Athena_(base|pedestal|statue)|EndStatue|PK_fountain(_water|_edge)?|.*_cars_car_.*|Sport_cars|South_stop_frame)$')
HARD  = rx(r'^(FL_bench|PK_bench|PK_X_bench|FL_urn|PK_urn|PK_X_urn|FL_Bed_.*|PK_.*Bed.*|PK_X_.*Bed|FL_bed_curb|FL_bed_soil|South_(garden|yard)_bed.*|South_stop_bench|Hedge_main)(\.\d+)?$')
THIN  = rx(r'^(Fence_left|Fence_stone|South_fence_bars|South_fence_posts|Gate_leaves|Gate_pillars|Gate_plate.*|Courtyard_gate_pillars|Courtyard_barrier_.*|South_yard_wall|Sport_court|AdmissionsBuilding_columns|SignBuilding_columns|BD_rails|BG_pilasters|Annex_plinth|FL_lamp|PK_lamp|PK_X_lamp|PK_street_lamp|Sport_lamp|FL_traffic_light|Flag_canopy_UA|Courtyard_shed_door)(\.\d+)?$')
TREE  = rx(r'^(TR_|MRG_Trees)')
WALK  = rx(r'^(Road_|Ring_|Entrance_square|Fountain_plaza|Plaza_|Courtyard_(drive|parking_|walk_)|PK_X_path|PK_X_endplaza|PK_pathcurb|Path_Park|Sport_(path|lot|walk)|South_(garden_paving|stop_paving|univer_plaza|yard_path|zebra)|Walk_door|FL_circle_path|FL_path|Stairs|.*_steps|.*_walk|Sport_court|Ground_ext)')
BARK = {'Bark', 'BirchBark'}
base = lambda n: re.sub(r'\.\d+$', '', n)

g = GLB(GLB_PATH)
nodes = [n for n in g.g['nodes'] if 'mesh' in n]

def cells(p):
    return np.floor((p[:, 0] - X0) / CS).astype(np.int64), np.floor((p[:, 2] - Z0) / CS).astype(np.int64)

_lat = {}
def lattice(n):
    if n not in _lat:
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing='ij'); m = (i + j) <= n
        _lat[n] = (i[m] / n, j[m] / n)
    return _lat[n]

def sample_points(w, idx):
    """точки на поверхні трикутників (щільність STEP)"""
    A, B, C = w[idx[:, 0]], w[idx[:, 1]], w[idx[:, 2]]
    e = np.maximum.reduce([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)])
    out = [A, B, C, (A + B + C) / 3]
    big = e > STEP * 1.5
    for k in np.nonzero(big)[0]:
        n = int(np.ceil(e[k] / STEP)); u, v = lattice(n)
        out.append(A[k] + np.outer(u, B[k] - A[k]) + np.outer(v, C[k] - A[k]))
    return np.vstack(out)

class Win:
    """локальне вікно сітки для одного вузла"""
    def __init__(self, bb):  # bb = (xmin,xmax,zmin,zmax)
        self.ix0 = max(int((bb[0] - X0) / CS) - 2, 0); self.iz0 = max(int((bb[2] - Z0) / CS) - 2, 0)
        ix1 = min(int((bb[1] - X0) / CS) + 3, W); iz1 = min(int((bb[3] - Z0) / CS) + 3, H)
        self.w, self.h = ix1 - self.ix0, iz1 - self.iz0
        self.zmin = np.full((self.h, self.w), np.inf, np.float32); self.zmax = np.full((self.h, self.w), -np.inf, np.float32)
    def add(self, p):
        ix, iz = cells(p); ix -= self.ix0; iz -= self.iz0
        ok = (ix >= 0) & (ix < self.w) & (iz >= 0) & (iz < self.h)
        ix, iz, y = ix[ok], iz[ok], p[ok, 1].astype(np.float32)
        np.minimum.at(self.zmin, (iz, ix), y); np.maximum.at(self.zmax, (iz, ix), y)
    def mask(self): return np.isfinite(self.zmax)

Zmin = np.full((H, W), np.inf, np.float32); Zmax = np.full((H, W), -np.inf, np.float32)
GH = np.zeros((H, W), np.float32)
KIND = np.zeros((H, W), np.uint8)   # debug: 1 solid,2 hard,3 thin,4 tree

def paste(win, zmin, zmax, m, kind):
    sl = (slice(win.iz0, win.iz0 + win.h), slice(win.ix0, win.ix0 + win.w))
    Zmin[sl] = np.where(m, np.minimum(Zmin[sl], zmin), Zmin[sl]); Zmax[sl] = np.where(m, np.maximum(Zmax[sl], zmax), Zmax[sl])
    KIND[sl] = np.where(m, kind, KIND[sl])

def node_points(n, ymax=None, mats=None):
    pts = []
    for mat, w, idx in g.prims(n):
        if mats is not None and mat not in mats: continue
        p = sample_points(w, idx)
        if ymax is not None: p = p[p[:, 1] < ymax]
        pts.append(p)
    return np.vstack(pts) if pts else None

t0 = time.time(); cnt = dict(solid=0, hard=0, thin=0, tree=0, walk=0)
for n in nodes:
    nm = n['name']; b = base(nm)
    if SOLID.match(nm) or HARD.match(nm) or THIN.match(nm):
        p = node_points(n)
        if p is None or not len(p): continue
        win = Win((p[:, 0].min(), p[:, 0].max(), p[:, 2].min(), p[:, 2].max())); win.add(p)
        m = win.mask(); zmin, zmax = win.zmin, win.zmax
        if SOLID.match(nm):
            m2 = ndimage.binary_fill_holes(m); zmax = np.where(m2 & ~m, zmax[m].max(), zmax); zmin = np.where(m2, 0, zmin); m = m2
            paste(win, zmin, zmax, m, 1); cnt['solid'] += 1
        elif HARD.match(nm):
            m2 = ndimage.binary_fill_holes(m); zmax = np.where(m2 & ~m, zmax[m].max(), zmax)
            zmax = np.maximum(zmax, HARD_TOP); zmin = np.zeros_like(zmin); paste(win, zmin, zmax, m2, 2); cnt['hard'] += 1
        else:
            paste(win, zmin, zmax, m, 3); cnt['thin'] += 1
    elif TREE.match(nm):
        p = node_points(n, ymax=2.2, mats=BARK)
        if p is None or not len(p): continue
        win = Win((p[:, 0].min(), p[:, 0].max(), p[:, 2].min(), p[:, 2].max())); win.add(p)
        m = ndimage.binary_fill_holes(win.mask())
        paste(win, np.zeros_like(win.zmin), np.full_like(win.zmax, 5.0), m, 4); cnt['tree'] += 1
    if re.match(r'^TR_(spr|thuja)', nm):
        # ялини/туї: крона йде до землі — блокуємо ядро крони (65% радіуса) на висоті 0.3–1.8 м
        pts = []
        for mat, w, idx in g.prims(n):
            if not mat.startswith(('F_spruce', 'F_thuja')): continue
            p = sample_points(w, idx); pts.append(p[(p[:, 1] > 0.3) & (p[:, 1] < 1.8)])
        pts = [p for p in pts if len(p)]
        if not pts: continue
        p = np.vstack(pts)
        win = Win((p[:, 0].min(), p[:, 0].max(), p[:, 2].min(), p[:, 2].max())); win.add(p)
        m = ndimage.binary_fill_holes(win.mask()); r = np.sqrt(m.sum() / np.pi)  # радіус у клітинках
        it = int(r * 0.35)
        if it > 0: m = ndimage.binary_erosion(m, iterations=it)
        if m.any(): paste(win, np.zeros_like(win.zmin), np.full_like(win.zmax, 5.0), m, 4); cnt['tree'] += 1
print('blockers', cnt, round(time.time() - t0, 1), 's')

# --- поверхні для ходьби: висота за центрами клітинок ---
t0 = time.time()
for n in nodes:
    nm = n['name']
    if not WALK.match(nm) or nm.startswith('Ground'): continue
    for mat, w, idx in g.prims(n):
        A, B, C = w[idx[:, 0]], w[idx[:, 1]], w[idx[:, 2]]
        nrm = np.cross(B - A, C - A); ln = np.linalg.norm(nrm, axis=1); up = nrm[:, 1] / np.maximum(ln, 1e-12)
        for k in np.nonzero(np.abs(up) > 0.3)[0]:
            a, b_, c = A[k], B[k], C[k]
            x_lo, x_hi = min(a[0], b_[0], c[0]), max(a[0], b_[0], c[0]); z_lo, z_hi = min(a[2], b_[2], c[2]), max(a[2], b_[2], c[2])
            i0 = max(int((x_lo - X0) / CS), 0); i1 = min(int((x_hi - X0) / CS) + 1, W - 1); j0 = max(int((z_lo - Z0) / CS), 0); j1 = min(int((z_hi - Z0) / CS) + 1, H - 1)
            if i1 < i0 or j1 < j0: continue
            xs = X0 + (np.arange(i0, i1 + 1) + 0.5) * CS; zs = Z0 + (np.arange(j0, j1 + 1) + 0.5) * CS
            X, Z = np.meshgrid(xs, zs)
            d = (b_[2] - c[2]) * (a[0] - c[0]) + (c[0] - b_[0]) * (a[2] - c[2])
            if abs(d) < 1e-12: continue
            l1 = ((b_[2] - c[2]) * (X - c[0]) + (c[0] - b_[0]) * (Z - c[2])) / d
            l2 = ((c[2] - a[2]) * (X - c[0]) + (a[0] - c[0]) * (Z - c[2])) / d
            l3 = 1 - l1 - l2; eps = -0.02
            ins = (l1 >= eps) & (l2 >= eps) & (l3 >= eps)
            if not ins.any(): continue
            Y = l1 * a[1] + l2 * b_[1] + l3 * c[1]
            sub = GH[j0:j1 + 1, i0:i1 + 1]; GH[j0:j1 + 1, i0:i1 + 1] = np.where(ins, np.maximum(sub, Y), sub)
    cnt['walk'] += 1
print('walk', cnt['walk'], round(time.time() - t0, 1), 's')

# --- кодування ---
def q(a, none):
    out = np.round(a / 0.05); out[~np.isfinite(a)] = none; return np.clip(out, 0, 254).astype(np.uint8) if none == 255 else np.clip(out, 0, 255).astype(np.uint8)
gh8 = np.clip(np.round(GH * 100), 0, 255).astype(np.uint8)
zmin8 = np.where(np.isfinite(Zmin), np.clip(np.round(np.maximum(Zmin, 0) / 0.05), 0, 254), 255).astype(np.uint8)
zmax8 = np.where(np.isfinite(Zmax), np.clip(np.round(np.maximum(Zmax, 0) / 0.05), 0, 254), 0).astype(np.uint8)
hdr = struct.pack('<4sIfffII', b'KSUC', 1, CS, X0, Z0, W, H)
blob = hdr + gh8.tobytes() + zmin8.tobytes() + zmax8.tobytes()
os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
with gzip.GzipFile(os.path.join(ROOT, 'data', 'collision.bin.gz'), 'wb', 9, mtime=0) as f: f.write(blob)
print('grid', W, H, 'raw MB', round(len(blob) / 1e6, 1), 'gz MB', round(os.path.getsize(os.path.join(ROOT, 'data', 'collision.bin.gz')) / 1e6, 2))

# --- debug-картинка ---
try:
    from PIL import Image
    blocked = (Zmin < 1.7) & (Zmax > 0.5)
    img = np.zeros((H, W, 3), np.uint8); v = (60 + np.clip(GH, 0, 1) * 150).astype(np.uint8); img[..., 0] = img[..., 1] = img[..., 2] = v
    for k, col in {1: (230, 60, 60), 2: (240, 160, 30), 3: (60, 120, 255), 4: (30, 200, 60)}.items():
        mm = blocked & (KIND == k); img[mm] = col
    Image.fromarray(img).save(os.environ.get('KSU_DEBUG_PNG', os.path.join(ROOT, 'docs', 'collision_map.png')))
except Exception as e: print('no png', e)
