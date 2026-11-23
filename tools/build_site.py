#!/usr/bin/env python3
"""Збирає папку для публікації (GitHub Pages) і перевіряє всі шляхи.

Запуск:  python tools/build_site.py [вихідна_папка]      (за замовчуванням _site)
У вихідну папку потрапляє лише те, що потрібне сайту (без tests/, tools/, docs/, резервних копій та зайвих GLB).
Скрипт завершується з помилкою, якщо якийсь шлях у index.html / CSS / JS веде в нікуди.
"""
import os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, '_site'))

# що публікуємо (все інше — ні)
INCLUDE = [
    'index.html',
    'css', 'js', 'assets', 'vendor',
    'data/collision.bin.gz',
    'models/KSU_campus_clean.glb',
]
LIMIT = 95 * 1024 * 1024   # ліміт GitHub — 100 МБ на файл


def fail(msg):
    print('ПОМИЛКА:', msg); sys.exit(1)


if os.path.commonpath([ROOT, OUT]) == OUT:
    fail('вихідна папка не може збігатися з папкою проєкту або містити її')
if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

for item in INCLUDE:
    src = os.path.join(ROOT, item)
    if not os.path.exists(src):
        fail(f'не знайдено {item}')
    dst = os.path.join(OUT, item)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.map', '.DS_Store', 'Thumbs.db'))
    else:
        shutil.copy2(src, dst)

open(os.path.join(OUT, '.nojekyll'), 'w').close()   # вимикає Jekyll: файли віддаються «як є»

# ---------- перевірка шляхів ----------
problems = []
def exists_rel(base_file, ref):
    ref = ref.split('#')[0].split('?')[0]
    if not ref or re.match(r'^(https?:|data:|mailto:|tel:|javascript:)', ref):
        return True
    if ref.startswith('/'):
        problems.append(f'{os.path.relpath(base_file, OUT)}: абсолютний шлях «{ref}» зламається в підкаталозі GitHub Pages'); return False
    target = os.path.normpath(os.path.join(os.path.dirname(base_file), ref))
    if not os.path.exists(target):
        problems.append(f'{os.path.relpath(base_file, OUT)}: немає файлу «{ref}»'); return False
    # Linux-сервер чутливий до регістру: перевіряємо точне збігання імен
    rel = os.path.relpath(target, OUT).split(os.sep); cur = OUT
    for part in rel:
        if part not in os.listdir(cur):
            problems.append(f'{os.path.relpath(base_file, OUT)}: невідповідність регістру в «{ref}»'); return False
        cur = os.path.join(cur, part)
    return True

def read(p): return open(p, encoding='utf-8').read()

html = os.path.join(OUT, 'index.html'); h = read(html)
for m in re.finditer(r'\b(src|href|poster|srcset)\s*=\s*"([^"]+)"', h):
    refs = m.group(2).split(',') if m.group(1) == 'srcset' else [m.group(2)]
    for ref in refs:
        exists_rel(html, ref.strip().split(' ')[0])
for m in re.finditer(r'"(\./[^"]+)"', h[h.find('importmap'):h.find('</script>', h.find('importmap'))]):
    exists_rel(html, m.group(1))
for dp, _, fs in os.walk(os.path.join(OUT, 'css')):
    for f in fs:
        p = os.path.join(dp, f)
        for m in re.finditer(r'url\(\s*[\'"]?([^\'")]+)', read(p)): exists_rel(p, m.group(1))
# URL-и в config.js (рядки *Url) та статичні імпорти й динамічні import() у js/
cfg = read(os.path.join(OUT, 'js', 'config.js'))
for m in re.finditer(r"\b\w*Url:\s*'([^']+)'", cfg): exists_rel(html, m.group(1))     # відносно index.html
for dp, _, fs in os.walk(os.path.join(OUT, 'js')):
    for f in fs:
        p = os.path.join(dp, f); t = read(p)
        for m in re.finditer(r"(?:from\s+|import\(\s*)'(\.{1,2}/[^']+)'", t): exists_rel(p, m.group(1))
        for m in re.finditer(r"(?:fetch|load)\(\s*'(/[^']*)'", t): exists_rel(p, m.group(1))

# розміри
total = 0; big = []
for dp, _, fs in os.walk(OUT):
    for f in fs:
        sz = os.path.getsize(os.path.join(dp, f)); total += sz
        if sz > LIMIT: big.append(f)
if big: problems.append('файли більші за 95 МБ: ' + ', '.join(big))

if problems:
    print('Знайдено проблеми:'); [print(' -', p) for p in problems]; sys.exit(1)
print(f'OK: {OUT}  ({total/1048576:.1f} МБ), усі шляхи відносні й існують.')
