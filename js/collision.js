// Сітка колізій, згенерована з GLB (tools/build_collision.py). Модель Blender/GLB не змінюється.
// Формат: заголовок 28 байт (KSUC, версія, розмір клітинки, x0, z0, ширина, висота) + 3 площини uint8:
//   gh   — висота поверхні для ходьби, см (0..255)
//   zmin — низ перешкоди, кроки по 0.05 м (255 = перешкоди немає)
//   zmax — верх перешкоди, кроки по 0.05 м
export class CollisionGrid {
  static async load(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Колізії: ${url} → HTTP ${res.status}`);
    let buf = await res.arrayBuffer();
    // gzip розпізнаємо за сигнатурою (деякі сервери самі розпаковують .gz і додають Content-Encoding)
    const u = new Uint8Array(buf, 0, 2);
    if (u[0] === 0x1f && u[1] === 0x8b) {
      if (typeof DecompressionStream === 'undefined') throw new Error('Колізії: браузер не підтримує DecompressionStream — оновіть браузер');
      buf = await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    }
    return new CollisionGrid(buf);
  }

  constructor(buf) {
    const dv = new DataView(buf);
    const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
    if (magic !== 'KSUC') throw new Error('Колізії: невірний формат файлу');
    this.cs = dv.getFloat32(8, true); this.x0 = dv.getFloat32(12, true); this.z0 = dv.getFloat32(16, true);
    this.w = dv.getUint32(20, true); this.h = dv.getUint32(24, true);
    const n = this.w * this.h;
    this.gh = new Uint8Array(buf, 28, n);
    this.zmin = new Uint8Array(buf, 28 + n, n);
    this.zmax = new Uint8Array(buf, 28 + 2 * n, n);
    this.x1 = this.x0 + this.w * this.cs; this.z1 = this.z0 + this.h * this.cs;
  }

  /** чи непрохідна клітинка для ніг на висоті feetY (тіло висотою height, крок угору до step) */
  blocked(ix, iz, feetY, height, step) {
    if (ix < 0 || iz < 0 || ix >= this.w || iz >= this.h) return true;
    const i = iz * this.w + ix;
    if (this.gh[i] * 0.01 > feetY + step) return true;                    // занадто високий уступ
    const zn = this.zmin[i];
    if (zn === 255) return false;
    return zn * 0.05 < feetY + height && this.zmax[i] * 0.05 > feetY + step;
  }

  /** висота поверхні під точкою (максимум по 4 клітинках навколо, щоб сходи не «мерехтіли») */
  groundAt(x, z, rr = 0.1) {
    let m = 0;
    for (let dz = -rr; dz <= rr; dz += 2 * rr) for (let dx = -rr; dx <= rr; dx += 2 * rr) {
      const ix = Math.floor((x + dx - this.x0) / this.cs), iz = Math.floor((z + dz - this.z0) / this.cs);
      if (ix < 0 || iz < 0 || ix >= this.w || iz >= this.h) continue;
      const g = this.gh[iz * this.w + ix]; if (g > m) m = g;
    }
    return m * 0.01;
  }
}
