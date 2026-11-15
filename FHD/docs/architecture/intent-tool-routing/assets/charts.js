// 留出集分域准确率图表
(function () {
  var host = document.getElementById('chart-holdout');
  if (!host || typeof echarts === 'undefined') return;

  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg = style.getPropertyValue('--bg').trim();

  var rows = [
    { name: '域外（out_of_scope）', value: 100.0 },
    { name: '库存', value: 100.0 },
    { name: '微信', value: 100.0 },
    { name: '拒绝', value: 90.9 },
    { name: '打印', value: 90.0 },
    { name: '产品', value: 90.0 },
    { name: '销售', value: 90.0 },
    { name: '客户', value: 80.0 },
    { name: '发货', value: 80.0 },
    { name: '报表', value: 80.0 },
    { name: '系统', value: 80.0 },
    { name: '数据', value: 70.0 },
    { name: '问候', value: 70.0 },
    { name: '财务', value: 70.0 }
  ];

  var chart = echarts.init(host, null, { renderer: 'svg' });
  chart.setOption({
    animation: false,
    backgroundColor: 'transparent',
    grid: { left: 8, right: 46, top: 18, bottom: 34, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      appendToBody: true,
      backgroundColor: bg,
      borderColor: rule,
      textStyle: { color: ink, fontSize: 12 },
      formatter: function (params) {
        var p = params[0];
        return p.name + '<br>' + p.value.toFixed(1) + '%';
      }
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 20,
      axisLabel: { color: muted, fontSize: 11, formatter: '{value}%' },
      axisLine: { lineStyle: { color: rule } },
      splitLine: { lineStyle: { color: rule } }
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map(function (r) { return r.name; }),
      axisLabel: { color: ink, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } },
      axisTick: { show: false }
    },
    series: [{
      type: 'bar',
      data: rows.map(function (r) { return r.value; }),
      barWidth: '54%',
      itemStyle: { color: accent, borderRadius: [0, 3, 3, 0] },
      label: {
        show: true,
        position: 'right',
        color: muted,
        fontSize: 11,
        formatter: function (p) { return p.value.toFixed(1) + '%'; }
      },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: accent2, type: 'dashed', width: 1.2 },
        label: {
          formatter: '总体 86.6%',
          color: accent2,
          fontSize: 11,
          position: 'insideEndTop'
        },
        data: [{ xAxis: 86.6 }]
      }
    }]
  });

  window.addEventListener('resize', function () { chart.resize(); });
})();
