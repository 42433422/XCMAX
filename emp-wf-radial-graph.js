/** 兼容旧路径：转发到 docs/xcagi-dashboard/emp-wf-radial-graph.js */
(function () {
  if (window.EmpWfRadialGraph) return;
  var s = document.createElement('script');
  s.src = 'docs/xcagi-dashboard/emp-wf-radial-graph.js?v=20260606h';
  s.defer = true;
  document.head.appendChild(s);
})();
