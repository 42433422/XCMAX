// 留出集分域准确率图表：静态 SVG，不加载第三方图表库。
(function (root) {
  var ROWS = [
    { name: '域外（out_of_scope）', value: 100.0 },
    { name: '打印', value: 90.0 },
    { name: '微信', value: 90.0 },
    { name: '客户', value: 80.0 },
    { name: '库存', value: 80.0 },
    { name: '数据', value: 70.0 },
    { name: '问候', value: 70.0 },
    { name: '拒绝', value: 63.6 },
    { name: '发货', value: 50.0 },
    { name: '报表', value: 50.0 },
    { name: '系统', value: 50.0 },
    { name: '财务', value: 40.0 },
    { name: '产品', value: 40.0 },
    { name: '销售', value: 40.0 }
  ];
  var OVERALL = 65.49;

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function buildTooltip(name, value) {
    var content = document.createElement('div');
    content.appendChild(document.createTextNode(name));
    content.appendChild(document.createElement('br'));
    content.appendChild(document.createTextNode(value.toFixed(1) + '%'));
    return content;
  }

  function svgEl(name, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, String(attrs[key]));
    });
    return node;
  }

  function svgText(content, attrs) {
    var node = svgEl('text', attrs);
    node.appendChild(document.createTextNode(content));
    return node;
  }

  function ensureTooltip() {
    var tip = document.getElementById('chart-holdout-tooltip');
    if (tip) return tip;
    tip = document.createElement('div');
    tip.id = 'chart-holdout-tooltip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    tip.style.position = 'absolute';
    tip.style.zIndex = '20';
    tip.style.pointerEvents = 'none';
    tip.style.padding = '6px 8px';
    tip.style.fontSize = '12px';
    tip.style.border = '1px solid ' + token('--rule');
    tip.style.background = token('--bg');
    tip.style.color = token('--ink');
    document.body.appendChild(tip);
    return tip;
  }

  function hideTooltip(tip) {
    tip.hidden = true;
    tip.replaceChildren();
  }

  function showTooltip(tip, name, value, event) {
    tip.replaceChildren(buildTooltip(name, value));
    tip.hidden = false;
    tip.style.left = event.pageX + 12 + 'px';
    tip.style.top = event.pageY + 12 + 'px';
  }

  function render(host) {
    var width = Math.max(host.clientWidth || 700, 320);
    var height = Math.max(host.clientHeight || 440, 400);
    var margin = { top: 18, right: 54, bottom: 34, left: 8 };
    var labelWidth = 118;
    var plotLeft = margin.left + labelWidth;
    var plotTop = margin.top;
    var plotWidth = Math.max(width - plotLeft - margin.right, 80);
    var plotHeight = Math.max(height - plotTop - margin.bottom, 80);
    var barGap = plotHeight / ROWS.length;
    var barHeight = barGap * 0.54;
    var accent = token('--accent');
    var accent2 = token('--accent2');
    var ink = token('--ink');
    var muted = token('--muted');
    var rule = token('--rule');
    var tip = ensureTooltip();

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: '100%',
      height: String(height),
      role: 'img',
      'aria-label': '留出集分域准确率'
    });

    var x;
    for (x = 0; x <= 100; x += 20) {
      var px = plotLeft + (x / 100) * plotWidth;
      svg.appendChild(svgEl('line', {
        x1: px, y1: plotTop, x2: px, y2: plotTop + plotHeight,
        stroke: rule, 'stroke-width': 1
      }));
      svg.appendChild(svgText(x + '%', {
        x: px, y: plotTop + plotHeight + 18,
        fill: muted, 'font-size': 11, 'text-anchor': 'middle'
      }));
    }

    ROWS.forEach(function (row, index) {
      var y = plotTop + index * barGap + (barGap - barHeight) / 2;
      var barWidth = (row.value / 100) * plotWidth;
      svg.appendChild(svgText(row.name, {
        x: plotLeft - 8, y: y + barHeight / 2 + 4,
        fill: ink, 'font-size': 12, 'text-anchor': 'end'
      }));
      var bar = svgEl('rect', {
        x: plotLeft,
        y: y,
        width: Math.max(barWidth, 0),
        height: barHeight,
        fill: accent,
        rx: 3,
        ry: 3,
        'data-name': row.name,
        'data-value': String(row.value)
      });
      bar.addEventListener('pointerenter', function (event) {
        showTooltip(tip, row.name, row.value, event);
      });
      bar.addEventListener('pointermove', function (event) {
        showTooltip(tip, row.name, row.value, event);
      });
      bar.addEventListener('pointerleave', function () {
        hideTooltip(tip);
      });
      svg.appendChild(bar);
      svg.appendChild(svgText(row.value.toFixed(1) + '%', {
        x: plotLeft + barWidth + 6, y: y + barHeight / 2 + 4,
        fill: muted, 'font-size': 11, 'text-anchor': 'start'
      }));
    });

    var markX = plotLeft + (OVERALL / 100) * plotWidth;
    svg.appendChild(svgEl('line', {
      x1: markX, y1: plotTop, x2: markX, y2: plotTop + plotHeight,
      stroke: accent2, 'stroke-width': 1.2, 'stroke-dasharray': '4 3'
    }));
    svg.appendChild(svgText('总体 65.5%', {
      x: markX + 4, y: plotTop + 12,
      fill: accent2, 'font-size': 11, 'text-anchor': 'start'
    }));

    host.replaceChildren(svg);
    return svg;
  }

  function mount(host) {
    if (!host) return null;
    function draw() { return render(host); }
    window.addEventListener('resize', draw);
    return draw();
  }

  var api = {
    rows: ROWS,
    overall: OVERALL,
    buildTooltip: buildTooltip,
    render: render,
    mount: mount
  };
  root.HoldoutAccuracyChart = api;
  if (typeof document !== 'undefined') {
    mount(document.getElementById('chart-holdout'));
  }
})(typeof window !== 'undefined' ? window : globalThis);
