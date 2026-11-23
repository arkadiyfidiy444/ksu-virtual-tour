"""Автотести керування/колізій у headless Chromium. Запуск: python tests/walk_test.py [url]"""
import asyncio, sys, json, time, os
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/index.html'
OUT = os.environ.get('KSU_OUT', '.')
HELPERS = r"""
window.T = {
  sim(keys, secs, dt = 1/60) {
    const k = __ksu, p = k.player; p.keys = new Set(keys); const n = Math.round(secs / dt); let viol = 0, maxY = 0, minD = 1e9;
    for (let i = 0; i < n; i++) { p.update(dt); if (p._overlaps(p.pos.x, p.pos.z, p.pos.y)) viol++; maxY = Math.max(maxY, p.pos.y); }
    p.keys = new Set(); return { viol, maxY, x: p.pos.x, y: p.pos.y, z: p.pos.z };
  },
  place(x, z, yaw) { const p = __ksu.player; p.teleport(x, z, yaw, 0); return { x: p.pos.x, z: p.pos.z, y: p.pos.y }; },
  box(name) { const o = __ksu.scene.getObjectByName(name); if (!o) return null; const b = new __ksu.THREE.Box3().setFromObject(o); return { min: [b.min.x, b.min.y, b.min.z], max: [b.max.x, b.max.y, b.max.z] }; }
};
"""
async def main():
    res = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-angle=swiftshader', '--use-gl=angle', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'])
        pg = await b.new_page(viewport={'width': 1280, 'height': 760}, device_scale_factor=1)
        logs = []
        pg.on('console', lambda m: logs.append(f'[{m.type}] {m.text}')); pg.on('pageerror', lambda e: logs.append(f'[pageerror] {e}'))
        await pg.goto(URL); await pg.click('#poster-start'); await pg.wait_for_function('window.__ksu !== undefined', timeout=240000)
        await pg.wait_for_timeout(1500); await pg.evaluate(HELPERS)
        await pg.click('#tour-stage', position={'x':20,'y':400}) if False else None
        print('mode', await pg.evaluate('__ksu.state.mode'), 'pos', await pg.evaluate('JSON.stringify(__ksu.player.pos)'))
        await pg.screenshot(path=f'{OUT}/fp_spawn.png')
        # 1) реальне керування клавіатурою (WASD, Shift) + мишею (drag-look без Pointer Lock у headless)
        p0 = await pg.evaluate('({x:__ksu.player.pos.x,z:__ksu.player.pos.z,yaw:__ksu.player.yaw})')
        await pg.keyboard.down('KeyW'); await pg.wait_for_timeout(2500); await pg.keyboard.up('KeyW')
        p1 = await pg.evaluate('({x:__ksu.player.pos.x,z:__ksu.player.pos.z})')
        res['kbd_W_moved_m'] = round(((p1['x']-p0['x'])**2+(p1['z']-p0['z'])**2)**.5, 2)
        await pg.evaluate("__ksu.player.drag = true; for (let i=0;i<4;i++) window.dispatchEvent(new MouseEvent('mousemove',{clientX:640+i*100,clientY:380,movementX:100,movementY:0}))")
        y1 = await pg.evaluate('__ksu.player.yaw'); res['mouse_dx400_yaw_delta_deg'] = round((y1 - p0['yaw']) * 57.2958, 1)
        await pg.evaluate("__ksu.player.drag = false")
        await pg.screenshot(path=f'{OUT}/fp_after_mouse.png')
        # 360°: yaw без обмежень
        res['full_turn'] = await pg.evaluate("(()=>{const p=__ksu.player;const y=p.yaw;for(let i=0;i<10;i++)p.look(-Math.round(2*Math.PI/p.cfg.sensitivity/10),0);return Math.abs(p.yaw-y-2*Math.PI)<0.01})()")
        res['pitch_clamped'] = await pg.evaluate("(()=>{const p=__ksu.player;p.look(0,-99999);const a=p.pitch;p.look(0,99999);return [a.toFixed(2),p.pitch.toFixed(2)]})()")
        await pg.evaluate("__ksu.renderer.render = () => {}")   # далі — чиста фізика без важкого софтверного рендера
        t_start = time.time()
        # 2) швидкості
        await pg.evaluate("T.place(50,-42,Math.PI)")   # дивимось на +Z (на південь)
        r = await pg.evaluate("T.sim(['KeyW'],1.5)"); a = await pg.evaluate("T.sim([],0.5)")
        res['walk_speed_mps'] = round(((r['x']-50)**2+(r['z']+42)**2)**.5/1.5, 2)
        await pg.evaluate("T.place(50,-42,Math.PI)"); r = await pg.evaluate("T.sim(['KeyW','ShiftLeft'],1.5)")
        res['run_speed_mps'] = round(((r['x']-50)**2+(r['z']+42)**2)**.5/1.5, 2)
        # 3) стрибок
        jmp = await pg.evaluate("""(()=>{const p=__ksu.player;__ksu.state.mode='x';p.teleport(50,-42,0,0);const y0=p.pos.y;p.keys=new Set(['Space']);let mx=0,air=0,jumps=0,was=true;
          for(let i=0;i<120;i++){p.update(1/60);if(i==3)p.keys=new Set();mx=Math.max(mx,p.pos.y);if(!p.grounded)air++;if(was&&!p.grounded)jumps++;was=p.grounded;}
          __ksu.state.mode='walk';return {ground_y:+y0.toFixed(2),apex_m:+(mx-y0).toFixed(2),air_frames:air,jumps,landed:p.grounded,y_end:+p.pos.y.toFixed(2)}})()""")
        res['jump'] = jmp
        # 4) висота очей
        res['eye_height'] = await pg.evaluate("(()=>{const k=__ksu;k.player.update(1/60);for(let i=0;i<60;i++)k.player.update(1/60);return +(k.camera.position.y-k.player.pos.y).toFixed(2)})()")
        # 5) цілеспрямовані колізії: біжимо на об'єкти з 8 напрямків
        async def approach(name, label, margin=14, minclear=None):
            print('...', label, round(time.time()-t_start,1), flush=True)
            bx = await pg.evaluate(f"T.box('{name}')")
            if not bx: res[label] = 'немає вузла'; return
            cx = (bx['min'][0]+bx['max'][0])/2; cz = (bx['min'][2]+bx['max'][2])/2
            tot = 0; worst = 1e9; stopped = 0
            import math
            for k in range(8):
                ang = k*math.pi/4; sx = cx + math.cos(ang)*(max(bx['max'][0]-bx['min'][0], bx['max'][2]-bx['min'][2])/2+margin); sz = cz + math.sin(ang)*(max(bx['max'][0]-bx['min'][0], bx['max'][2]-bx['min'][2])/2+margin)
                yaw = math.atan2(-(cx-sx), -(cz-sz))
                pos = await pg.evaluate(f"T.place({sx},{sz},{yaw})")
                out = await pg.evaluate("T.sim(['KeyW','ShiftLeft'],6)")
                tot += out['viol']
                # чи гравець опинився всередині габаритів об'єкта (з урахуванням радіуса)
                inside = bx['min'][0]+0.3 < out['x'] < bx['max'][0]-0.3 and bx['min'][2]+0.3 < out['z'] < bx['max'][2]-0.3
                if inside: worst = -1
                if abs(out['x']-pos['x'])+abs(out['z']-pos['z']) < 40: stopped += 1
            res[label] = {'violations': tot, 'blocked_runs_of_8': stopped}
        await approach('Main_body', 'wall_Main_body')
        await approach('South_dorm_A', 'wall_South_dorm_A')
        await approach('Sport_hall', 'wall_Sport_hall')
        await approach('PK_fountain', 'fountain', margin=8)
        await approach('Athena_pedestal', 'athena_pedestal', margin=8)
        await approach('Annex', 'annex', margin=8)
        # 6) дерева: 60 випадкових стовбурів із сітки (клітинки з zmax==5 м, zmin==0)
        trees = await pg.evaluate("""(()=>{const g=__ksu.grid;const out=[];for(let j=0;j<g.h;j+=1)for(let i=0;i<g.w;i+=1){const q=j*g.w+i;if(g.zmin[q]===0&&g.zmax[q]===100)out.push([g.x0+(i+.5)*g.cs,g.z0+(j+.5)*g.cs]);}return out})()""")
        import random, math
        random.seed(1); sample = random.sample(trees, 80); v = 0; entered = 0
        for (tx, tz) in sample:
            ang = random.random()*6.283; sx = tx+math.cos(ang)*6; sz = tz+math.sin(ang)*6
            yaw = math.atan2(-(tx-sx), -(tz-sz)); await pg.evaluate(f"T.place({sx},{sz},{yaw})")
            o = await pg.evaluate("T.sim(['KeyW','ShiftLeft'],3)"); v += o['viol']
            if math.hypot(o['x']-tx, o['z']-tz) < 0.2: entered += 1
        res['trees_sampled'] = len(sample); res['trees_violations'] = v; res['trees_center_reached'] = entered
        # 7) забір на паркан
        await approach('South_fence_bars', 'fence_south')
        # 8) сходи: підйом та зійти
        bx = await pg.evaluate("T.box('StairsA_0')"); res['stairsA_box'] = bx

        # 8b) ВІРНІСТЬ: відстань від очей до реальної геометрії (без листя/трави) та «усередині тіла» через back-face
        fid = await pg.evaluate("""(()=>{const k=__ksu,T3=k.THREE,p=k.player;const meshes=[];k.scene.traverse(o=>{if(!o.isMesh)return;const m=Array.isArray(o.material)?o.material[0]:o.material;const mn=(m&&m.name)||'';
            if(/^(F_|Water|CarGlass|Text|M_grass|Soil)/.test(mn)||/^(MRG|TF_|SH_|Ground)/.test(o.name)||(o.parent&&/^(MRG|Ground)/.test(o.parent.name)))return; meshes.push(o);});
          const rc=new T3.Raycaster();rc.far=3;let minD=9,inside=0,N=0;const origin=new T3.Vector3(),dir=new T3.Vector3();
          let seed=777;const rnd=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296};
          const worst=[];
          for(let r=0;r<120;r++){const x=40+rnd()*120,z=-110+rnd()*180;p.teleport(x,z,rnd()*6.283,0);p.keys=new Set(['KeyW','ShiftLeft']);
            for(let i=0;i<300;i++){if(i%60===0)p.yaw+=(rnd()-.5)*2.5;p.update(1/60);}
            p.keys=new Set();origin.set(p.pos.x,p.pos.y+1.0,p.pos.z);let ins=0,rays=0,md=9;
            for(let a=0;a<16;a++){dir.set(Math.cos(a*Math.PI/8),0,Math.sin(a*Math.PI/8));rc.set(origin,dir);const h=rc.intersectObjects(meshes,false);rays++;
              if(h.length){md=Math.min(md,h[0].distance);const n=h[0].face.normal.clone().transformDirection(h[0].object.matrixWorld);if(n.dot(dir)>0)ins++;}}
            N++;minD=Math.min(minD,md);if(ins>=8)inside++; if(md<0.15)worst.push([+x.toFixed(1),+z.toFixed(1),+md.toFixed(2)]);}
          return {positions:N,min_dist_to_geometry_m:+minD.toFixed(2),inside_solid:inside,closer_than_15cm:worst.slice(0,8)}})()""")
        res['fidelity'] = fid
        # 8c) сходи: підйом по StairsA з 8 боків до найвищої клітинки
        st = await pg.evaluate("""(()=>{const k=__ksu,g=k.grid,p=k.player;const b=T.box('StairsA_0');let best=0,bx=0,bz=0;
          for(let z=b.min[2];z<=b.max[2];z+=0.2)for(let x=b.min[0];x<=b.max[0];x+=0.2){const h=g.groundAt(x,z);if(h>best){best=h;bx=x;bz=z;}}
          const out=[];for(let a=0;a<12;a++){const sx=bx+Math.cos(a*Math.PI/6)*7,sz=bz+Math.sin(a*Math.PI/6)*7;p.teleport(sx,sz,Math.atan2(-(bx-sx),-(bz-sz)),0);p.keys=new Set(['KeyW']);let mx=0,viol=0;for(let i=0;i<60*8;i++){p.update(1/60);mx=Math.max(mx,p.pos.y);if(p._overlaps(p.pos.x,p.pos.z,p.pos.y))viol++;}p.keys=new Set();out.push({max_h:+mx.toFixed(2),viol});}
          return {top_h:best,top:[+bx.toFixed(1),+bz.toFixed(1)],runs:out}})()""")
        res['stairs'] = st
        # 9) випадковий «шторм»: 300 випадкових стартів, випадкові клавіші, жодного входу в перешкоди
        storm = await pg.evaluate("""(()=>{const k=__ksu,p=k.player,g=k.grid;let viol=0,runs=0,jumps=0;const combos=[['KeyW'],['KeyW','KeyA'],['KeyW','KeyD'],['KeyS','KeyA'],['KeyD'],['KeyW','Space'],['KeyW','ShiftLeft','Space']];
          let seed=12345;const rnd=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296};
          for(let r=0;r<300;r++){const x=40+rnd()*120,z=-110+rnd()*180;p.teleport(x,z,rnd()*6.283,0);p.keys=new Set(combos[Math.floor(rnd()*combos.length)]);
            for(let i=0;i<400;i++){ if(i%90===0){p.yaw+=(rnd()-.5)*3;} p.update(1/60); if(p._overlaps(p.pos.x,p.pos.z,p.pos.y))viol++; }runs++;}
          p.keys=new Set();return {runs,viol}})()""")
        res['storm'] = storm; res['unstick_total'] = await pg.evaluate('__ksu.player.stats.unstick||0'); res['unstick_log'] = await pg.evaluate('__ksu.player.stats.log||[]')
        # 10) швидкодія колізій: час update на кадр у щільній зоні
        perf = await pg.evaluate("""(()=>{const p=__ksu.player;p.teleport(60,-30,1,0);p.keys=new Set(['KeyW','ShiftLeft']);const N=20000;const t=performance.now();for(let i=0;i<N;i++){if(i%100===0)p.yaw+=0.7;p.update(1/60);}const tot=performance.now()-t;p.keys=new Set();return {avg_us_per_update:+(tot*1000/N).toFixed(2)}})()""")
        res['collision_update_cost'] = perf
        # 11) перемикання режимів
        await pg.keyboard.press('KeyF'); await pg.wait_for_timeout(300)
        m1 = await pg.evaluate('__ksu.state.mode'); await pg.keyboard.down('KeyW'); await pg.wait_for_timeout(1000); await pg.keyboard.up('KeyW')
        yfree = await pg.evaluate('__ksu.camera.position.toArray()')
        await pg.keyboard.press('KeyF'); await pg.wait_for_timeout(300); m2 = await pg.evaluate('__ksu.state.mode')
        res['mode_toggle'] = [m1, m2]
        await pg.click('#mode-free'); await pg.wait_for_timeout(200); m3 = await pg.evaluate('__ksu.state.mode')
        await pg.click('#mode-walk'); await pg.wait_for_timeout(200); m4 = await pg.evaluate('__ksu.state.mode')
        res['mode_buttons'] = [m3, m4]
        # 12) FPS (SwiftShader, не показник реального GPU)
        await pg.wait_for_timeout(1500)
        res['elapsed_s'] = round(time.time()-t_start,1)
        res['console'] = [l for l in logs if 'error' in l.lower() or 'pageerror' in l][:10]
        await b.close()
    print(json.dumps(res, ensure_ascii=False, indent=1))
asyncio.run(main())
