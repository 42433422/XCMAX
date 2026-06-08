/**
 * 架构图共享绘制（时间轨 TB 径向 / 事件轨 LR）
 */
const ArchGraphDraw = (() => {
  const PHASE_COLORS = {
    trigger: '#79c0ff',
    route: '#d2a8ff',
    dispatch: '#56d364',
    cross: '#ffa657',
    merge: '#58e2c2',
    t0: '#79c0ff',
    t1: '#58e2c2',
    t2: '#d2a8ff',
    t2b: '#a371f7',
    t3: '#56d364',
    t4: '#ffa657',
  };

  let dagrePromise = null;
  const DAGRE_URLS = [
    'docs/xcagi-dashboard/vendor/dagre.min.js',
    'https://cdn.jsdelivr.net/npm/@dagrejs/dagre@1.1.4/dist/dagre.min.js',
  ];

  const LANE_SPACING = 16;
  const ARROW_TRIM = 10;

  function loadDagre() {
    if (window.dagre && window.dagre.graphlib) return Promise.resolve(window.dagre);
    if (dagrePromise) return dagrePromise;
    dagrePromise = new Promise((resolve, reject) => {
      let idx = 0;
      const tryNext = () => {
        if (idx >= DAGRE_URLS.length) {
          reject(new Error('dagre 布局库加载失败'));
          return;
        }
        const s = document.createElement('script');
        s.src = DAGRE_URLS[idx++];
        s.async = true;
        s.onload = () => {
          if (window.dagre && window.dagre.graphlib) resolve(window.dagre);
          else tryNext();
        };
        s.onerror = tryNext;
        document.head.appendChild(s);
      };
      tryNext();
    });
    return dagrePromise;
  }

  function nodeSize(n) {
    if (n.kind === 'decision') {
      const w = Math.min(196, Math.max(132, Math.ceil((n.label.split('\n')[0] || n.label).length * 6.8)));
      return { w, h: Math.round(w * 0.78) };
    }
    if (n.kind === 'phase') return { w: 272, h: 52 };
    if (n.phase === 'merge') return { w: 220, h: 72 };
    const lines = (n.label || '').split('\n');
    const w = Math.min(248, Math.max(172, Math.ceil(lines[0].length * 6.4)));
    return { w, h: lines.length > 1 ? 86 : 72 };
  }

  function computeLayout(dagreLib, nodes, edges, opts) {
    const g = new dagreLib.graphlib.Graph({ multigraph: true });
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: (opts && opts.rankdir) || 'LR',
      ranksep: (opts && opts.ranksep) || 56,
      nodesep: (opts && opts.nodesep) || 28,
      marginx: 32,
      marginy: 32,
    });
    for (const n of nodes) {
      const sz = nodeSize(n);
      g.setNode(n.id, { width: sz.w, height: sz.h });
    }
    for (const row of edges) {
      g.setEdge(row[0], row[1], {}, row[0] + '->' + row[1]);
    }
    dagreLib.layout(g);
    const positions = new Map();
    for (const n of nodes) {
      const pos = g.node(n.id);
      const sz = nodeSize(n);
      if (pos && Number.isFinite(pos.x)) {
        positions.set(n.id, { x: pos.x - sz.w / 2, y: pos.y - sz.h / 2, w: sz.w, h: sz.h });
      }
    }
    if (positions.size < 1) throw new Error('dagre 布局结果为空');
    return positions;
  }

  function appendArrowMarker(defs, id, fill) {
    const ns = 'http://www.w3.org/2000/svg';
    const marker = document.createElementNS(ns, 'marker');
    marker.setAttribute('id', id);
    marker.setAttribute('markerWidth', '12');
    marker.setAttribute('markerHeight', '12');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '6');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'userSpaceOnUse');
    const arrow = document.createElementNS(ns, 'path');
    arrow.setAttribute('d', 'M0,1 L11,6 L0,11 Z');
    arrow.setAttribute('fill', fill);
    marker.appendChild(arrow);
    defs.appendChild(marker);
  }

  function orthogonalPathTB(x1, y1, x2, y2, laneSrc, laneTgt) {
    const xs = x1 + (laneSrc || 0) * LANE_SPACING;
    const xt = x2 + (laneTgt || 0) * LANE_SPACING;
    const yEnd = y2 - ARROW_TRIM;
    if (Math.abs(xs - xt) < 4) return `M ${xs} ${y1} L ${xt} ${yEnd}`;
    const midY = y1 + Math.max(22, (yEnd - y1) * 0.42);
    return `M ${xs} ${y1} L ${xs} ${midY} L ${xt} ${midY} L ${xt} ${yEnd}`;
  }

  function lrPath(x1, y1, x2, y2) {
    const xEnd = x2 - 8;
    if (Math.abs(y1 - y2) < 6) return `M ${x1} ${y1} L ${xEnd} ${y2}`;
    const midX = x1 + Math.max(28, (xEnd - x1) * 0.45);
    return `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${xEnd} ${y2}`;
  }

  function edgeLaneMaps(edges) {
    const outCount = new Map();
    const inCount = new Map();
    for (const row of edges) {
      outCount.set(row[0], (outCount.get(row[0]) || 0) + 1);
      inCount.set(row[1], (inCount.get(row[1]) || 0) + 1);
    }
    const outIdx = new Map();
    const inIdx = new Map();
    const lanes = new Map();
    for (const row of edges) {
      const key = row[0] + '->' + row[1];
      const oi = outIdx.get(row[0]) || 0;
      outIdx.set(row[0], oi + 1);
      const ii = inIdx.get(row[1]) || 0;
      inIdx.set(row[1], ii + 1);
      const oTotal = outCount.get(row[0]) || 1;
      const iTotal = inCount.get(row[1]) || 1;
      lanes.set(key, {
        laneSrc: oTotal > 1 ? oi - (oTotal - 1) / 2 : 0,
        laneTgt: iTotal > 1 ? ii - (iTotal - 1) / 2 : 0,
      });
    }
    return lanes;
  }

  function edgeClassRadial(row, opts) {
    const key = row[0] + '->' + row[1];
    const hub = opts.hubKeys && opts.hubKeys.has(key);
    const pipe = opts.pipelineKeys && opts.pipelineKeys.has(key);
    if (row[2] === 'hub' || hub) return 'emp-wf-radial-edge emp-wf-radial-edge--hub';
    if (row[2] === 'pipe' || pipe) return 'emp-wf-radial-edge emp-wf-radial-edge--pipeline';
    if (row[2] === 'merge') return 'emp-wf-radial-edge emp-wf-radial-edge--hub';
    return 'emp-wf-radial-edge emp-wf-radial-edge--branch';
  }

  function markerIdRadial(row, opts) {
    const key = row[0] + '->' + row[1];
    if (row[2] === 'hub' || (opts.hubKeys && opts.hubKeys.has(key))) return 'emp-wf-arrow-hub';
    if (row[2] === 'pipe' || (opts.pipelineKeys && opts.pipelineKeys.has(key))) return 'emp-wf-arrow-pipeline';
    return 'emp-wf-arrow-branch';
  }

  function renderEdgesTB(svg, positions, edges, minX, minY, pad, opts) {
    const ns = 'http://www.w3.org/2000/svg';
    const lanes = edgeLaneMaps(edges);
    for (const row of edges) {
      const src = positions.get(row[0]);
      const tgt = positions.get(row[1]);
      if (!src || !tgt) continue;
      const x1 = src.x - minX + pad + src.w / 2;
      const y1 = src.y - minY + pad + src.h;
      const x2 = tgt.x - minX + pad + tgt.w / 2;
      const y2 = tgt.y - minY + pad;
      const key = row[0] + '->' + row[1];
      const lane = lanes.get(key) || { laneSrc: 0, laneTgt: 0 };
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', orthogonalPathTB(x1, y1, x2, y2, lane.laneSrc, lane.laneTgt));
      path.setAttribute('class', edgeClassRadial(row, opts));
      path.setAttribute('marker-end', 'url(#' + markerIdRadial(row, opts) + ')');
      svg.appendChild(path);
    }
  }

  function renderEdgesLR(svg, positions, edges, minX, minY, pad) {
    const ns = 'http://www.w3.org/2000/svg';
    for (const row of edges) {
      const src = positions.get(row[0]);
      const tgt = positions.get(row[1]);
      if (!src || !tgt) continue;
      const x1 = src.x - minX + pad + src.w;
      const y1 = src.y - minY + pad + src.h / 2;
      const x2 = tgt.x - minX + pad;
      const y2 = tgt.y - minY + pad + tgt.h / 2;
      const path = document.createElementNS(ns, 'path');
      const dashed = row[2] === 'merge';
      path.setAttribute('d', lrPath(x1, y1, x2, y2));
      path.setAttribute('class', 'arch-graph-edge' + (dashed ? ' arch-graph-edge--merge' : ''));
      path.setAttribute('marker-end', dashed ? 'url(#arch-arrow-merge)' : 'url(#arch-arrow-flow)');
      if (dashed) path.setAttribute('stroke-dasharray', '6 4');
      svg.appendChild(path);
    }
  }

  function radialNodeClasses(n) {
    if (n.kind === 'center') return ' emp-wf-radial-node--center';
    if (n.kind === 'decision') return ' emp-wf-radial-node--decision';
    if (n.kind === 'phase') return ' emp-wf-radial-node--phase';
    if (n.phase === 'merge') return ' emp-wf-radial-node--step arch-graph-node--merge';
    return ' emp-wf-radial-node--step';
  }

  function phaseClass(phase) {
    return phase ? ' emp-wf-radial-node--' + phase : '';
  }

  async function renderStage(root, spec, opts) {
    opts = opts || {};
    root.classList.add('is-loading');
    root.textContent = '正在布局架构图…';
    const useRadialTb = opts.edgeMode === 'radial-tb' || opts.rankdir === 'TB';
    try {
      const dagreLib = await loadDagre();
      const nodes = spec.nodes || [];
      const edges = (spec.edges || []).map((r) => [r[0], r[1], r[2]]);
      const positions = computeLayout(dagreLib, nodes, edges, opts);
      root.innerHTML = '';
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const p of positions.values()) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x + p.w);
        maxY = Math.max(maxY, p.y + p.h);
      }
      const pad = 48;
      const width = maxX - minX + pad * 2;
      const height = maxY - minY + pad * 2;
      const stage = document.createElement('div');
      stage.className = opts.stageClass || (useRadialTb ? 'emp-wf-radial-stage' : 'arch-graph-stage');
      stage.style.width = width + 'px';
      stage.style.height = height + 'px';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', useRadialTb ? 'emp-wf-radial-svg' : 'arch-graph-svg');
      svg.setAttribute('width', String(width));
      svg.setAttribute('height', String(height));
      const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      if (useRadialTb) {
        appendArrowMarker(defs, 'emp-wf-arrow-pipeline', '#56d364');
        appendArrowMarker(defs, 'emp-wf-arrow-branch', '#79c0ff');
        appendArrowMarker(defs, 'emp-wf-arrow-hub', '#58e2c2');
      } else {
        appendArrowMarker(defs, 'arch-arrow-flow', '#79c0ff');
        appendArrowMarker(defs, 'arch-arrow-merge', '#58e2c2');
      }
      svg.appendChild(defs);
      if (useRadialTb) {
        renderEdgesTB(svg, positions, edges, minX, minY, pad, opts);
      } else {
        renderEdgesLR(svg, positions, edges, minX, minY, pad);
      }
      stage.appendChild(svg);
      const layer = document.createElement('div');
      layer.className = useRadialTb ? 'emp-wf-radial-nodes' : 'arch-graph-nodes';
      const hi = opts.highlightIds;
      for (const n of nodes) {
        const p = positions.get(n.id);
        if (!p) continue;
        const el = document.createElement('div');
        el.className = 'emp-wf-radial-node' + radialNodeClasses(n) + phaseClass(n.phase) +
          (n.compact ? ' emp-wf-radial-node--compact' : '') +
          (hi && hi.has(n.id) ? ' arch-graph-node--live' : '');
        el.style.left = p.x - minX + pad + 'px';
        el.style.top = p.y - minY + pad + 'px';
        el.style.width = p.w + 'px';
        el.style.height = p.h + 'px';
        el.style.minHeight = p.h + 'px';
        el.style.whiteSpace = 'pre-line';
        if (n.phase && PHASE_COLORS[n.phase]) {
          el.style.setProperty('--phase-color', PHASE_COLORS[n.phase]);
        }
        el.textContent = n.label;
        el.title = n.label + '\n点击查看主责/协作员工';
        el.dataset.eventNode = n.id;
        el.dataset.empWfNode = n.staffNodeId || n.id;
        if (n.id === 'Vibe08') el.classList.add('event-merge-node');
        layer.appendChild(el);
      }
      stage.appendChild(layer);
      if (window.EmpWfNodeStaff && opts.bindStaff !== false) {
        window.EmpWfNodeStaff.bindRadial(layer);
      }
      if (opts.panZoom && window.EmpWfPanZoom && typeof window.EmpWfPanZoom.bind === 'function') {
        const viewport = document.createElement('div');
        viewport.className = 'emp-wf-radial-viewport';
        viewport.appendChild(stage);
        root.appendChild(viewport);
        window.EmpWfPanZoom.bind(root, viewport, stage);
      } else {
        root.appendChild(stage);
      }
      root.classList.remove('is-loading', 'is-error');
    } catch (err) {
      root.classList.add('is-error');
      root.classList.remove('is-loading');
      root.textContent = '架构图渲染失败：' + (err && err.message ? err.message : 'unknown');
      throw err;
    }
  }

  return { loadDagre, renderStage, PHASE_COLORS };
})();

window.ArchGraphDraw = ArchGraphDraw;
