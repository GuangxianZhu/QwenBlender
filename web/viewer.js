/* QwenBlender 演示页骨架。页面内容全部来自 QB_DATA（demo.json + 零件表 + GLB），这个文件不用改。
   坐标约定：demo.json / custom.js 里一律用建模坐标（毫米，Z 朝上），这里负责换算到 three.js。 */
(function () {
  'use strict';
  var T = QB3.THREE;
  var QB = window.QB = window.QB || {};
  var $ = function (id) { return document.getElementById(id); };
  var S = {
    errors: [], ready: false, parts: {}, order: [], step: -1, stepT: 0, time: 0,
    ex: 0, exTarget: 0, sec: null, sel: null, params: {}, camGoal: null, labels: [], arrows: {},
    customRead: {}
  };
  var DATA, CFG, renderer, scene, camera, controls, root, MM = 0.001;
  var asm = { center: new T.Vector3(), radius: 1, box: new T.Box3() };
  var plane = new T.Plane(new T.Vector3(-1, 0, 0), 0);
  var HL = new T.Color(0x1f5fbf), SEL = new T.Color(0xd9730d);

  function err(msg) {
    msg = String(msg);
    if (S.errors.indexOf(msg) >= 0) return;
    S.errors.push(msg);
    var e = $('err');
    if (e) { e.style.display = 'block'; e.textContent = S.errors.slice(0, 6).join('\n'); }
  }
  window.addEventListener('error', function (e) { err('脚本错误：' + e.message + (e.lineno ? '（第 ' + e.lineno + ' 行）' : '')); });
  window.addEventListener('unhandledrejection', function (e) { err('脚本错误：' + (e.reason && e.reason.message || e.reason)); });

  function b2t(v) { return new T.Vector3(+v[0] || 0, +v[2] || 0, -(+v[1] || 0)); }
  function t2b(v) { return [v.x, -v.z, v.y]; }
  function axisVec(a) {
    if (Array.isArray(a)) return b2t(a).normalize();
    var s = String(a || 'z').toLowerCase().trim(), sign = s.charAt(0) === '-' ? -1 : 1;
    var k = s.replace(/[+-]/g, '');
    var v = k === 'x' ? [1, 0, 0] : k === 'y' ? [0, 1, 0] : [0, 0, 1];
    return b2t(v).multiplyScalar(sign);
  }
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function smooth(u) { return u * u * (3 - 2 * u); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function rich(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>'); }

  // ---------- 表达式：数字，或者用参数 id、t（本步骤已过秒数）和 Math 函数写的式子
  var exprCache = {};
  function num(x, where) {
    if (typeof x === 'number') return x;
    if (x == null) return 0;
    var f = exprCache[x];
    if (!f) {
      try { f = new Function('p', 't', 'with(Math){with(p){return (' + x + ');}}'); }
      catch (e) { err('表达式写错了：' + x + '（' + (where || '') + '）'); f = function () { return 0; }; }
      exprCache[x] = f;
    }
    try {
      var v = +f(S.params, S.stepT);
      if (!isFinite(v)) { err('表达式算出来不是数：' + x + '（' + (where || '') + '）'); return 0; }
      return v;
    } catch (e) { err('表达式出错：' + x + ' → ' + e.message); return 0; }
  }

  // ---------- 启动
  function start() {
    DATA = window.QB_DATA;
    if (!DATA) { err('没有页面数据 QB_DATA'); return; }
    CFG = DATA.config || {};
    document.title = CFG.title || '演示';
    document.querySelector('#hd h1').textContent = CFG.title || '';
    document.querySelector('#hd p').textContent = CFG.subtitle || '';
    (CFG.params || []).forEach(function (p) { S.params[p.id] = +p.value || 0; });

    var canvas = $('c');
    try {
      renderer = new T.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch (e) { err('浏览器不支持 WebGL：' + e.message); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = T.NeutralToneMapping || T.ACESFilmicToneMapping;
    renderer.localClippingEnabled = false;
    scene = new T.Scene();
    var pm = new T.PMREMGenerator(renderer);
    scene.environment = pm.fromScene(new QB3.RoomEnvironment(), 0.04).texture;
    var sun = new T.DirectionalLight(0xffffff, 1.6);
    sun.position.set(2, 4, 3);
    scene.add(sun);
    camera = new T.PerspectiveCamera(32, 1, 0.001, 100);
    controls = new QB3.OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.addEventListener('start', function () { S.camGoal = null; });

    var bin = atob(DATA.glb), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    new QB3.GLTFLoader().parse(buf.buffer, '', function (gltf) {
      try { onModel(gltf); } catch (e) { err('初始化失败：' + e.message); console.error(e); }
    }, function (e) { err('模型读不出来：' + (e && e.message || e)); });
  }

  function onModel(gltf) {
    scene.add(gltf.scene);
    root = gltf.scene.getObjectByName('QB_ROOT') || gltf.scene;
    MM = root.scale.x || 0.001;
    scene.updateMatrixWorld(true);
    var over = CFG.parts || {};
    (DATA.parts || []).forEach(function (meta) {
      var node = root.getObjectByName(meta.name);
      if (!node) { err('模型里找不到零件 ' + meta.name); return; }
      var o = over[meta.name] || {};
      var P = {
        name: meta.name, node: node, cn: o.cn || meta.cn || meta.name, info: o.info || meta.info || '',
        group: o.group || meta.group || '', pos0: node.position.clone(), quat0: node.quaternion.clone(),
        meshes: [], mats: [], caps: [], blink: 0, look: 'normal', cOff: new T.Vector3(), cQ: new T.Quaternion(),
        cColor: null, cOpacity: null, cShow: null
      };
      var found = [];
      node.traverse(function (m) { if (m.isMesh) found.push(m); });
      found.forEach(function (m) {
        var arr = Array.isArray(m.material) ? m.material : [m.material];
        arr = arr.map(function (mt) {
          var c = mt.clone();
          c.userData.base = { color: c.color.clone(), opacity: c.opacity, transparent: c.transparent, side: c.side,
            emissive: c.emissive ? c.emissive.clone() : new T.Color(0), ei: c.emissiveIntensity };
          P.mats.push(c);
          return c;
        });
        m.material = Array.isArray(m.material) ? arr : arr[0];
        m.userData.part = meta.name;
        P.meshes.push(m);
        // 剖切时的「切面」：同一个网格只画背面，用压暗的纯色，看起来像实心的截面
        var cc = arr[0].color.clone().multiplyScalar(0.55).lerp(new T.Color(0x8a2c22), 0.25);
        var cap = new T.Mesh(m.geometry, new T.MeshBasicMaterial({ color: cc, side: T.BackSide }));
        cap.visible = false; cap.raycast = function () {};
        m.add(cap); P.caps.push(cap);
      });
      var box = new T.Box3().setFromObject(node);
      P.radius = box.getSize(new T.Vector3()).length() / 2;
      P.cLocal = node.worldToLocal(box.getCenter(new T.Vector3()));
      P.c0 = root.worldToLocal(box.getCenter(new T.Vector3()));      // 零件中心（root 坐标，毫米）
      asm.box.union(box);
      var ex = o.explode || meta.explode;
      P.ex = ex ? b2t(ex) : null;
      S.parts[meta.name] = P;
      S.order.push(meta.name);
    });
    asm.box.getCenter(asm.center);
    asm.radius = Math.max(asm.box.getSize(new T.Vector3()).length() / 2, 1e-6);
    var cL = root.worldToLocal(asm.center.clone()), rL = asm.radius / MM;
    var exScale = (CFG.explode && +CFG.explode.scale) || 1;
    S.order.forEach(function (n) {
      var P = S.parts[n];
      if (!P.ex) {                         // 没给爆炸方向：从装配体中心往外推
        var d = P.c0.clone().sub(cL);
        if (d.length() < rL * 0.05) d.set(0, 1, 0);
        P.ex = d.normalize().multiplyScalar(rL * 0.9);
      }
      P.ex.multiplyScalar(exScale);
    });
    buildUI();
    var ro = new ResizeObserver(resize);
    ro.observe($('stage'));
    resize();
    setView('iso', true);
    try { if (QB.onInit) QB.onInit(api); } catch (e) { err('custom.js onInit 出错：' + e.message); }
    goStep(0, true);
    S.ready = true;
    var last = performance.now();
    (function loop(now) {
      var dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!S.manual) { update(dt); renderer.render(scene, camera); }
      requestAnimationFrame(loop);
    })(last);
  }

  function resize() {
    var st = $('stage'), w = Math.max(1, st.clientWidth), h = Math.max(1, st.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (S.lastView) setView(S.lastView, true);
  }

  // ---------- 相机
  function contentSphere(e, focus) {
    if (focus && S.parts[focus]) {
      var P = S.parts[focus];
      var c = root.localToWorld(P.c0.clone().addScaledVector(P.ex, e));
      return { c: c, r: Math.max(P.radius * 1.9, asm.radius * 0.12) };
    }
    var r = asm.radius, cL = root.worldToLocal(asm.center.clone());
    if (e > 0) S.order.forEach(function (n) {
      var P = S.parts[n];
      var d = P.c0.clone().addScaledVector(P.ex, e).sub(cL).length() * MM + P.radius;
      if (d > r) r = d;
    });
    return { c: asm.center.clone(), r: r };
  }
  var VIEWS = { front: [0, 0], back: [180, 0], right: [90, 0], left: [-90, 0], top: [0, 89.5], bottom: [0, -89.5], iso: [35, 26], iso2: [-145, 26] };
  function setView(v, instant) {
    S.lastView = v;
    var az = 35, el = 26, zoom = 1, focus = null;
    if (typeof v === 'string') { var p = VIEWS[v] || VIEWS.iso; az = p[0]; el = p[1]; }
    else if (v) {
      if (v.preset && VIEWS[v.preset]) { az = VIEWS[v.preset][0]; el = VIEWS[v.preset][1]; }
      if (v.az != null) az = +v.az; if (v.el != null) el = +v.el;
      zoom = +v.zoom || 1; focus = v.focus || null;
    }
    el = Math.max(-89.5, Math.min(89.5, el));
    var a = az * Math.PI / 180, e = el * Math.PI / 180;
    var dir = new T.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e));
    var sp = contentSphere(S.exTarget, focus);
    var fv = camera.fov * Math.PI / 360, fh = Math.atan(Math.tan(fv) * camera.aspect);
    var dist = sp.r / Math.sin(Math.min(fv, fh)) * 1.08 / zoom;
    var goal = { pos: sp.c.clone().addScaledVector(dir, dist), target: sp.c };
    camera.near = dist / 200; camera.far = dist * 20 + asm.radius * 20; camera.updateProjectionMatrix();
    if (instant) { camera.position.copy(goal.pos); controls.target.copy(goal.target); controls.update(); S.camGoal = null; }
    else S.camGoal = goal;
  }
  function refit() {           // 保持方向，只调整距离（拖爆炸滑条时用）
    var dir = camera.position.clone().sub(controls.target).normalize();
    var sp = contentSphere(S.exTarget, null);
    var fv = camera.fov * Math.PI / 360, fh = Math.atan(Math.tan(fv) * camera.aspect);
    var dist = sp.r / Math.sin(Math.min(fv, fh)) * 1.08;
    camera.far = dist * 20 + asm.radius * 20; camera.near = dist / 200; camera.updateProjectionMatrix();
    S.camGoal = { pos: sp.c.clone().addScaledVector(dir, dist), target: sp.c };
  }

  // ---------- 步骤
  function steps() { return CFG.steps || []; }
  function cur() { return steps()[S.step] || {}; }
  function goStep(i, instant) {
    var n = steps().length;
    if (!n) { S.step = -1; applyLook(); return; }
    i = Math.max(0, Math.min(n - 1, i));
    S.step = i; S.stepT = 0;
    var st = cur();
    (st.anim || []).forEach(function (a) { a._ang = 0; });
    steps().forEach(function (sx) { (sx.anim || []).forEach(function (a) {
      if (a.id && (a.type === 'crank_slider' || a.type === 'four_bar'))
        ['pos', 'angle', 'rocker'].forEach(function (k) { if (!((a.id + '_' + k) in S.params)) S.params[a.id + '_' + k] = 0; });
    }); });
    S.exTarget = clamp01(+st.explode || 0);
    if (instant) S.ex = S.exTarget;
    $('ex').value = S.exTarget;
    setSection(st.section ? st.section.axis : '', st.section && st.section.pos != null ? +st.section.pos : 0.5);
    S.sel = null; showCard(null);
    applyLook();
    buildLabels(st.labels || []);
    setView(st.view || 'iso', !!instant);
    $('steptitle').textContent = st.title || ('第 ' + (i + 1) + ' 步');
    $('stepn').textContent = (i + 1) + ' / ' + n;
    $('steptext').innerHTML = rich(st.text || '');
    $('prev').disabled = i === 0; $('next').disabled = i === n - 1;
    Array.prototype.forEach.call($('dots').children, function (d, k) { d.className = k === i ? 'on' : ''; });
    showParams(st);
    buildReadouts();
    try { if (QB.onStep) QB.onStep(api, i, st); } catch (e) { err('custom.js onStep 出错：' + e.message); }
  }

  function showParams(st) {     // 只显示这一步用到的滑条；有 custom.js 时全部显示
    var all = !!(QB.onInit || QB.onStep || QB.onFrame);
    var txt = JSON.stringify([st.anim || [], st.readouts || [], CFG.readouts || []]);
    (CFG.params || []).forEach(function (p) {
      if (!p._row) return;
      var used = all || new RegExp('(^|[^A-Za-z0-9_])' + p.id + '([^A-Za-z0-9_]|$)').test(txt);
      p._row.style.display = used ? '' : 'none';
    });
  }

  function applyLook() {
    var st = cur(), hl = st.highlight || [], gh = st.ghost || [], hd = st.hide || [];
    var anyHl = hl.length > 0;
    S.order.forEach(function (n) {
      var P = S.parts[n];
      P.look = hd.indexOf(n) >= 0 ? 'hide' : gh.indexOf(n) >= 0 ? 'ghost' : hl.indexOf(n) >= 0 ? 'hl' : anyHl ? 'dim' : 'normal';
    });
  }
  function paint() {
    var secOn = !!S.sec;
    S.order.forEach(function (n) {
      var P = S.parts[n], look = P.look, sel = S.sel === n;
      var show = P.cShow != null ? P.cShow : look !== 'hide';
      P.node.visible = show;
      if (!show) return;
      var capOn = secOn && look !== 'ghost' && look !== 'dim' && P.cOpacity == null;
      P.caps.forEach(function (c) { c.visible = capOn; });
      P.mats.forEach(function (m) {
        var b = m.userData.base;
        var op = look === 'ghost' ? 0.14 : look === 'dim' ? 0.32 : b.opacity;
        if (P.cOpacity != null) op = P.cOpacity;
        if (sel) op = Math.max(op, b.opacity);
        m.opacity = op;
        m.transparent = op < 0.999 || b.transparent;
        m.depthWrite = op >= 0.5;
        m.side = (secOn && !capOn) ? T.DoubleSide : b.side;
        if (P.cColor) m.color.copy(P.cColor); else m.color.copy(b.color);
        if (m.emissive) {
          var k = sel ? 0.45 : look === 'hl' ? 0.22 + 0.12 * Math.sin(S.time * 3) : 0;
          k = Math.max(k, P.blink * 0.6);
          if (k > 0) { m.emissive.copy(sel ? SEL : HL); m.emissiveIntensity = k; }
          else { m.emissive.copy(b.emissive); m.emissiveIntensity = b.ei; }
        }
      });
    });
  }

  function prog(t, a) {
    var Tm = Math.max(0.05, +a.time || 2), pause = a.pause != null ? +a.pause : 0.6, loop = a.loop || 'once', u;
    t -= (+a.delay || 0);
    if (t <= 0) return 0;
    if (loop === 'repeat') { u = clamp01((t % (Tm + pause)) / Tm); }
    else if (loop === 'pingpong') {
      var tt = t % (2 * (Tm + pause));
      u = tt < Tm ? tt / Tm : tt < Tm + pause ? 1 : tt < 2 * Tm + pause ? 1 - (tt - Tm - pause) / Tm : 0;
    } else u = clamp01(t / Tm);
    return a.ease === 'linear' ? u : smooth(u);
  }

  // ---------- 连杆机构（曲柄滑块、四连杆）。点和方向都是建模坐标，机构在垂直于 axis 的平面里运动。
  function names(x) { return x == null ? [] : Array.isArray(x) ? x : [x]; }
  function inPlane(v, n) { return v.clone().addScaledVector(n, -v.dot(n)); }
  function signedAngle(u, v, n) { return Math.atan2(n.dot(new T.Vector3().crossVectors(u, v)), u.dot(v)); }
  function rigid(list, from, to, q) {      // 让一组零件做刚体运动：先绕 from 点转 q，再把 from 点搬到 to
    list.forEach(function (nm) {
      var P = S.parts[nm];
      if (!P) return;
      P._p.sub(from).applyQuaternion(q).add(to);
      P._q.premultiply(q);
    });
  }
  function linkageAngle(a, w, dt) {
    if (a.angle != null) return num(a.angle, w);
    if (S.stepT > (+a.delay || 0)) a._ang = (a._ang || 0) + num(a.speed, w) * dt;
    return a._ang || 0;
  }
  function setVar(a, key, val) { if (a.id) S.params[a.id + '_' + key] = val; }
  function solveLinkage(a, w, dt) {
    var n = axisVec(a.axis || 'y'), th = linkageAngle(a, w, dt) * Math.PI / 180;
    var qc = new T.Quaternion().setFromAxisAngle(n, th);
    if (a.type === 'crank_slider') {
      var O = b2t(a.center), P0 = b2t(a.crank_pin), S0 = b2t(a.slider_pin), d = inPlane(axisVec(a.slide || 'z'), n).normalize();
      var P = P0.clone().sub(O).applyQuaternion(qc).add(O);
      var L = inPlane(S0.clone().sub(P0), n).length();
      var wv = inPlane(S0.clone().sub(P), n), b = d.dot(wv), disc = b * b - wv.lengthSq() + L * L;
      if (disc < 0) { err(w + '：连杆太短，曲柄转到这个角度时够不到滑块的导轨'); disc = 0; }
      var b0 = d.dot(inPlane(S0.clone().sub(P0), n));
      var sl = -b + (b0 >= 0 ? 1 : -1) * Math.sqrt(disc);
      var Sp = S0.clone().addScaledVector(d, sl);
      rigid(names(a.crank), O, O, qc);
      var qr = new T.Quaternion().setFromAxisAngle(n, signedAngle(inPlane(S0.clone().sub(P0), n), inPlane(Sp.clone().sub(P), n), n));
      rigid(names(a.rod), P0, P, qr);
      names(a.slider).forEach(function (nm) { if (S.parts[nm]) S.parts[nm]._p.addScaledVector(d, sl); });
      setVar(a, 'pos', sl); setVar(a, 'angle', ((th * 180 / Math.PI) % 360 + 360) % 360);
    } else {
      var A = b2t(a.a), B0 = b2t(a.b), C0 = b2t(a.c), D = b2t(a.d);
      var B = B0.clone().sub(A).applyQuaternion(qc).add(A);
      var r2 = inPlane(C0.clone().sub(B0), n).length(), r3 = inPlane(C0.clone().sub(D), n).length();
      var bd = inPlane(D.clone().sub(B), n), dist = bd.length();
      if (dist > r2 + r3 || dist < Math.abs(r2 - r3) || dist < 1e-9) {
        err(w + '：四连杆转到这个角度装不上（两根杆够不着）。曲柄不能转整圈时，用 angle 配一个范围合适的滑条');
        dist = Math.min(Math.max(dist, Math.abs(r2 - r3) + 1e-6), r2 + r3 - 1e-6);
      }
      var x = (dist * dist + r2 * r2 - r3 * r3) / (2 * dist), h = Math.sqrt(Math.max(r2 * r2 - x * x, 0));
      var e1 = bd.clone().normalize(), e2 = new T.Vector3().crossVectors(n, e1);
      var side0 = n.dot(new T.Vector3().crossVectors(inPlane(D.clone().sub(B0), n), inPlane(C0.clone().sub(B0), n))) >= 0 ? 1 : -1;
      var C = B.clone().addScaledVector(e1, x).addScaledVector(e2, side0 * h);
      C.addScaledVector(n, n.dot(C0) - n.dot(C));
      rigid(names(a.crank), A, A, qc);
      var qcp = new T.Quaternion().setFromAxisAngle(n, signedAngle(inPlane(C0.clone().sub(B0), n), inPlane(C.clone().sub(B), n), n));
      rigid(names(a.coupler), B0, B, qcp);
      var rk = signedAngle(inPlane(C0.clone().sub(D), n), inPlane(C.clone().sub(D), n), n);
      rigid(names(a.rocker), D, D, new T.Quaternion().setFromAxisAngle(n, rk));
      setVar(a, 'rocker', rk * 180 / Math.PI); setVar(a, 'angle', ((th * 180 / Math.PI) % 360 + 360) % 360);
    }
  }

  var _q = new T.Quaternion(), _v = new T.Vector3();
  function rotateAbout(pos, q, axis, deg, pivot) {
    _q.setFromAxisAngle(axis, deg * Math.PI / 180);
    if (pivot) { pos.sub(pivot).applyQuaternion(_q).add(pivot); }
    q.premultiply(_q);
  }

  function update(dt) {
    S.time += dt; S.stepT += dt;
    var k = 1 - Math.exp(-dt * 7);
    S.ex += (S.exTarget - S.ex) * k;
    if (Math.abs(S.exTarget - S.ex) < 1e-4) S.ex = S.exTarget;
    var st = cur(), anims = st.anim || [];
    S.order.forEach(function (n) {
      var P = S.parts[n];
      P._p = P.pos0.clone().addScaledVector(P.ex, S.ex);
      P._q = P.quat0.clone();
      P.blink = 0;
    });
    for (var i = 0; i < anims.length; i++) {
      var a = anims[i], P = S.parts[a.part];
      var w = 'steps[' + S.step + '].anim[' + i + ']';
      if (a.type === 'crank_slider' || a.type === 'four_bar') { solveLinkage(a, w, dt); continue; }
      if (!P) continue;
      var piv = a.pivot ? b2t(a.pivot) : null;
      if (a.type === 'spin') {
        if (S.stepT > (+a.delay || 0)) a._ang = (a._ang || 0) + num(a.speed, w) * dt;
        rotateAbout(P._p, P._q, axisVec(a.axis), a._ang || 0, piv);
      } else if (a.type === 'turn') {
        rotateAbout(P._p, P._q, axisVec(a.axis), num(a.by, w) * prog(S.stepT, a), piv);
      } else if (a.type === 'move') {
        var by = a.by || [0, 0, 0];
        P._p.addScaledVector(b2t([num(by[0], w), num(by[1], w), num(by[2], w)]), prog(S.stepT, a));
      } else if (a.type === 'screw') {
        var d = axisVec(a.axis), u = prog(S.stepT, a), turns = num(a.turns, w), pitch = num(a.pitch, w);
        rotateAbout(P._p, P._q, d, 360 * turns * u, piv);
        P._p.addScaledVector(d, pitch * turns * u);
      } else if (a.type === 'blink') {
        P.blink = 0.5 + 0.5 * Math.sin(S.stepT * 2 * Math.PI / Math.max(0.2, +a.time || 1));
      }
    }
    try { if (QB.onFrame) QB.onFrame(api, S.stepT, dt); } catch (e) { err('custom.js onFrame 出错：' + e.message); }
    S.order.forEach(function (n) {
      var P = S.parts[n];
      P._p.add(P.cOff);
      P._q.premultiply(P.cQ);
      P.node.position.copy(P._p);
      P.node.quaternion.copy(P._q);
    });
    if (S.camGoal) {
      camera.position.lerp(S.camGoal.pos, k);
      controls.target.lerp(S.camGoal.target, k);
      if (camera.position.distanceTo(S.camGoal.pos) < asm.radius * 1e-3) S.camGoal = null;
    }
    controls.update();
    // 剖切
    if (S.sec) {
      var b = asm.box, ax = S.sec.axis, lo, hi;
      if (ax === 'x') { lo = b.min.x; hi = b.max.x; plane.normal.set(-1, 0, 0); }
      else if (ax === 'z') { lo = b.min.y; hi = b.max.y; plane.normal.set(0, -1, 0); }
      else { lo = -b.max.z; hi = -b.min.z; plane.normal.set(0, 0, 1); }
      plane.constant = lo + (hi - lo) * S.sec.pos;
      renderer.clippingPlanes = [plane];
    } else renderer.clippingPlanes = [];
    paint();
    updateLabels();
    updateReadouts();
  }

  // ---------- 标签、读数
  function buildLabels(list) {
    var box = $('labels');
    S.labels.forEach(function (l) { if (!l.custom) box.removeChild(l.el); });
    S.labels = S.labels.filter(function (l) { return l.custom; });
    list.forEach(function (l) { addLabel(l, false); });
  }
  function addLabel(l, custom) {
    var el = document.createElement('div');
    el.className = 'lbl'; el.textContent = l.text || (l.part && S.parts[l.part] ? S.parts[l.part].cn : '');
    $('labels').appendChild(el);
    var o = { el: el, part: l.part, at: l.at ? b2t(l.at) : null, custom: custom, id: l.id };
    S.labels.push(o);
    return o;
  }
  function updateLabels() {
    var st = $('stage'), w = st.clientWidth, h = st.clientHeight;
    S.labels.forEach(function (l) {
      var p;
      if (l.part && S.parts[l.part]) { var P = S.parts[l.part]; p = P.node.localToWorld(P.cLocal.clone()); if (!P.node.visible) { l.el.style.display = 'none'; return; } }
      else if (l.at) p = root.localToWorld(l.at.clone());
      else { l.el.style.display = 'none'; return; }
      p.project(camera);
      if (p.z > 1 || p.z < -1) { l.el.style.display = 'none'; return; }
      l.el.style.display = '';
      l.el.style.left = ((p.x + 1) / 2 * w).toFixed(1) + 'px';
      l.el.style.top = ((1 - p.y) / 2 * h).toFixed(1) + 'px';
    });
  }
  var roItems = [];
  function buildReadouts() {
    var box = $('readouts'); box.innerHTML = ''; roItems = [];
    (CFG.readouts || []).concat(cur().readouts || []).forEach(function (r, i) {
      var d = document.createElement('div'); d.className = 'ro';
      d.innerHTML = '<span>' + esc(r.label) + '</span><b></b>';
      box.appendChild(d);
      roItems.push({ r: r, el: d.querySelector('b'), last: null, w: 'readouts[' + i + ']' });
    });
    Object.keys(S.customRead).forEach(function (kk) {
      var d = document.createElement('div'); d.className = 'ro';
      d.innerHTML = '<span>' + esc(kk) + '</span><b></b>';
      box.appendChild(d);
      roItems.push({ key: kk, el: d.querySelector('b'), last: null });
    });
  }
  function updateReadouts() {
    roItems.forEach(function (it) {
      var txt;
      if (it.key) txt = String(S.customRead[it.key]);
      else {
        var dg = it.r.digits != null ? +it.r.digits : 1;
        txt = num(it.r.expr, it.w).toFixed(dg) + (it.r.unit ? ' ' + it.r.unit : '');
      }
      if (txt !== it.last) { it.el.textContent = txt; it.last = txt; }
    });
  }

  // ---------- 剖切、选中
  function setSection(axis, pos) {
    axis = (axis || '').toLowerCase();
    S.sec = 'xyz'.indexOf(axis) >= 0 && axis ? { axis: axis, pos: clamp01(pos == null ? 0.5 : pos) } : null;
    Array.prototype.forEach.call($('secaxis').children, function (b) { b.className = (b.dataset.a === (S.sec ? S.sec.axis : '')) ? 'on' : ''; });
    $('secpos').value = S.sec ? S.sec.pos : 0.5;
    $('secpos').disabled = !S.sec;
  }
  function showCard(name) {
    var c = $('card'), P = name && S.parts[name];
    Array.prototype.forEach.call($('partlist').children, function (li) { li.className = li.dataset.n === name ? 'on' : ''; });
    if (!P) { c.style.display = 'none'; return; }
    c.innerHTML = '<button class="x" aria-label="关闭">×</button><b>' + esc(P.cn) + '</b><small>' + esc(P.name) + '</small>' +
      (P.info ? '<div>' + rich(P.info) + '</div>' : '');
    c.style.display = 'block';
    c.querySelector('.x').onclick = function () { select(null); };
  }
  function select(name) { S.sel = name && S.parts[name] ? name : null; showCard(S.sel); }

  // ---------- 界面
  function buildUI() {
    var tabs = $('tabs');
    function tab(name) {
      Array.prototype.forEach.call(tabs.children, function (b) { b.setAttribute('aria-selected', b.dataset.tab === name ? 'true' : 'false'); });
      ['steps', 'parts', 'explode', 'section'].forEach(function (n) { $('tab-' + n).className = 'tab' + (n === name ? ' on' : ''); });
      S.tab = name;
    }
    S.setTab = tab;
    Array.prototype.forEach.call(tabs.children, function (b) { b.onclick = function () { tab(b.dataset.tab); }; });
    if (!steps().length) { tabs.querySelector('[data-tab=steps]').style.display = 'none'; tab('parts'); } else tab('steps');
    if (S.order.length < 2) tabs.querySelector('[data-tab=explode]').style.display = 'none';
    $('prev').onclick = function () { goStep(S.step - 1); };
    $('next').onclick = function () { goStep(S.step + 1); };
    var dots = $('dots');
    steps().forEach(function (s, i) {
      var d = document.createElement('button'); d.setAttribute('aria-label', '第 ' + (i + 1) + ' 步');
      d.onclick = function () { goStep(i); }; dots.appendChild(d);
    });
    var pl = $('partlist');
    S.order.forEach(function (n) {
      var P = S.parts[n], li = document.createElement('li');
      li.dataset.n = n; li.tabIndex = 0;
      li.innerHTML = esc(P.cn) + '<small>' + esc(n) + '</small>' + (P.info ? '<p>' + rich(P.info) + '</p>' : '');
      li.onclick = function () { select(S.sel === n ? null : n); };
      li.onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); li.onclick(); } };
      pl.appendChild(li);
    });
    $('ex').oninput = function () { S.exTarget = +this.value; refit(); };
    Array.prototype.forEach.call($('secaxis').children, function (b) {
      b.onclick = function () { setSection(b.dataset.a, +$('secpos').value); };
    });
    $('secpos').oninput = function () { if (S.sec) S.sec.pos = +this.value; };
    var pb = $('params');
    (CFG.params || []).forEach(function (p) {
      var row = document.createElement('label'); row.className = 'param';
      var dg = (String(p.step || 1).split('.')[1] || '').length;
      row.innerHTML = '<span>' + esc(p.label || p.id) + '</span><input type="range" min="' + (+p.min || 0) + '" max="' + (+p.max || 100) +
        '" step="' + (+p.step || 1) + '" value="' + (+p.value || 0) + '"><output></output>';
      var inp = row.querySelector('input'), out = row.querySelector('output');
      function show() { out.textContent = (+inp.value).toFixed(dg) + (p.unit ? ' ' + p.unit : ''); }
      inp.oninput = function () { S.params[p.id] = +inp.value; show(); };
      p._inp = inp; p._show = show; p._row = row; show(); pb.appendChild(row);
    });
    // 点选零件
    var cv = $('c'), down = null, ray = new T.Raycaster();
    cv.addEventListener('pointerdown', function (e) { down = [e.clientX, e.clientY]; });
    cv.addEventListener('pointerup', function (e) {
      if (!down || Math.abs(e.clientX - down[0]) + Math.abs(e.clientY - down[1]) > 6) return;
      var r = cv.getBoundingClientRect();
      ray.setFromCamera(new T.Vector2((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      var list = [];
      S.order.forEach(function (n) { var P = S.parts[n]; if (P.node.visible && P.look !== 'ghost') list = list.concat(P.meshes); });
      var hit = ray.intersectObjects(list, false).filter(function (h) {
        return !S.sec || plane.distanceToPoint(h.point) >= 0;
      })[0];
      select(hit ? hit.object.userData.part : null);
    });
    window.addEventListener('keydown', function (e) {
      if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === 'ArrowRight') goStep(S.step + 1);
      if (e.key === 'ArrowLeft') goStep(S.step - 1);
    });
  }

  // ---------- 给 custom.js 用的接口（坐标都是建模坐标：毫米，Z 朝上）
  function handle(name) {
    var P = S.parts[name];
    if (!P) { err('custom.js 用了不存在的零件名：' + name); return null; }
    return {
      name: name, node: P.node,
      move: function (x, y, z) { P.cOff.copy(b2t([x, y, z])); return this; },
      turn: function (axis, deg) { P.cQ.setFromAxisAngle(axisVec(axis), deg * Math.PI / 180); return this; },
      color: function (hex) { P.cColor = hex ? new T.Color(hex) : null; return this; },
      opacity: function (a) { P.cOpacity = a == null ? null : +a; return this; },
      show: function (b) { P.cShow = b == null ? null : !!b; return this; },
      center: function () { return t2b(root.worldToLocal(P.node.localToWorld(P.cLocal.clone()))); }
    };
  }
  var api = {
    THREE: T, get scene() { return scene; }, get camera() { return camera; }, get root() { return root; },
    part: handle, parts: function () { return S.order.slice(); },
    param: function (id) { if (!(id in S.params)) err('custom.js 用了不存在的参数：' + id); return S.params[id] || 0; },
    setParam: function (id, v) {
      S.params[id] = +v;
      (CFG.params || []).forEach(function (p) { if (p.id === id && p._inp) { p._inp.value = v; p._show(); } });
    },
    step: function () { return S.step; }, time: function () { return S.stepT; },
    vec: function (x, y, z) { return b2t([x, y, z]); },
    readout: function (label, text) { var isNew = !(label in S.customRead); S.customRead[label] = text; if (isNew) buildReadouts(); },
    panel: function () { return $('custom'); },
    label: function (id, at, text) {
      var l = S.labels.filter(function (x) { return x.custom && x.id === id; })[0];
      if (!l) l = addLabel({ id: id, at: at, text: text }, true);
      l.at = at ? b2t(at) : null; l.el.textContent = text;
    },
    arrow: function (id, from, to, color) {
      var a = S.arrows[id], f = b2t(from), d = b2t(to).sub(f), len = d.length();
      if (!a) { a = S.arrows[id] = new T.ArrowHelper(new T.Vector3(0, 1, 0), f, 1, color || 0xd9730d); root.add(a); }
      a.visible = len > 1e-6;
      if (!a.visible) return;
      a.position.copy(f); a.setDirection(d.normalize());
      a.setLength(len, Math.min(len * 0.3, asm.radius / MM * 0.12), Math.min(len * 0.15, asm.radius / MM * 0.05));
      if (color) a.setColor(new T.Color(color));
    },
    hideArrow: function (id) { if (S.arrows[id]) S.arrows[id].visible = false; },
    error: err
  };

  // ---------- 自检（check_page 会调用）
  function finiteAll() {
    var bad = [];
    S.order.forEach(function (n) {
      var e = S.parts[n].node.matrix.elements;
      for (var i = 0; i < 16; i++) if (!isFinite(e[i])) { bad.push(n); break; }
    });
    var c = camera.position;
    if (!isFinite(c.x + c.y + c.z)) bad.push('相机');
    return bad;
  }
  function coverage() {
    renderer.render(scene, camera);
    var gl = renderer.getContext(), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    var px = new Uint8Array(4), hit = 0, tot = 0;
    for (var y = 0; y < 24; y++) for (var x = 0; x < 24; x++) {
      gl.readPixels(Math.floor((x + 0.5) / 24 * w), Math.floor((y + 0.5) / 24 * h), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
      tot++; if (px[3] > 8) hit++;
    }
    return hit / tot;
  }
  function tick(dt) { update(dt); scene.updateMatrixWorld(true); renderer.render(scene, camera); }
  function selftest() {
    var out = { steps: steps().length, parts: S.order.length, moved: {}, coverage: [] };
    S.manual = true;
    try {
      for (var i = 0; i < Math.max(1, steps().length); i++) {
        if (steps().length) goStep(i, true);
        var before = {};
        update(0); scene.updateMatrixWorld(true);
        S.order.forEach(function (n) { before[n] = S.parts[n].node.matrix.clone(); });
        for (var f = 0; f < 50; f++) update(0.05);
        scene.updateMatrixWorld(true);
        var bad = finiteAll();
        if (bad.length) err('第 ' + (i + 1) + ' 步里这些东西的位置算成了 NaN：' + bad.join('、'));
        var st = cur(), mv = [];
        (st.anim || []).forEach(function (a) {
          if (a.type === 'crank_slider' || a.type === 'four_bar') {
            names(a.crank).concat(names(a.slider), names(a.rocker)).forEach(function (nm) {
              if (!S.parts[nm] || a.angle != null) return;
              var m1 = S.parts[nm].node.matrix.elements, m0 = before[nm].elements, same = true;
              for (var k = 0; k < 16; k++) if (Math.abs(m1[k] - m0[k]) > 1e-9) same = false;
              if (same) mv.push(nm);
            });
            return;
          }
          if (a.type === 'blink' || !S.parts[a.part]) return;
          var same = true, e1 = S.parts[a.part].node.matrix.elements, e0 = before[a.part].elements;
          for (var k = 0; k < 16; k++) if (Math.abs(e1[k] - e0[k]) > 1e-9) same = false;
          if (same) mv.push(a.part);
        });
        if (mv.length) out.moved[i] = mv;
        if (S.camGoal) { camera.position.copy(S.camGoal.pos); controls.target.copy(S.camGoal.target); controls.update(); S.camGoal = null; }
        out.coverage.push(+coverage().toFixed(3));
      }
      S.exTarget = S.ex = 1; refit(); update(0.05); scene.updateMatrixWorld(true);
      if (finiteAll().length) err('爆炸图位置算成了 NaN');
      setSection('x', 0.5); update(0.05); setSection('', 0.5);
      if (steps().length) goStep(0, true);
      tick(0.05);
    } catch (e) { err('自检过程出错：' + e.message); }
    S.manual = false;
    out.errors = S.errors.slice();
    out.overflowX = document.documentElement.scrollWidth > window.innerWidth + 1;
    out.ok = out.errors.length === 0;
    return out;
  }

  window.QBV = { start: start };
  window.__qb = {
    get ready() { return S.ready; }, get errors() { return S.errors; }, state: S,
    goStep: goStep, tick: tick, selftest: selftest, coverage: coverage, setView: setView,
    setExplode: function (e) { S.exTarget = S.ex = clamp01(e); $('ex').value = S.ex; refit(); if (S.camGoal) { camera.position.copy(S.camGoal.pos); controls.target.copy(S.camGoal.target); S.camGoal = null; } },
    setSection: setSection, setTab: function (t) { S.setTab(t); }, select: select, manual: function (b) { S.manual = !!b; }
  };
})();
