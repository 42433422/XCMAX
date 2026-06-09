/** 兼容旧路径：转发到 docs/xcagi-dashboard/emp-wf-radial-graph.js */
/* SOT_VERSION 与 docs/xcagi-dashboard/emp-wf-radial-graph.js 内 SOT_VERSION 保持一致 */
(function () {
  if (window.EmpWfRadialGraph) return;
  var s = document.createElement('script');
  s.src = 'docs/xcagi-dashboard/emp-wf-radial-graph.js?v=20260608';
  s.defer = true;
  document.head.appendChild(s);
})();
