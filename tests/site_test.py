"""Функціональні тести сайту: кнопки, посилання, секції, ліниве завантаження 3D, картки, мобільна версія.
Запуск: python tests/site_test.py [url]   (потрібен запущений сервер, напр. start.bat)"""
import asyncio, sys, json, os
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/index.html'
OUT = os.environ.get('KSU_OUT', '.')
ARGS = ['--use-angle=swiftshader', '--use-gl=angle', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl']
R = {}; fails = []
def check(name, ok, extra=''):
    R[name] = ('OK ' if ok else 'FAIL ') + str(extra)
    if not ok: fails.append(name)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=ARGS)
        # ================= ДЕСКТОП =================
        ctx = await b.new_context(viewport={'width': 1440, 'height': 900}); pg = await ctx.new_page()
        reqs = []; errs = []
        pg.on('request', lambda r: reqs.append(r.url)); pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
        pg.on('response', lambda r: errs.append(f'HTTP {r.status} {r.url}') if r.status >= 400 else None)
        await pg.goto(URL); await pg.wait_for_timeout(1500)
        check('lazy_no_glb_on_open', not any(u.endswith('.glb') for u in reqs) and not any('tour.js' in u or 'three.module' in u for u in reqs))
        # якорі та посилання
        links = await pg.evaluate("[...document.querySelectorAll('a[href]')].map(a=>[a.getAttribute('href'),a.target,a.rel])")
        anchors = [l[0] for l in links if l[0].startswith('#') and l[0] != '#']
        missing = [a for a in set(anchors) if not await pg.evaluate(f"!!document.querySelector('{a}')")]
        check('anchors_exist', not missing, missing or len(set(anchors)))
        ext = [l for l in links if l[0].startswith('http')]
        check('external_links', ext and all(l[0] == 'https://www.kspu.edu/' and l[1] == '_blank' and 'noopener' in l[2] for l in ext), len(ext))
        # навігація: клік по кожному пункту прокручує до розділу
        for href in ['#about', '#tour', '#campus', '#top']:
            await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(200)
            await pg.click(f'.nav a[href="{href}"]') if href != '#top' else await pg.click('.brand')
            await pg.wait_for_timeout(1300)
            top = await pg.evaluate(f"document.querySelector('{href}').getBoundingClientRect().top")
            check(f'nav_{href}', abs(top) < 120, round(top))
        # шапка стає суцільною при прокрутці
        await pg.evaluate("window.scrollTo(0,600)"); await pg.wait_for_timeout(300)
        check('header_scrolled', await pg.evaluate("document.getElementById('header').classList.contains('scrolled')"))
        check('no_horizontal_scroll', await pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        # ===== запуск екскурсії з Hero =====
        await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(300)
        await pg.click('.hero .btn-primary')
        await pg.wait_for_function('window.__ksu !== undefined', timeout=240000); await pg.wait_for_timeout(2000)
        glb = [u for u in reqs if u.endswith('.glb')]
        check('glb_loaded_once', len(glb) == 1, len(glb))
        st = await pg.evaluate("({mode:__ksu.state.mode,eng:__ksu.state.engaged,act:__ksu.state.active,poster:document.getElementById('tour-poster').classList.contains('hidden'),ui:!document.getElementById('ui').hidden})")
        check('tour_started', st['mode'] == 'walk' and st['eng'] and st['act'] and st['poster'] and st['ui'], st)
        stage_box = await pg.evaluate("(()=>{const r=document.getElementById('tour-stage').getBoundingClientRect();return [r.top,r.bottom,innerHeight]})()")
        check('stage_in_viewport', stage_box[0] >= -5 and stage_box[1] <= stage_box[2] + 5, stage_box)
        await pg.screenshot(path=f'{OUT}/site_tour_desktop.png')
        # клавіатура працює в сцені
        z0 = await pg.evaluate("__ksu.player.pos.z"); await pg.evaluate("__ksu.player.teleport(50,-42,Math.PI,0)")
        await pg.keyboard.down('KeyW'); await pg.wait_for_timeout(2500); await pg.keyboard.up('KeyW')
        p1 = await pg.evaluate("[__ksu.player.pos.x,__ksu.player.pos.z]")
        check('wasd_moves_in_tour', abs(p1[1] + 42) > 0.1, p1)
        # поза сценою клавіші не перехоплюються (Space повинен прокручувати сторінку)
        await pg.click('#campus .section-head h2'); await pg.wait_for_timeout(200)
        eng = await pg.evaluate("__ksu.state.engaged"); check('click_outside_disengages', eng is False, eng)
        prevented = await pg.evaluate("(()=>{const e=new KeyboardEvent('keydown',{code:'Space',cancelable:true,bubbles:true});window.dispatchEvent(e);return e.defaultPrevented})()")
        check('space_not_hijacked_outside', prevented is False)
        # рендер призупиняється поза екраном
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)"); await pg.wait_for_timeout(600)
        check('render_paused_offscreen', await pg.evaluate("__ksu.state.active") is False)
        # ===== картки → 3D без перезавантаження моделі =====
        VIEWS = {'main': (84, 22), 'athena': (50, -42), 'park': (100.5, -69.5), 'dorm': (40, 45), 'courts': (92, -112)}
        for key, (x, z) in VIEWS.items():
            await pg.evaluate("window.scrollTo(0, document.querySelector('#campus').offsetTop)"); await pg.wait_for_timeout(400)
            await pg.click(f'.card[data-view="{key}"] .btn-link'); await pg.wait_for_timeout(1500)
            pos = await pg.evaluate("[__ksu.player.pos.x,__ksu.player.pos.z,__ksu.state.mode,__ksu.state.engaged]")
            d = ((pos[0] - x) ** 2 + (pos[1] - z) ** 2) ** .5
            check(f'card_{key}_teleports', pos[2] == 'walk' and d < 3 and pos[3], [round(v, 1) if isinstance(v, float) else v for v in pos] + [round(d, 1)])
        # клік по самій картці (не лише по кнопці)
        await pg.evaluate("window.scrollTo(0, document.querySelector('#campus').offsetTop)"); await pg.wait_for_timeout(400)
        await pg.click('.card[data-view="park"] .card-img'); await pg.wait_for_timeout(1200)
        check('card_body_click', abs(await pg.evaluate("__ksu.player.pos.x") - 100.5) < 3)
        check('glb_still_once', len([u for u in reqs if u.endswith('.glb')]) == 1)
        # ===== усі кнопки в сцені =====
        for key in ['main', 'athena', 'park', 'dorm', 'courts', 'aerial', 'parkAerial', 'sport']:
            await pg.click(f'#views button[data-view="{key}"]'); await pg.wait_for_timeout(400)
            m = await pg.evaluate("[__ksu.state.mode,__ksu.camera.position.y]")
            exp = 'free' if key in ('aerial', 'parkAerial', 'sport') else 'walk'
            check(f'btn_{key}', m[0] == exp, [m[0], round(m[1], 1)])
        await pg.click('#mode-walk'); await pg.wait_for_timeout(200); m1 = await pg.evaluate("__ksu.state.mode")
        await pg.click('#mode-free'); await pg.wait_for_timeout(200); m2 = await pg.evaluate("__ksu.state.mode")
        check('mode_buttons', (m1, m2) == ('walk', 'free'), (m1, m2))
        await pg.keyboard.press('KeyF'); await pg.wait_for_timeout(200); m3 = await pg.evaluate("__ksu.state.mode")
        await pg.keyboard.press('KeyF'); await pg.wait_for_timeout(200); m4 = await pg.evaluate("__ksu.state.mode")
        check('F_toggles_mode', (m3, m4) == ('walk', 'free'), (m3, m4))
        await pg.click('#mode-walk')
        await pg.keyboard.press('KeyR'); await pg.wait_for_timeout(300)
        rp = await pg.evaluate("[__ksu.player.pos.x,__ksu.player.pos.z]"); check('R_respawn', abs(rp[0] - 50) < 2 and abs(rp[1] + 42) < 2, rp)
        # налаштування
        await pg.click('#toggles summary'); await pg.check('#t-eco'); await pg.wait_for_timeout(300)
        check('eco_mode', await pg.evaluate("__ksu.renderer.getPixelRatio()") <= 0.76, await pg.evaluate("__ksu.renderer.getPixelRatio()"))
        await pg.uncheck('#t-eco'); await pg.check('#t-stats'); await pg.wait_for_timeout(1200)
        check('stats_toggle', (await pg.inner_text('#stats')).startswith('FPS'))
        await pg.uncheck('#t-stats')
        # повний екран
        await pg.click('#fs-btn'); await pg.wait_for_timeout(800)
        fs = await pg.evaluate("[!!document.fullscreenElement, document.getElementById('tour-stage').classList.contains('is-fs')||document.getElementById('tour-stage').classList.contains('is-fs-css'), document.getElementById('tour-stage').getBoundingClientRect().height]")
        check('fullscreen_on', fs[0] or fs[1], fs)
        await pg.screenshot(path=f'{OUT}/site_fullscreen.png')
        await pg.click('#fs-btn'); await pg.wait_for_timeout(600)
        check('fullscreen_off', not await pg.evaluate("!!document.fullscreenElement || document.getElementById('tour-stage').classList.contains('is-fs-css')"))
        check('desktop_no_errors', not [e for e in errs if 'GL Driver' not in e], [e for e in errs if 'GL Driver' not in e][:5])
        await ctx.close()

        # ================= ТЕЛЕФОН =================
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2); pg = await ctx.new_page()
        merrs = []; pg.on('pageerror', lambda e: merrs.append(str(e))); pg.on('console', lambda m: merrs.append(m.text) if m.type == 'error' else None)
        await pg.goto(URL); await pg.wait_for_timeout(1500)
        check('m_no_hscroll', await pg.evaluate("document.documentElement.scrollWidth <= innerWidth"), await pg.evaluate("document.documentElement.scrollWidth"))
        await pg.tap('#burger'); await pg.wait_for_timeout(500)
        check('m_burger_opens', await pg.evaluate("document.getElementById('nav').classList.contains('open')"))
        await pg.screenshot(path=f'{OUT}/site_mobile_menu.png')
        await pg.tap('.nav a[href="#campus"]'); await pg.wait_for_timeout(1200)
        check('m_nav_closes_and_scrolls', not await pg.evaluate("document.getElementById('nav').classList.contains('open')") and await pg.evaluate("document.querySelector('#campus').getBoundingClientRect().top") < 100)
        await pg.evaluate("window.scrollTo(0,0)"); await pg.wait_for_timeout(300)
        await pg.tap('.hero .btn-primary')
        await pg.wait_for_function('window.__ksu !== undefined', timeout=240000); await pg.wait_for_timeout(2000)
        await pg.screenshot(path=f'{OUT}/site_mobile_tour.png')
        vis = await pg.evaluate("({joy:getComputedStyle(document.getElementById('touch')).display, free:getComputedStyle(document.getElementById('mode-free')).display})")
        check('m_touch_ui_visible', vis['joy'] == 'block' and vis['free'] == 'none', vis)
        await pg.evaluate("__ksu.player.teleport(50,-42,Math.PI,0)")
        moved = await pg.evaluate("""(async()=>{const j=document.getElementById('joy'),r=j.getBoundingClientRect(),cx=r.left+r.width/2,cy=r.top+r.height/2;
          const ev=(t,x,y)=>j.dispatchEvent(new PointerEvent(t,{pointerId:7,pointerType:'touch',clientX:x,clientY:y,bubbles:true}));
          ev('pointerdown',cx,cy);ev('pointermove',cx,cy-46);await new Promise(r=>setTimeout(r,2500));const z=__ksu.player.pos.z;ev('pointerup',cx,cy-46);return [z,__ksu.player.touch.z]})()""")
        check('m_joystick_moves', abs(moved[0] + 42) > 0.3, moved)
        yaw0 = await pg.evaluate("__ksu.player.yaw")
        await pg.evaluate("""(()=>{const c=document.getElementById('view');const ev=(t,x,y)=>c.dispatchEvent(new PointerEvent(t,{pointerId:9,pointerType:'touch',clientX:x,clientY:y,bubbles:true}));ev('pointerdown',200,300);ev('pointermove',260,300);ev('pointerup',260,300)})()""")
        check('m_touch_look', abs(await pg.evaluate("__ksu.player.yaw") - yaw0) > 0.05)
        await pg.evaluate("__ksu.player.teleport(50,-42,0,0)")
        jmp = await pg.evaluate("""(async()=>{const b=document.getElementById('btn-jump');b.dispatchEvent(new PointerEvent('pointerdown',{pointerId:11,pointerType:'touch',bubbles:true}));let mx=0;for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,40));mx=Math.max(mx,__ksu.player.pos.y)}b.dispatchEvent(new PointerEvent('pointerup',{pointerId:11,pointerType:'touch',bubbles:true}));return mx})()""")
        check('m_jump_button', jmp > 0.2, round(jmp, 2))
        check('mobile_no_errors', not [e for e in merrs if 'GL Driver' not in e], [e for e in merrs if 'GL Driver' not in e][:5])
        await ctx.close()
        # ================= ПЛАНШЕТ: лише верстка =================
        ctx = await b.new_context(viewport={'width': 820, 'height': 1180}); pg = await ctx.new_page()
        await pg.goto(URL); await pg.wait_for_timeout(1200)
        check('tablet_no_hscroll', await pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        await pg.screenshot(path=f'{OUT}/site_tablet_hero.png')
        await ctx.close()
        await b.close()
    print(json.dumps(R, ensure_ascii=False, indent=1)); print('FAILS:', fails)
asyncio.run(main())
