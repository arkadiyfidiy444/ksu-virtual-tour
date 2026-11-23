// Керування від першої особи: WASD, миша (Pointer Lock), Shift — біг, Space — стрибок,
// колізії з сіткою (ковзання вздовж стін), сходи/бордюри, гравітація.
import * as THREE from 'three';

export const PLAYER_DEFAULTS = {
  eyeHeight: 1.65,     // висота очей над землею, м
  bodyHeight: 1.75,    // висота тіла (для перевірки стель/навісів)
  radius: 0.32,        // радіус «капсули» гравця
  stepHeight: 0.5,     // максимальний уступ, на який можна зійти (сходинки, бордюри)
  walkSpeed: 2.6,      // м/с
  runSpeed: 5.6,
  accel: 22,           // розгін на землі, м/с²
  airAccel: 4,
  jumpSpeed: 3.7,      // → висота стрибка ≈ 0.7 м
  gravity: 9.8,
  sensitivity: 0.0022, // рад/піксель
  bob: 0.02,           // амплітуда похитування камери при ході, м (0 — вимкнути)
  fov: 70,
};

export class Player {
  constructor(camera, grid, canvas, cfg = {}) {
    this.camera = camera; this.grid = grid; this.canvas = canvas;
    this.cfg = { ...PLAYER_DEFAULTS, ...cfg };
    this.pos = new THREE.Vector3();          // ноги
    this.vx = 0; this.vz = 0; this.vy = 0;
    this.yaw = 0; this.pitch = 0;
    this.grounded = true; this.viewY = 0; this.bobT = 0;
    this.keys = new Set(); this.locked = false; this.drag = false;
    this.enabled = false;
    this.inputEnabled = true;                // клавіатура реагує лише коли сцена «в фокусі» (див. tour.js)
    this.touch = { x: 0, z: 0, jump: false, run: false };   // віртуальний джойстик (телефони/планшети)
    this.stats = { collisionUs: 0, steps: 0, hits: 0 };
    this._bind();
  }

  // ---------- ввід ----------
  _bind() {
    const down = (e) => {
      if (!this.enabled || !this.inputEnabled) return;
      if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) e.preventDefault();
      this.keys.add(e.code);
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', (e) => this.keys.delete(e.code));
    window.addEventListener('blur', () => this.keys.clear());
    document.addEventListener('pointerlockchange', () => {
      this.locked = document.pointerLockElement === this.canvas; this.onLockChange && this.onLockChange(this.locked);
    });
    this.canvas.addEventListener('pointerdown', (e) => {
      if (!this.enabled || e.pointerType === 'touch') return;
      if (!this.locked && this.canvas.requestPointerLock) {
        try { const p = this.canvas.requestPointerLock(); if (p && p.catch) p.catch(() => {}); } catch (_) {}
      }
      this.drag = true; try { this.canvas.setPointerCapture(e.pointerId); } catch (_) {}
    });
    this.canvas.addEventListener('pointerup', (e) => { this.drag = false; try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) {} });
    let lx = null, ly = null;
    window.addEventListener('mousemove', (e) => {
      const px = lx, py = ly; lx = e.clientX; ly = e.clientY;
      if (!this.enabled || !(this.locked || this.drag)) return;
      // з Pointer Lock — movementX/Y; без нього (перетягування) — різниця координат, якщо movement недоступний
      let dx = e.movementX, dy = e.movementY;
      if (!this.locked && !dx && !dy && px !== null) { dx = e.clientX - px; dy = e.clientY - py; }
      // Chrome іноді видає «стрибок» movementX після повернення курсору — відсікаємо
      if (Math.abs(dx) > 300) dx = 0; if (Math.abs(dy) > 300) dy = 0;
      this.look(dx, dy);
    });
  }

  look(dx, dy) {
    this.yaw -= dx * this.cfg.sensitivity;                                    // 360° без обмежень
    this.pitch = Math.max(-1.5, Math.min(1.5, this.pitch - dy * this.cfg.sensitivity));
  }

  // ---------- вмикання / вимикання ----------
  enable(x, z, yaw, pitch) {
    this.enabled = true; this.keys.clear();
    this.teleport(x, z, yaw, pitch);
    this.camera.fov = this.cfg.fov; this.camera.updateProjectionMatrix();
  }
  disable() {
    this.enabled = false; this.keys.clear(); this.drag = false;
    if (document.pointerLockElement === this.canvas) document.exitPointerLock();
  }

  /** телепорт на (x,z) з виштовхуванням із перешкод */
  teleport(x, z, yaw = this.yaw, pitch = this.pitch) {
    const g = this.grid;
    x = Math.min(Math.max(x, g.x0 + 1), g.x1 - 1); z = Math.min(Math.max(z, g.z0 + 1), g.z1 - 1);
    this.pos.set(x, g.groundAt(x, z), z);
    this._unstick();
    this.pos.y = g.groundAt(this.pos.x, this.pos.z);
    this.vx = this.vz = this.vy = 0; this.grounded = true; this.viewY = this.pos.y;
    this.yaw = yaw; this.pitch = pitch; this._applyCamera(0, 0);
  }

  /** якщо точка всередині перешкоди — шукаємо найближче вільне місце (спіраль) */
  _unstick() {
    const c = this.cfg, g = this.grid;
    if (!this._overlaps(this.pos.x, this.pos.z, this.pos.y)) return true;
    for (let r = 0.1; r < 25; r += 0.1) {
      const n = Math.max(8, Math.round(r * 20));
      for (let k = 0; k < n; k++) {
        const a = (k / n) * Math.PI * 2, x = this.pos.x + Math.cos(a) * r, z = this.pos.z + Math.sin(a) * r;
        if (!this._overlaps(x, z, g.groundAt(x, z))) { this.pos.x = x; this.pos.z = z; return true; }
      }
    }
    return false;
  }

  _overlaps(x, z, y) {
    const c = this.cfg, g = this.grid, r = c.radius, cs = g.cs;
    const i0 = Math.floor((x - r - g.x0) / cs), i1 = Math.floor((x + r - g.x0) / cs);
    const j0 = Math.floor((z - r - g.z0) / cs), j1 = Math.floor((z + r - g.z0) / cs);
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
      if (!g.blocked(i, j, y, c.bodyHeight, c.stepHeight)) continue;
      const cx = Math.min(Math.max(x, g.x0 + i * cs), g.x0 + (i + 1) * cs), cz = Math.min(Math.max(z, g.z0 + j * cs), g.z0 + (j + 1) * cs);
      if ((x - cx) ** 2 + (z - cz) ** 2 < (r - 0.003) ** 2) return true;   // допуск на похибку округлення
    }
    return false;
  }

  /** виштовхування кола з заблокованих клітинок; повертає кількість контактів */
  _resolve() {
    const c = this.cfg, g = this.grid, r = c.radius, cs = g.cs, y = this.pos.y;
    let hits = 0;
    for (let it = 0; it < 4; it++) {
      let moved = false, x = this.pos.x, z = this.pos.z;
      const i0 = Math.floor((x - r - g.x0) / cs), i1 = Math.floor((x + r - g.x0) / cs);
      const j0 = Math.floor((z - r - g.z0) / cs), j1 = Math.floor((z + r - g.z0) / cs);
      for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
        if (!g.blocked(i, j, y, c.bodyHeight, c.stepHeight)) continue;
        const minx = g.x0 + i * cs, maxx = minx + cs, minz = g.z0 + j * cs, maxz = minz + cs;
        const cx = Math.min(Math.max(x, minx), maxx), cz = Math.min(Math.max(z, minz), maxz);
        let dx = x - cx, dz = z - cz; const d2 = dx * dx + dz * dz;
        if (d2 >= r * r) continue;
        if (d2 > 1e-10) { const d = Math.sqrt(d2), k = (r + 0.001 - d) / d; x += dx * k; z += dz * k; }
        else { // центр усередині клітинки — виштовхуємо через найближчу грань
          const l = x - minx, rr = maxx - x, t = z - minz, b = maxz - z, m = Math.min(l, rr, t, b);
          const e = r + 0.001;
          if (m === l) x = minx - e; else if (m === rr) x = maxx + e; else if (m === t) z = minz - e; else z = maxz + e;
        }
        moved = true; hits++;
      }
      this.pos.x = x; this.pos.z = z;
      if (!moved) break;
    }
    return hits;
  }

  // ---------- оновлення ----------
  update(dt) {
    if (!this.enabled || !(dt > 0)) return;      // dt ≤ 0 або NaN — пропускаємо (захист від ділення на нуль)
    const c = this.cfg, g = this.grid, k = this.keys;
    const t0 = performance.now();
    // бажаний напрямок (площина XZ), yaw=0 дивиться в −Z
    let fx = 0, fz = 0;
    if (k.has('KeyW') || k.has('ArrowUp')) fz += 1;
    if (k.has('KeyS') || k.has('ArrowDown')) fz -= 1;
    if (k.has('KeyD') || k.has('ArrowRight')) fx += 1;
    if (k.has('KeyA') || k.has('ArrowLeft')) fx -= 1;
    fx += this.touch.x; fz += this.touch.z;
    const len = Math.hypot(fx, fz); if (len > 1) { fx /= len; fz /= len; }
    const sin = Math.sin(this.yaw), cos = Math.cos(this.yaw);
    const wx = -sin * fz + cos * fx, wz = -cos * fz - sin * fx;               // світові координати
    const run = k.has('ShiftLeft') || k.has('ShiftRight') || this.touch.run;
    const sp = (run ? c.runSpeed : c.walkSpeed) * Math.min(1, len);
    const a = (this.grounded ? c.accel : c.airAccel) * dt;
    const tx = wx * sp, tz = wz * sp;
    const ddx = tx - this.vx, ddz = tz - this.vz, dl = Math.hypot(ddx, ddz);
    if (dl <= a || dl < 1e-9) { this.vx = tx; this.vz = tz; } else { this.vx += ddx / dl * a; this.vz += ddz / dl * a; }

    // стрибок
    if (this.grounded && (k.has('Space') || this.touch.jump)) { this.vy = c.jumpSpeed; this.grounded = false; }

    // рух підкроками (< 0.1 м), щоб не «пролітати» крізь тонкі стіни
    const dist = Math.hypot(this.vx, this.vz) * dt;
    const n = Math.max(1, Math.ceil(dist / 0.1)), sdt = dt / n; let hits = 0;
    for (let s = 0; s < n; s++) {
      const px = this.pos.x, pz = this.pos.z;
      this.pos.x += this.vx * sdt; this.pos.z += this.vz * sdt;
      hits += this._resolve();
      // швидкість по нормалі до стіни гасимо: рухаємось тільки на реально пройдену відстань
      if (sdt > 0) { const rvx = (this.pos.x - px) / sdt, rvz = (this.pos.z - pz) / sdt; if (hits) { this.vx = rvx; this.vz = rvz; } }
      this._vertical(sdt);
      hits += this._resolve();            // після зміни висоти (приземлення) перешкоди можуть стати «вищими» за ноги
      if (this._overlaps(this.pos.x, this.pos.z, this.pos.y)) {   // вузька щілина/гострий кут: виштовхнути нікуди — лишаємось на місці
        this.pos.x = px; this.pos.z = pz; this.vx = this.vz = 0; this._vertical(0); hits++;
      }
    }
    this.stats.steps = n; this.stats.hits = hits;
    // страховка від застрягання (напр., рухома нова колізія)
    if (this._overlaps(this.pos.x, this.pos.z, this.pos.y)) {
      this.stats.unstick = (this.stats.unstick || 0) + 1;
      (this.stats.log ||= []).length < 20 && this.stats.log.push([+this.pos.x.toFixed(2), +this.pos.z.toFixed(2), +this.pos.y.toFixed(2), +this.vx.toFixed(1), +this.vz.toFixed(1)]);
      this._unstick(); this.pos.y = g.groundAt(this.pos.x, this.pos.z); this.vx = this.vz = 0;
    }
    this._applyCamera(dt, Math.hypot(this.vx, this.vz));
    this.stats.collisionUs = (performance.now() - t0) * 1000;
  }

  _vertical(dt) {
    const c = this.cfg, g = this.grid, ground = g.groundAt(this.pos.x, this.pos.z);
    if (this.grounded) {
      if (ground >= this.pos.y - 1e-3) this.pos.y = ground;               // зійшли на сходинку / бордюр
      else if (this.pos.y - ground <= 0.4) this.pos.y = ground;           // зійшли вниз зі сходинки
      else { this.grounded = false; this.vy = 0; }                        // обрив — падаємо
    }
    if (!this.grounded) {
      this.vy -= c.gravity * dt; this.pos.y += this.vy * dt;
      if (this.pos.y <= ground && this.vy <= 0) { this.pos.y = ground; this.vy = 0; this.grounded = true; }
    }
  }

  _applyCamera(dt, speed) {
    const c = this.cfg;
    // плавне вирівнювання по вертикалі (сходи, бордюри, приземлення)
    this.viewY += (this.pos.y - this.viewY) * (dt > 0 ? 1 - Math.exp(-16 * dt) : 1);
    let bob = 0;
    if (c.bob && this.grounded && speed > 0.3) { this.bobT += dt * (6 + speed * 0.9); bob = Math.sin(this.bobT) * c.bob * Math.min(1, speed / c.walkSpeed); }
    else this.bobT = 0;
    this.camera.position.set(this.pos.x, this.viewY + c.eyeHeight + bob, this.pos.z);
    this.camera.rotation.set(this.pitch, this.yaw, 0, 'YXZ');
  }
}
