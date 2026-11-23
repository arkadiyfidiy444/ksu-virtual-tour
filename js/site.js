// Сайт: навігація, анімації появи, ліниве завантаження 3D-екскурсії.
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const root = document.documentElement;

/* ---------- шапка: фон при прокрутці, активний розділ, мобільне меню ---------- */
const header = $('#header'), nav = $('#nav'), burger = $('#burger');
const onScroll = () => header.classList.toggle('scrolled', window.scrollY > 24);
onScroll(); window.addEventListener('scroll', onScroll, { passive: true });

burger.addEventListener('click', () => {
  const open = nav.classList.toggle('open'); burger.setAttribute('aria-expanded', String(open));
});
$$('a', nav).forEach((a) => a.addEventListener('click', () => { nav.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); }));
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') { nav.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); } });

const sections = ['about', 'tour', 'campus'].map((id) => document.getElementById(id));
const spy = new IntersectionObserver((es) => es.forEach((e) => {
  if (!e.isIntersecting) return;
  $$('a', nav).forEach((a) => a.classList.toggle('active', a.getAttribute('href') === '#' + e.target.id));
}), { rootMargin: '-45% 0px -50% 0px' });
sections.forEach((s) => s && spy.observe(s));

/* ---------- поява елементів ---------- */
const reveal = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); reveal.unobserve(e.target); } }), { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
$$('.reveal').forEach((el) => reveal.observe(el));

/* анімація підказки в Hero зупиняється, коли Hero поза екраном */
const heroEl = $('.hero');
if (heroEl) new IntersectionObserver((es) => es.forEach((e) => heroEl.classList.toggle('is-off', !e.isIntersecting))).observe(heroEl);

/* ---------- 3D-екскурсія: ліниве завантаження ---------- */
const stage = $('#tour-stage'), poster = $('#tour-poster'), bar = $('#progress-bar'), progress = $('#progress'), note = $('#poster-note'), err = $('#poster-error');
let tourMod = null, starting = null, stageVisible = false;

const coarse = matchMedia('(pointer: coarse)').matches;
if (coarse) note.textContent = 'Модель близько 40 МБ — краще завантажувати через Wi-Fi. Рухайтесь джойстиком, оглядайтесь перетягуванням.';

function scrollToTour() { stage.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }); }

async function ensureTour() {
  if (tourMod && tourMod.isLoaded()) return tourMod;
  if (starting) return starting;
  poster.classList.add('loading'); progress.hidden = false; err.hidden = true; note.textContent = 'Завантаження моделі…';
  starting = (async () => {
    try {
      tourMod = await import('./tour.js');
      await tourMod.load((f, text) => { bar.style.width = (f * 100).toFixed(1) + '%'; note.textContent = text; });
      bar.style.width = '100%';
      poster.classList.add('hidden');
      tourMod.setActive(stageVisible);
      return tourMod;
    } catch (e) {
      console.error(e); starting = null; tourMod = null;
      poster.classList.remove('loading'); progress.hidden = true;
      err.hidden = false; err.textContent = 'Не вдалося завантажити 3D-модель: ' + (e && e.message || e) + '. Переконайтесь, що сайт відкрито через start.bat (а не подвійним кліком по index.html).';
      note.textContent = '';
      throw e;
    }
  })();
  return starting;
}

async function startTour(view) {
  scrollToTour();
  try {
    const t = await ensureTour();
    t.goTo(view || 'spawn'); t.engage(true);
    t.setActive(true);
  } catch (_) { /* помилка вже показана на постері */ }
}

$$('[data-start-tour]').forEach((b) => b.addEventListener('click', () => startTour()));
$$('.card').forEach((c) => {
  const go = () => startTour(c.dataset.view);
  c.addEventListener('click', go);
  $('.btn-link', c).addEventListener('click', (e) => { e.stopPropagation(); go(); });
});

/* рендер лише коли сцену видно */
new IntersectionObserver((es) => es.forEach((e) => {
  stageVisible = e.isIntersecting; stage.dataset.visible = stageVisible ? '1' : '0';
  if (tourMod && tourMod.isLoaded()) { tourMod.setActive(stageVisible); if (!stageVisible) tourMod.engage(false); }
}), { threshold: 0.05 }).observe(stage);

/* якщо сторінку відкрито як file:// — модулі не працюватимуть */
if (location.protocol === 'file:') {
  err.hidden = false; err.textContent = 'Сторінку відкрито напряму з диска. Запустіть start.bat і відкрийте http://localhost:8080.';
}
