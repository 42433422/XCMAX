import { computed, onBeforeUnmount, onDeactivated, onMounted, ref, watch, type Ref } from 'vue';

type Row = Record<string, string | number | null | undefined>;
type Point = { x: number; y: number };
type Gesture = {
  id: string; pointer: number; touch: boolean; start: Point; point: Point;
  offset: number; context: string; slots: { id: string; middle: number }[];
};

/** Preview locally; the existing owner/revision-checked move endpoint owns persistence. */
export function useAttendanceRowReorder(options: {
  rows: Ref<Row[]>; root: Ref<HTMLElement | null>; viewport: Ref<HTMLElement | null>;
  enabled: Readonly<Ref<boolean>>; context: Readonly<Ref<string>>;
  move: (row: Row, position: number, preview: Row[]) => void;
}) {
  const draggingId = ref('');
  const overId = ref('');
  let gesture: Gesture | null = null;
  let timer = 0;
  let frame = 0;
  let ghost: HTMLTableElement | null = null;
  let captureTarget: HTMLElement | null = null;
  let suppressClickUntil = 0;
  const previewRows = computed(() => {
    const result = [...options.rows.value];
    const from = result.findIndex(row => String(row.id) === draggingId.value);
    const to = result.findIndex(row => String(row.id) === overId.value);
    if (from >= 0 && to >= 0) result.splice(to, 0, result.splice(from, 1)[0]);
    return result;
  });

  function cancel() {
    const pointer = gesture?.pointer;
    if (draggingId.value) suppressClickUntil = Date.now() + 400;
    window.clearTimeout(timer);
    window.cancelAnimationFrame(frame);
    timer = frame = 0;
    ghost?.remove();
    ghost = null;
    gesture = null;
    draggingId.value = overId.value = '';
    if (pointer !== undefined && captureTarget?.hasPointerCapture?.(pointer)) captureTarget.releasePointerCapture(pointer);
    captureTarget = null;
  }

  function bounds() {
    const list = options.viewport.value?.getBoundingClientRect();
    const root = options.root.value?.getBoundingClientRect();
    if (!list || !root) return null;
    return { left: Math.max(0, list.left, root.left), right: Math.min(innerWidth, list.right, root.right),
      top: Math.max(0, list.top, root.top), bottom: Math.min(innerHeight, list.bottom, root.bottom) };
  }

  function inside(point: Point) {
    const rect = bounds();
    return rect && point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
  }

  function updateTarget() {
    if (!gesture || !inside(gesture.point)) return;
    const body = options.viewport.value?.querySelector('tbody');
    if (!body) return;
    const y = gesture.point.y - body.getBoundingClientRect().top;
    // Keep hit slots tied to the original order, so the moving placeholder cannot oscillate.
    overId.value = gesture.slots.reduce((best, slot) =>
      Math.abs(slot.middle - y) < Math.abs(best.middle - y) ? slot : best).id;
  }

  function tick() {
    frame = 0;
    if (!gesture || !draggingId.value) return;
    if (!options.enabled.value || options.context.value !== gesture.context) { cancel(); return; }
    const rect = bounds();
    if (rect && inside(gesture.point)) {
      const edge = Math.min(48, (rect.bottom - rect.top) / 3);
      const speed = gesture.point.y < rect.top + edge ? -12 * (1 - (gesture.point.y - rect.top) / edge)
        : gesture.point.y > rect.bottom - edge ? 12 * (1 - (rect.bottom - gesture.point.y) / edge) : 0;
      for (let node = options.viewport.value; speed && node; node = node.parentElement) {
        const before = node.scrollTop;
        if (node.scrollHeight > node.clientHeight) node.scrollTop += speed;
        if (node.scrollTop !== before) break;
      }
      updateTarget();
    }
    if (ghost) ghost.style.transform = `translate(${gesture.point.x - gesture.start.x}px, ${gesture.point.y - gesture.start.y}px)`;
    frame = window.requestAnimationFrame(tick);
  }

  function begin(target: EventTarget | null, point: Point, pointer: number, touch: boolean) {
    if (!options.enabled.value || gesture || !(target instanceof Element) ||
      target.closest('input,button,a,select,textarea,[contenteditable="true"]')) return;
    const row = target.closest<HTMLTableRowElement>('tr[data-roster-id]');
    const body = row?.parentElement;
    if (!row || !body || !options.viewport.value?.contains(row)) return;
    const rect = row.getBoundingClientRect();
    const top = body.getBoundingClientRect().top;
    const slots = Array.from(body.querySelectorAll<HTMLTableRowElement>('tr[data-roster-id]')).map(item => {
      const box = item.getBoundingClientRect();
      return { id: item.dataset.rosterId!, middle: box.top + box.height / 2 - top };
    });
    if (slots.length < 2) return;
    gesture = { id: row.dataset.rosterId!, pointer, touch, start: point, point, offset: point.y - rect.top,
      context: options.context.value, slots };
    timer = window.setTimeout(() => {
      if (!gesture || !options.enabled.value || options.context.value !== gesture.context) { cancel(); return; }
      if (!gesture.touch) {
        captureTarget = options.viewport.value;
        try { captureTarget?.setPointerCapture?.(gesture.pointer); }
        catch { cancel(); return; }
      }
      const table = row.closest('table')!;
      ghost = table.cloneNode(false) as HTMLTableElement;
      ghost.classList.add('roster-drag-ghost');
      ghost.setAttribute('aria-hidden', 'true');
      const copy = row.cloneNode(true) as HTMLTableRowElement;
      copy.removeAttribute('data-roster-id');
      Array.from(copy.cells).forEach((cell, index) => { cell.style.width = `${row.cells[index].getBoundingClientRect().width}px`; });
      copy.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
      copy.querySelectorAll<HTMLElement>('input,button,a').forEach(node => { node.tabIndex = -1; });
      ghost.append(document.createElement('tbody'));
      ghost.tBodies[0].append(copy);
      Object.assign(ghost.style, { position: 'fixed', left: `${rect.left}px`, top: `${gesture.start.y - gesture.offset}px`,
        width: `${rect.width}px`, minWidth: '0', tableLayout: 'fixed', pointerEvents: 'none', zIndex: '1000' });
      document.body.append(ghost);
      window.getSelection()?.removeAllRanges();
      draggingId.value = overId.value = gesture.id;
      frame = window.requestAnimationFrame(tick);
    }, 500);
  }

  function movePoint(point: Point, event: Event) {
    if (!gesture) return;
    if (!draggingId.value && Math.hypot(point.x - gesture.start.x, point.y - gesture.start.y) > 8) { cancel(); return; }
    if (draggingId.value) {
      if (gesture.touch && !event.cancelable) { cancel(); return; }
      event.preventDefault();
    }
    gesture.point = point;
  }

  function finish(point: Point) {
    if (!gesture) return;
    gesture.point = point;
    updateTarget(); // Include the final pointer coordinate even before the next animation frame.
    const row = options.rows.value.find(item => String(item.id) === gesture!.id);
    const target = options.rows.value.find(item => String(item.id) === overId.value);
    const preview = previewRows.value;
    const commit = draggingId.value && inside(point) && options.enabled.value &&
      options.context.value === gesture.context && row && target && row.id !== target.id &&
      Number.isInteger(Number(target.order_position)) && Number(target.order_position) > 0;
    cancel();
    if (commit && row && target) options.move(row, Number(target.order_position), preview);
  }

  function pointerDown(event: PointerEvent) {
    if (event.pointerType === 'touch') return;
    if (gesture) { if (event.pointerId !== gesture.pointer) cancel(); return; }
    if (event.button === 0 && event.isPrimary !== false) begin(event.target, { x: event.clientX, y: event.clientY }, event.pointerId, false);
  }
  function pointerMove(event: PointerEvent) {
    if (gesture && !gesture.touch && event.pointerType === 'mouse' && event.buttons === 0) { cancel(); return; }
    if (gesture && !gesture.touch && event.pointerId === gesture.pointer) movePoint({ x: event.clientX, y: event.clientY }, event);
  }
  function pointerUp(event: PointerEvent) {
    if (gesture && !gesture.touch && event.pointerId === gesture.pointer) finish({ x: event.clientX, y: event.clientY });
  }
  function pointerCancel(event: PointerEvent) {
    if (gesture && !gesture.touch && event.pointerId === gesture.pointer) cancel();
  }
  function touchStart(event: TouchEvent) {
    if (event.touches.length !== 1) { cancel(); return; }
    const touch = event.touches[0];
    begin(event.target, { x: touch.clientX, y: touch.clientY }, touch.identifier, true);
  }
  function touchMove(event: TouchEvent) {
    if (!gesture?.touch) return;
    const touch = Array.from(event.touches).find(item => item.identifier === gesture!.pointer);
    if (!touch || event.touches.length !== 1) { cancel(); return; }
    movePoint({ x: touch.clientX, y: touch.clientY }, event);
  }
  function touchEnd(event: TouchEvent) {
    if (!gesture?.touch) return;
    const touch = Array.from(event.changedTouches).find(item => item.identifier === gesture!.pointer);
    if (touch) finish({ x: touch.clientX, y: touch.clientY });
  }
  function scroll() { if (gesture && !draggingId.value) cancel(); }
  function keyDown(event: KeyboardEvent) { if (event.key === 'Escape') cancel(); }
  function contextMenu(event: Event) { if (gesture) event.preventDefault(); }
  function click(event: Event) {
    if (Date.now() < suppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); }
  }
  const listeners: [string, EventListener, boolean | AddEventListenerOptions][] = [
    ['pointerdown', ((event: PointerEvent) => { if (gesture && event.pointerId !== gesture.pointer) cancel(); }) as EventListener, true],
    ['pointermove', pointerMove as EventListener, true], ['pointerup', pointerUp as EventListener, true],
    ['pointercancel', pointerCancel as EventListener, true], ['touchmove', touchMove as EventListener, { capture: true, passive: false }],
    ['lostpointercapture', pointerCancel as EventListener, true],
    ['touchend', touchEnd as EventListener, true], ['touchcancel', cancel, true],
    ['touchstart', ((event: TouchEvent) => { if (event.touches.length > 1) cancel(); }) as EventListener, true],
    ['scroll', scroll, true], ['wheel', cancel, true], ['keydown', keyDown as EventListener, true],
    ['blur', cancel, false], ['resize', cancel, false], ['contextmenu', contextMenu, true], ['click', click, true],
    ['visibilitychange', (() => { if (document.hidden) cancel(); }), true],
  ];
  watch([options.enabled, options.context, options.rows], cancel, { flush: 'sync' });
  onMounted(() => {
    listeners.forEach(([name, handler, settings]) => window.addEventListener(name, handler, settings));
  });
  // The viewport is conditional while a page loads; attach to its current instance.
  watch(options.viewport, (next, previous) => {
    previous?.removeEventListener('touchstart', touchStart);
    next?.addEventListener('touchstart', touchStart, { passive: true });
  }, { flush: 'post' });
  onDeactivated(cancel);
  onBeforeUnmount(() => {
    cancel();
    options.viewport.value?.removeEventListener('touchstart', touchStart);
    listeners.forEach(([name, handler, settings]) => window.removeEventListener(name, handler, settings));
  });
  return { draggingId, previewRows, pointerDown, cancel };
}
