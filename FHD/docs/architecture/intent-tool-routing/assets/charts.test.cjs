const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const echarts = require('../_shared/js/echarts.min.js');

function captureChart() {
  const captured = {};
  function element(name) {
    return {
      nodeType: 1,
      nodeName: name.toUpperCase(),
      childNodes: [],
      appendChild(child) { this.childNodes.push(child); },
      set innerHTML(value) { throw new Error('HTML assignment: ' + value); }
    };
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'charts.js'), 'utf8'), {
    document: {
      documentElement: {},
      getElementById(id) { assert.equal(id, 'chart-holdout'); return {}; },
      createElement: element,
      createTextNode(text) { return { nodeType: 3, textContent: String(text) }; }
    },
    getComputedStyle() { return { getPropertyValue() { return '#345678'; } }; },
    echarts: {
      init(host, theme, options) {
        captured.init = options;
        return {
          setOption(option) { captured.option = option; },
          resize() { captured.resized = true; }
        };
      }
    },
    window: { addEventListener(event, handler) {
      assert.equal(event, 'resize'); captured.resize = handler;
    } }
  });
  return captured;
}

test('static chart retains SVG rendering, all rows, labels and resize', () => {
  const chart = captureChart();
  assert.equal(chart.init.renderer, 'svg');
  assert.equal(chart.option.series[0].type, 'bar');
  assert.equal(chart.option.yAxis.data.length, 14);
  assert.equal(chart.option.yAxis.data[0], '域外（out_of_scope）');
  assert.equal(chart.option.yAxis.data[13], '销售');
  assert.equal(chart.option.series[0].data[0], 100);
  assert.equal(chart.option.series[0].data[13], 40);
  assert.equal(chart.option.series[0].markLine.data[0].xAxis, 65.49);
  assert.equal(chart.option.series[0].label.formatter({ value: 63.6 }), '63.6%');
  chart.resize();
  assert.equal(chart.resized, true);
  const rendered = echarts.init(null, null, {
    renderer: 'svg', ssr: true, width: 700, height: 500
  });
  try {
    rendered.setOption(chart.option);
    const svg = rendered.renderToSVGString();
    assert.ok(svg.includes('<svg'));
    assert.ok(svg.includes('out_of_scope'));
    assert.ok(svg.includes('65.5%'));
    assert.ok(svg.includes('63.6%'));
  } finally {
    rendered.dispose();
  }
});

test('tooltip preserves literal hostile labels without any HTML assignment', () => {
  const chart = captureChart();
  const label = '<img src=x onerror=alert(1)><svg onload=alert(2)>';
  const content = chart.option.tooltip.formatter([{ name: label, value: 63.6 }]);
  assert.equal(content.nodeType, 1);
  assert.equal(content.childNodes.length, 3);
  assert.equal(content.childNodes[0].nodeType, 3);
  assert.equal(content.childNodes[0].textContent, label);
  assert.equal(content.childNodes[1].nodeName, 'BR');
  assert.equal(content.childNodes[2].textContent, '63.6%');
});

test('modern vendor GeoJSON parsing uses JSON, never JavaScript expressions', () => {
  assert.doesNotThrow(() => echarts.registerMap('security-empty',
    '{"type":"FeatureCollection","features":[]}'));
  assert.throws(() => echarts.registerMap('security-expression',
    '({type:"FeatureCollection",features:[]})'), SyntaxError);
});
