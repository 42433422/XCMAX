/**
 * 架构图平移缩放（时间轨辐射图 / 事件轨合并架构等共用）
 * 滚轮缩放 · Space/Shift/中键/空白左键拖平移 · 双击空白复位
 */
const EmpWfPanZoom = (() => {
  const MIN = 0.22;
  const MAX = 2.8;
  const STEP = 1.09;

  function bind(host, viewport, stage) {
    if (!host || !viewport || !stage) return;
    host.classList.add('emp-wf-pan-zoom-host');

    let hud = host.querySelector('.emp-wf-pan-zoom-hud');
    if (!hud) {
      hud = document.createElement('div');
      hud.className = 'emp-wf-pan-zoom-hud';
      hud.setAttribute('aria-hidden', 'true');
      host.appendChild(hud);
    }

    if (host.__empWfPanZoom) {
      host.__empWfPanZoom.attach(viewport, stage);
      requestAnimationFrame(() => host.__empWfPanZoom.reset());
      return;
    }

    const state = {
      viewport,
      stage,
      scale: 1,
      tx: 0,
      ty: 0,
      dragging: false,
      panBtn: -1,
      lastX: 0,
      lastY: 0,
      moved: 0,
      spaceHeld: false,
    };

    function applyTransform() {
      const vp = state.viewport;
      if (!vp) return;
      vp.style.transform = 'translate(' + state.tx + 'px,' + state.ty + 'px) scale(' + state.scale + ')';
      vp.style.transformOrigin = '0 0';
      hud.textContent = '滚轮缩放 · Space/Shift/中键/左键拖平移 · ' + Math.round(state.scale * 100) + '%';
    }

    function fitInitial() {
      const st = state.stage;
      if (!st) return;
      const hw = host.clientWidth || 0;
      const sw = st.offsetWidth || 0;
      const sh = st.offsetHeight || 0;
      if (hw > 0 && sw > 0) {
        state.scale = Math.min(1, Math.max(MIN, (hw - 32) / sw));
        state.tx = Math.max(8, (hw - sw * state.scale) * 0.5);
        state.ty = 8;
      } else {
        state.scale = 1;
        state.tx = 0;
        state.ty = 0;
      }
      if (sh * state.scale > (host.clientHeight || 480)) {
        state.ty = 8;
      }
      applyTransform();
    }

    function zoomAt(clientX, clientY, factor) {
      const rect = host.getBoundingClientRect();
      const mx = clientX - rect.left;
      const my = clientY - rect.top;
      const next = Math.min(MAX, Math.max(MIN, state.scale * factor));
      const wx = (mx - state.tx) / state.scale;
      const wy = (my - state.ty) / state.scale;
      state.scale = next;
      state.tx = mx - wx * state.scale;
      state.ty = my - wy * state.scale;
      applyTransform();
    }

    function shouldStartPan(e) {
      if (e.button === 1) return true;
      if (e.button !== 0) return false;
      if (state.spaceHeld || e.shiftKey || e.altKey) return true;
      if (e.target.closest('.emp-wf-radial-node, .arch-graph-node')) return false;
      return true;
    }

    function beginPan(e) {
      state.dragging = true;
      state.panBtn = e.button;
      state.lastX = e.clientX;
      state.lastY = e.clientY;
      state.moved = 0;
      host.classList.add('is-panning');
      document.body.classList.add('emp-wf-pan-active');
      if (typeof e.pointerId === 'number' && host.setPointerCapture) {
        try {
          host.setPointerCapture(e.pointerId);
        } catch (_err) {
          /* ignore */
        }
      }
    }

    function endPan(e) {
      if (!state.dragging) return;
      if (e && typeof e.buttons === 'number' && e.buttons !== 0) return;
      state.dragging = false;
      host.classList.remove('is-panning');
      document.body.classList.remove('emp-wf-pan-active');
      if (state.moved > 6) {
        host.dataset.panMoved = '1';
        setTimeout(() => {
          delete host.dataset.panMoved;
        }, 400);
      }
    }

    function onPointerDown(e) {
      if (!shouldStartPan(e)) return;
      if (e.button === 1 || state.spaceHeld || e.shiftKey || e.altKey) {
        e.preventDefault();
        e.stopPropagation();
      }
      beginPan(e);
    }

    function onPointerMove(e) {
      if (!state.dragging) return;
      e.preventDefault();
      const dx = e.clientX - state.lastX;
      const dy = e.clientY - state.lastY;
      state.moved += Math.abs(dx) + Math.abs(dy);
      state.tx += dx;
      state.ty += dy;
      state.lastX = e.clientX;
      state.lastY = e.clientY;
      applyTransform();
    }

    host.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? STEP : 1 / STEP);
      },
      { passive: false },
    );

    host.addEventListener('pointerdown', onPointerDown, true);
    host.addEventListener('pointermove', onPointerMove);
    host.addEventListener('pointerup', endPan);
    host.addEventListener('pointercancel', endPan);
    window.addEventListener('blur', () => endPan());

    host.addEventListener(
      'auxclick',
      (e) => {
        if (e.button === 1) e.preventDefault();
      },
      true,
    );

    host.addEventListener(
      'dblclick',
      (e) => {
        if (e.target.closest('.emp-wf-radial-node, .arch-graph-node')) return;
        fitInitial();
      },
      true,
    );

    window.addEventListener('keydown', (e) => {
      if (e.code !== 'Space' || e.repeat) return;
      if (e.target && e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
      state.spaceHeld = true;
      host.classList.add('is-space-pan');
    });
    window.addEventListener('keyup', (e) => {
      if (e.code !== 'Space') return;
      state.spaceHeld = false;
      host.classList.remove('is-space-pan');
      endPan();
    });

    host.__empWfPanZoom = {
      attach(vp, st) {
        state.viewport = vp;
        state.stage = st;
      },
      reset: fitInitial,
    };
    requestAnimationFrame(fitInitial);
  }

  return { bind };
})();

window.EmpWfPanZoom = EmpWfPanZoom;
