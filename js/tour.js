// 3D-прогулянка: рендерер, світло, завантаження GLB та колізій, режими «прогулянка» / «вільний огляд».
// Модуль підвантажується ліниво (з site.js) — модель 40 МБ не вантажиться, поки користувач не почав екскурсію.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { CONFIG } from './config.js';
import { CollisionGrid } from './collision.js';
import { Player } from './player.js';

const $ = (id) => document.getElementById(id);
const stage = $('tour-stage'), canvas = $('view');

const state = { yaw: 0, pitch: 0, speed: 12, keys: new Set(), drag: false, mode: 'walk', active: false, engaged: false, loaded: false, eco: false, dirty: true };
const info = { loadMs: 0, hidden: 0, meshes: 0, materials: new Set(), textures: new Set() };
let renderer, scene, camera, sun, player, gltf, grid, raf = 0, dupGroup = null, loadPromise = null;
const touchState = { x: 0, z: 0 };

// ---------- ініціалізація сцени ----------
function createScene() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  applyPixelRatio();
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = CONFIG.exposure;
  renderer.shadowMap.enabled = false;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(CONFIG.sky);
  scene.fog = new THREE.Fog(CONFIG.fog.color, CONFIG.fog.near, CONFIG.fog.far);
  camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1500);
  camera.rotation.order = 'YXZ';

  scene.add(new THREE.HemisphereLight(CONFIG.hemi.sky, CONFIG.hemi.ground, CONFIG.hemi.intensity));
  sun = new THREE.DirectionalLight(CONFIG.sun.color, CONFIG.sun.intensity);
  const sd = new THREE.Vector3(...CONFIG.sun.dir).normalize(), sc = new THREE.Vector3(...CONFIG.sun.shadowCenter);
  sun.position.copy(sc).addScaledVector(sd, -400); sun.target.position.copy(sc);
  sun.shadow.mapSize.set(CONFIG.sun.shadowMapSize, CONFIG.sun.shadowMapSize);
  const h = CONFIG.sun.shadowHalfSize;
  Object.assign(sun.shadow.camera, { left: -h, right: h, top: h, bottom: -h, near: 10, far: 900 });
  sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.3;
  scene.add(sun, sun.target);
}

// Адаптивна роздільність: якщо кадри повільні — плавно зменшуємо внутрішню роздільність canvas (UI й тексти не страждають)
const SCALES = [1, 0.85, 0.72, 0.62, 0.55];
const gov = { level: 0, best: 0, slow: 0, fast: 0, acc: 0, n: 0, hold: 0, lastUp: 0 };
function currentRatio() {
  const dpr = window.devicePixelRatio || 1;
  return state.eco ? Math.min(dpr, 0.75) : Math.min(dpr, CONFIG.maxPixelRatio) * SCALES[gov.level];
}
function applyPixelRatio() {
  renderer.setPixelRatio(currentRatio());
  resize();
}
function resize() {
  if (!renderer || !camera) return;
  const w = Math.max(1, stage.clientWidth), h = Math.max(1, stage.clientHeight);
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  state.dirty = true; gov.hold = performance.now() + 1500;
}

// ---------- вільна камера ----------
function setView(v) {
  camera.position.set(...v.pos);
  const m = new THREE.Matrix4().lookAt(camera.position, new THREE.Vector3(...v.target), new THREE.Vector3(0, 1, 0));
  const e = new THREE.Euler(0, 0, 0, 'YXZ').setFromRotationMatrix(m);
  state.yaw = e.y; state.pitch = e.x;
}
function updateFree(dt) {
  camera.rotation.set(state.pitch, state.yaw, 0);
  const k = state.keys, f = new THREE.Vector3(), r = new THREE.Vector3(), mv = new THREE.Vector3();
  camera.getWorldDirection(f); r.crossVectors(f, camera.up).normalize();
  if (k.has('KeyW')) mv.add(f); if (k.has('KeyS')) mv.sub(f);
  if (k.has('KeyD')) mv.add(r); if (k.has('KeyA')) mv.sub(r);
  if (k.has('KeyE')) mv.y += 1; if (k.has('KeyQ')) mv.y -= 1;
  mv.addScaledVector(f, touchState.z).addScaledVector(r, touchState.x);
  if (mv.lengthSq()) camera.position.addScaledVector(mv.length() > 1 ? mv.normalize() : mv, state.speed * (k.has('ShiftLeft') || k.has('ShiftRight') || player.touch.run ? 3 : 1) * dt);
}
function lookDelta(dx, dy) {
  if (state.mode === 'walk') player.look(dx, dy);
  else { state.yaw -= dx * 0.0035; state.pitch = Math.max(-1.55, Math.min(1.55, state.pitch - dy * 0.0035)); }
}

// ---------- режими ----------
function lookAtAngles(pos, target) {
  const dx = target[0] - pos[0], dz = target[2] - pos[2], dy = target[1] - pos[1];
  return { yaw: Math.atan2(-dx, -dz), pitch: Math.atan2(dy, Math.hypot(dx, dz)) };
}
export function setMode(mode, opts = {}) {
  if (!state.loaded || (state.mode === mode && !opts.force)) return;
  state.keys.clear(); state.drag = false;
  const e = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ');
  if (mode === 'walk') { state.mode = 'walk'; player.enable(camera.position.x, camera.position.z, e.y, Math.max(-1.2, Math.min(1.2, e.x))); }
  else { state.mode = 'free'; state.yaw = e.y; state.pitch = e.x; player.disable(); camera.fov = 60; camera.updateProjectionMatrix(); }
  syncModeUI();
}
function goWalk(v) {
  const a = lookAtAngles(v.pos, v.target);
  state.mode = 'walk'; state.keys.clear();
  player.enable(v.pos[0], v.pos[2], a.yaw, Math.max(-0.5, Math.min(0.5, a.pitch)));
  syncModeUI();
}
/** перейти до точки: ключ із CONFIG.views або 'spawn' */
export function goTo(key) {
  if (!state.loaded) return;
  const v = key === 'spawn' || !CONFIG.views[key] ? CONFIG.spawn : CONFIG.views[key];
  if (v.pos[1] < 10) goWalk(v); else { setMode('free', { force: true }); setView(v); }
  gov.hold = performance.now() + 1200; state.dirty = true; renderOnce();
}
export const respawn = () => goTo('spawn');

function syncModeUI() {
  const walk = state.mode === 'walk';
  $('mode-walk').classList.toggle('on', walk); $('mode-free').classList.toggle('on', !walk);
  $('crosshair').hidden = !walk;
  $('hint').textContent = walk
    ? 'WASD — ходьба · миша — огляд · Shift — біг · Space — стрибок · F — вільний огляд · R — на початок · Esc — курсор'
    : 'Вільний огляд: тягнути мишею — огляд · WASD — рух · Q/E — вниз/вгору · Shift — швидше · колесо — швидкість · F — прогулянка';
  updateLockHint();
}
function updateLockHint() {
  const coarse = matchMedia('(pointer: coarse)').matches;
  $('lockhint').hidden = !(state.mode === 'walk' && state.loaded && state.engaged && !player.locked && !coarse);
}

// ---------- «фокус» на екскурсії: клавіші працюють лише всередині сцени ----------
export function engage(v = true) {
  state.engaged = v; if (player) { player.inputEnabled = v; if (!v) player.keys.clear(); }
  if (!v) state.keys.clear();
  stage.classList.toggle('engaged', v); if (state.loaded) updateLockHint();
}
function bindInput() {
  stage.addEventListener('pointerdown', () => engage(true));
  document.addEventListener('pointerdown', (e) => { if (state.engaged && !stage.contains(e.target) && !document.fullscreenElement) engage(false); }, true);
  window.addEventListener('keydown', (e) => {
    if (!state.engaged || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === 'KeyF') { setMode(state.mode === 'walk' ? 'free' : 'walk'); e.preventDefault(); return; }
    if (e.code === 'KeyR' && state.mode === 'walk') { respawn(); return; }
    if (state.mode === 'free') { state.keys.add(e.code); if (e.code === 'Space') e.preventDefault(); }
  });
  window.addEventListener('keyup', (e) => state.keys.delete(e.code));
  window.addEventListener('blur', () => state.keys.clear());
  canvas.addEventListener('pointerdown', (e) => { if (state.mode === 'free' && e.pointerType !== 'touch') { state.drag = true; try { canvas.setPointerCapture(e.pointerId); } catch (_) {} } });
  canvas.addEventListener('pointerup', (e) => { if (state.mode !== 'free') return; state.drag = false; try { canvas.releasePointerCapture(e.pointerId); } catch (_) {} });
  canvas.addEventListener('pointermove', (e) => { if (state.mode === 'free' && state.drag && e.pointerType !== 'touch') lookDelta(e.movementX, e.movementY); });
  stage.addEventListener('wheel', (e) => {
    if (state.mode === 'free') { e.preventDefault(); state.speed = Math.max(1, Math.min(120, state.speed * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); }
    else if (player.locked) e.preventDefault();
  }, { passive: false });
  document.addEventListener('fullscreenchange', () => { const fs = document.fullscreenElement === stage; stage.classList.toggle('is-fs', fs); $('fs-btn').textContent = fs ? '✕ Згорнути' : '⛶ Повний екран'; if (fs) engage(true); resize(); });
}

export function toggleFullscreen() {
  if (document.fullscreenElement) { document.exitFullscreen(); return; }
  if (stage.requestFullscreen) { stage.requestFullscreen().catch(() => cssFullscreen()); }
  else cssFullscreen();
}
function cssFullscreen() {   // iOS/Safari без Fullscreen API для елементів
  const on = stage.classList.toggle('is-fs-css'); document.documentElement.classList.toggle('no-scroll', on);
  $('fs-btn').textContent = on ? '✕ Згорнути' : '⛶ Повний екран'; resize();
}

// ---------- дотик: джойстик + огляд перетягуванням ----------
function bindTouch() {
  const joy = $('joy'), knob = $('joy-knob'); let jid = null, cx = 0, cy = 0; const R = 46;
  const setAxes = (x, z) => { player.touch.x = x; player.touch.z = z; touchState.x = x; touchState.z = z; };
  joy.addEventListener('pointerdown', (e) => { jid = e.pointerId; try { joy.setPointerCapture(jid); } catch (_) {} const r = joy.getBoundingClientRect(); cx = r.left + r.width / 2; cy = r.top + r.height / 2; e.preventDefault(); engage(true); });
  joy.addEventListener('pointermove', (e) => {
    if (e.pointerId !== jid) return;
    let dx = e.clientX - cx, dy = e.clientY - cy; const d = Math.hypot(dx, dy); if (d > R) { dx *= R / d; dy *= R / d; }
    knob.style.transform = `translate(${dx}px, ${dy}px)`; setAxes(dx / R, -dy / R);
  });
  const end = (e) => { if (e.pointerId !== jid) return; jid = null; knob.style.transform = ''; setAxes(0, 0); };
  joy.addEventListener('pointerup', end); joy.addEventListener('pointercancel', end);
  const jump = $('btn-jump'), run = $('btn-run');
  jump.addEventListener('pointerdown', (e) => { player.touch.jump = true; e.preventDefault(); });
  const jEnd = () => { player.touch.jump = false; }; jump.addEventListener('pointerup', jEnd); jump.addEventListener('pointercancel', jEnd); jump.addEventListener('pointerleave', jEnd);
  run.addEventListener('click', () => { player.touch.run = !player.touch.run; run.classList.toggle('on', player.touch.run); });
  // огляд: перетягування пальцем по сцені
  let lid = null, lx = 0, ly = 0;
  canvas.addEventListener('pointerdown', (e) => { if (e.pointerType !== 'touch' || lid !== null) return; lid = e.pointerId; lx = e.clientX; ly = e.clientY; try { canvas.setPointerCapture(lid); } catch (_) {} });
  canvas.addEventListener('pointermove', (e) => { if (e.pointerId !== lid) return; lookDelta((e.clientX - lx) * 1.6, (e.clientY - ly) * 1.6); lx = e.clientX; ly = e.clientY; });
  const lEnd = (e) => { if (e.pointerId === lid) lid = null; };
  canvas.addEventListener('pointerup', lEnd); canvas.addEventListener('pointercancel', lEnd);
}

// ---------- завантаження ----------
async function loadModel(onProgress) {
  const t0 = performance.now();
  const hid = CONFIG.hiddenNodesUrl ? await (await fetch(CONFIG.hiddenNodesUrl)).json() : null;
  const hiddenIdx = new Set(hid ? hid.nodes : []), hiddenNames = new Set(hid ? hid.names : []);
  const loader = new GLTFLoader();
  gltf = await new Promise((res, rej) => loader.load(CONFIG.modelUrl, res, (p) => {
    if (p.lengthComputable) onProgress && onProgress(p.loaded / p.total * 0.9, `${(p.loaded / 1048576).toFixed(1)} / ${(p.total / 1048576).toFixed(1)} МБ`);
  }, rej));
  onProgress && onProgress(0.95, 'Обробка сцени…');
  await new Promise((r) => setTimeout(r, 30));
  const root = gltf.scene;
  dupGroup = new THREE.Group(); dupGroup.name = '__duplicates__'; dupGroup.visible = false;
  const toMove = new Set();
  if (hid) gltf.parser.associations.forEach((v, obj) => { if (v && v.nodes !== undefined && hiddenIdx.has(v.nodes) && obj.parent === root) toMove.add(obj); });
  if (hid) root.children.forEach((o) => { if (hiddenNames.has(o.name)) toMove.add(o); });
  [...toMove].forEach((o) => dupGroup.add(o)); info.hidden = toMove.size;
  scene.add(root, dupGroup);
  const maxAn = Math.min(CONFIG.anisotropy, renderer.capabilities.getMaxAnisotropy());
  root.traverse((o) => {
    if (!o.isMesh) return;
    info.meshes++;
    (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
      info.materials.add(m);
      for (const k of ['map', 'normalMap', 'aoMap', 'emissiveMap', 'metalnessMap', 'roughnessMap']) if (m[k]) { m[k].anisotropy = maxAn; info.textures.add(m[k]); }
    });
  });
  scene.updateMatrixWorld(true);                       // сцена статична: матриці рахуємо один раз
  root.traverse((o) => { o.matrixAutoUpdate = false; });
  info.loadMs = performance.now() - t0;
}


/** «прогрів» GPU: компілюємо шейдери, завантажуємо текстури й геометрію у відеопам'ять ЗАЗДАЛЕГІДЬ (поки видно постер),
 *  щоб під час прогулянки не було фризів, коли новий об'єкт уперше потрапляє в кадр */
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));
async function warmUp(onProgress) {
  const t0 = performance.now();
  const rep = (f, t) => onProgress && onProgress(f, t);
  rep(0.955, 'Підготовка графіки: шейдери…');
  try { await renderer.compileAsync(scene, camera); } catch (_) { renderer.compile(scene, camera); }
  const tex = [...info.textures];
  for (let i = 0; i < tex.length; i++) {
    renderer.initTexture(tex[i]);
    if (i % 4 === 3) { rep(0.96 + 0.02 * i / tex.length, `Підготовка графіки: текстури ${i + 1}/${tex.length}`); await nextFrame(); }
  }
  const meshes = []; gltf.scene.traverse((o) => { if (o.isMesh && o.visible) meshes.push(o); });
  const vis = meshes.map((o) => o.visible), cull = meshes.map((o) => o.frustumCulled);
  renderer.setScissorTest(true); renderer.setScissor(0, 0, 1, 1);
  const BATCH = 400;
  for (let b = 0; b < meshes.length; b += BATCH) {
    meshes.forEach((o, i) => { const on = i >= b && i < b + BATCH; o.visible = on; o.frustumCulled = !on; });
    renderer.render(scene, camera);
    rep(0.98 + 0.02 * b / meshes.length, 'Підготовка графіки: геометрія…'); await nextFrame();
  }
  meshes.forEach((o, i) => { o.visible = vis[i]; o.frustumCulled = cull[i]; });
  renderer.setScissorTest(false); state.dirty = true;
  info.warmMs = performance.now() - t0;
}

/** завантажує модель і колізії один раз; повторні виклики повертають той самий проміс */
export function load(onProgress) {
  if (loadPromise) return loadPromise;
  loadPromise = (async () => {
    createScene(); resize();
    setView(CONFIG.views[CONFIG.startView]);
    await Promise.all([loadModel(onProgress), CollisionGrid.load(CONFIG.collisionUrl).then((g) => { grid = g; })]);
    await warmUp(onProgress);
    player = new Player(camera, grid, canvas, CONFIG.player);
    player.onLockChange = updateLockHint;
    bindInput(); bindTouch(); bindUI();
    state.loaded = true; $('ui').hidden = false; stage.classList.add('live');
    new ResizeObserver(resize).observe(stage);
    window.__ksu = { THREE, scene, camera, renderer, gltf, info, setView, state, player, grid, setMode, goWalk, goTo, respawn, gov, currentRatio };   // для налагодження з консолі
    goTo('spawn'); syncModeUI();
    setActive(true);
  })().catch((e) => { loadPromise = null; throw e; });
  return loadPromise;
}

// ---------- UI ----------
function bindUI() {
  document.querySelectorAll('#views button').forEach((b) => b.addEventListener('click', () => { b.blur(); goTo(b.dataset.view); engage(true); }));
  $('mode-walk').addEventListener('click', (e) => { e.currentTarget.blur(); setMode('walk'); });
  $('mode-free').addEventListener('click', (e) => { e.currentTarget.blur(); setMode('free'); });
  $('fs-btn').addEventListener('click', (e) => { e.currentTarget.blur(); toggleFullscreen(); });
  $('t-shadows').addEventListener('change', (e) => {
    renderer.shadowMap.enabled = e.target.checked; sun.castShadow = e.target.checked; state.dirty = true;
    scene.traverse((o) => { if (o.isMesh) { o.castShadow = e.target.checked; o.receiveShadow = e.target.checked; if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.needsUpdate = true; }); } });
  });
  $('t-eco').addEventListener('change', (e) => { state.eco = e.target.checked; applyPixelRatio(); state.dirty = true; });
  $('t-stats').addEventListener('change', (e) => { $('stats').hidden = !e.target.checked; });
  $('lockhint').addEventListener('click', () => { try { canvas.requestPointerLock(); } catch (_) {} });
  matchMedia('(pointer: coarse)').addEventListener?.('change', updateLockHint);
}

// ---------- цикл ----------
let last = 0, fpsAcc = 0, fpsN = 0, fpsRendered = 0, lastRaw = 0;
const lastPose = new Float64Array(7);
function poseChanged() {   // сцена статична: якщо камера не рухалась — кадр не перемальовуємо (економить GPU, коли гравець стоїть)
  const p = camera.position, r = camera.rotation, f = camera.fov;
  if (state.dirty || p.x !== lastPose[0] || p.y !== lastPose[1] || p.z !== lastPose[2] || r.x !== lastPose[3] || r.y !== lastPose[4] || r.z !== lastPose[5] || f !== lastPose[6]) {
    lastPose[0] = p.x; lastPose[1] = p.y; lastPose[2] = p.z; lastPose[3] = r.x; lastPose[4] = r.y; lastPose[5] = r.z; lastPose[6] = f; state.dirty = false; return true;
  }
  return false;
}
/** регулятор якості: стежить за реальним інтервалом між кадрами і підлаштовує роздільність */
function govTick(now, raw) {
  if (state.eco || now < gov.hold || raw > 1500) { gov.acc = 0; gov.n = 0; return; }
  gov.acc += raw; gov.n++;
  if (gov.acc < 1000) return;
  const avg = gov.acc / gov.n; gov.acc = 0; gov.n = 0;
  if (avg > 24) {                                   // < ~42 FPS
    gov.fast = 0;
    if (++gov.slow >= 2 && gov.level < SCALES.length - 1) {
      if (now - gov.lastUp < 20000) gov.best = gov.level + 1;      // щойно піднімали і знову повільно — вище не підніматимемо
      gov.level++; gov.slow = 0; applyPixelRatio(); gov.hold = now + 1200;
    }
  } else if (avg < 19) {                            // тримає ~55+ FPS
    gov.slow = 0;
    if (++gov.fast >= 8 && gov.level > gov.best) { gov.level--; gov.fast = 0; gov.lastUp = now; applyPixelRatio(); gov.hold = now + 1200; }
  } else { gov.slow = 0; gov.fast = 0; }
}
function frame(now) {
  raf = 0; if (!state.active) return;
  const dt = Math.max(0, Math.min(0.1, (now - last) / 1000)); const raw = now - lastRaw; last = now; lastRaw = now;   // rAF-мітка може бути трохи раніше за performance.now()
  if (state.mode === 'walk') player.update(dt); else updateFree(dt);
  fpsAcc += dt;
  if (poseChanged()) {
    renderer.render(scene, camera); fpsN++; govTick(now, raw);
  } else { gov.acc = 0; gov.n = 0; }
  if (fpsAcc >= 0.5) {
    const fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0;
    if (!$('stats').hidden) {
      const r = renderer.info.render, m = renderer.info.memory;
      $('stats').textContent =
        `FPS ${fps > 0 ? fps.toFixed(0) : '— (кадр не змінюється)'}  |  виклики ${r.calls}  |  трикутники ${(r.triangles / 1000).toFixed(0)}k\n` +
        `роздільність ×${currentRatio().toFixed(2)}${state.eco ? ' (економний)' : gov.level ? ' (авто-зниження)' : ''}  |  текстур ${m.textures}\n` +
        `мешів ${info.meshes}  |  матеріалів ${info.materials.size}  |  завантаження ${(info.loadMs / 1000).toFixed(1)} с` +
        (state.mode === 'walk' ? `\nхід: x ${player.pos.x.toFixed(1)}  z ${player.pos.z.toFixed(1)}  h ${player.pos.y.toFixed(2)}  |  колізії ${player.stats.collisionUs.toFixed(0)} мкс` : '');
    }
  }
  raf = requestAnimationFrame(frame);
}
function renderOnce() { if (state.loaded && !state.active) { if (state.mode === 'walk') player._applyCamera(0, 0); else camera.rotation.set(state.pitch, state.yaw, 0); renderer.render(scene, camera); } }

/** рендер лише коли секція видима й вкладка активна — економить ресурси слабких ПК */
export function setActive(v) {
  v = !!v && state.loaded && !document.hidden;
  if (v === state.active) return;
  state.active = v;
  if (v) { last = lastRaw = performance.now(); gov.hold = last + 1500; gov.acc = 0; gov.n = 0; state.dirty = true; if (!raf) raf = requestAnimationFrame(frame); }
  else { if (raf) cancelAnimationFrame(raf); raf = 0; state.keys.clear(); if (player) player.keys.clear(); }
}
document.addEventListener('visibilitychange', () => { if (document.hidden) setActive(false); else if (stage.dataset.visible === '1') setActive(true); });
export const isLoaded = () => state.loaded;
