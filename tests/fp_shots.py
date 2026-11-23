"""Знімки від першої особи: біжимо на об'єкти й дивимось, де зупиняє колізія. Запуск: KSU_OUT=dir python tests/fp_shots.py"""
import asyncio, os, math, json
from playwright.async_api import async_playwright
OUT = os.environ.get('KSU_OUT', '.')
URL = 'http://127.0.0.1:8765/index.html'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-angle=swiftshader', '--use-gl=angle', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'])
        pg = await b.new_page(viewport={'width': 1280, 'height': 720}, device_scale_factor=1)
        await pg.goto(URL); await pg.click('#poster-start'); await pg.wait_for_function('window.__ksu !== undefined', timeout=240000); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f'{OUT}/fp_01_spawn.png')
        async def run_at(name, sx, sz, tx, tz, secs, shot, pitch=0.0):
            r = await pg.evaluate(f"""(()=>{{const p=__ksu.player;__ksu.state.mode='x';p.teleport(({sx}),({sz}),Math.atan2(-(({tx})-({sx})),-(({tz})-({sz}))),({pitch}));p.keys=new Set(['KeyW','ShiftLeft']);
              for(let i=0;i<{int(secs*60)};i++)p.update(1/60);p.keys=new Set();__ksu.state.mode='walk';return {{x:p.pos.x,z:p.pos.z,y:p.pos.y}}}})()""")
            await pg.wait_for_timeout(1800); await pg.screenshot(path=f'{OUT}/{shot}.png'); print(shot, json.dumps(r))
        fo = await pg.evaluate("(()=>{const o=__ksu.scene.getObjectByName('PK_fountain');const b=new __ksu.THREE.Box3().setFromObject(o);return [(b.min.x+b.max.x)/2,(b.min.z+b.max.z)/2,(b.max.x-b.min.x)/2]})()")
        print('fountain', fo)
        await run_at('fountain', fo[0] - 12, fo[1] + 1, fo[0], fo[1], 5, 'fp_02_fountain', pitch=-0.12)
        at = await pg.evaluate("(()=>{const o=__ksu.scene.getObjectByName('Athena_pedestal');const b=new __ksu.THREE.Box3().setFromObject(o);return [(b.min.x+b.max.x)/2,(b.min.z+b.max.z)/2]})()")
        await run_at('athena', at[0] + 8, at[1] + 6, at[0], at[1], 4, 'fp_03_athena', pitch=0.1)
        # головний корпус: з майданчика на північ від входу
        await run_at('mainwall', 50, -42, 20, -42, 8, 'fp_04_mainwall')
        # стовбур дерева: перше з сітки
        tr = await pg.evaluate("(()=>{const g=__ksu.grid;for(let j=2400>>2;j<g.h;j+=7)for(let i=200;i<g.w;i+=7){const q=j*g.w+i;if(g.zmin[q]===0&&g.zmax[q]===100&&g.x0+i*g.cs>85&&g.x0+i*g.cs<130&&g.z0+j*g.cs<-50&&g.z0+j*g.cs>-90)return [g.x0+(i+.5)*g.cs,g.z0+(j+.5)*g.cs]}return null})()")
        print('tree', tr)
        if tr: await run_at('tree', tr[0] + 5, tr[1] + 1, tr[0], tr[1], 3, 'fp_05_tree', pitch=0.0)
        await run_at('stairs', 39, -56, 39, -66, 5, 'fp_06_stairs', pitch=0.05)
        await run_at('fence', 130, -20, 130, 40, 6, 'fp_07_run_south', pitch=0.0)
        await b.close()
asyncio.run(main())
