/* ==========================================================================
 * XCAGI · Tree Web Worker
 * 从主线程剥离 30K 文件的索引/过滤/构建行操作
 * 通信协议：
 *   IN  : { type:'init', jsonUrl } | { type:'filter', filter, ext, expanded }
 *   OUT : { type:'ready', root, totalFiles, totalDirs, totalSize }
 *         { type:'chunk', rows, done, shown }
 *         { type:'error', message }
 * ========================================================================== */

const FILE_COUNT = { py: 0 };

self.addEventListener('message', async (e) => {
  const msg = e.data;
  try {
    if (msg.type === 'init') {
      await initAndIndex(msg.jsonUrl);
    } else if (msg.type === 'filter') {
      buildAndSend(msg.filter, msg.ext, msg.expanded);
    } else if (msg.type === 'stats') {
      sendStats();
    }
  } catch (err) {
    self.postMessage({ type: 'error', message: err && err.message ? err.message : String(err) });
  }
});

  let ROOT = null;
const PATH_MAP = new Map();
let TOTAL_FILES = 0;
let TOTAL_DIRS = 0;
let TOTAL_SIZE = 0;
let TOP_LINE_MAP = new Map();
let PATH_EMPLOYEE_MAP = new Map();

function applyTopLevelLines(coverage) {
  TOP_LINE_MAP = new Map();
  if (!coverage || !coverage.top_level) return;
  for (const entry of coverage.top_level) {
    if (entry.path && entry.lines && entry.lines.length) {
      TOP_LINE_MAP.set(entry.path, entry.lines);
    }
  }
}

function applyPathEmployeeIndex(pathEmployee) {
  PATH_EMPLOYEE_MAP = new Map();
  if (!pathEmployee || !pathEmployee.path_index) return;
  for (const [path, meta] of Object.entries(pathEmployee.path_index)) {
    PATH_EMPLOYEE_MAP.set(path, meta);
  }
}

function pathMetaForRow(path) {
  if (PATH_EMPLOYEE_MAP.has(path)) return PATH_EMPLOYEE_MAP.get(path);
  const parts = path.split('/');
  if (parts.length >= 2) {
    const parent = parts.slice(0, -1).join('/');
    if (PATH_EMPLOYEE_MAP.has(parent)) return PATH_EMPLOYEE_MAP.get(parent);
  }
  if (parts.length === 1 && TOP_LINE_MAP.has(path)) {
    return { lines: TOP_LINE_MAP.get(path), primary: [] };
  }
  return null;
}

async function initAndIndex(jsonUrl) {
  const t0 = (self.performance && self.performance.now) ? self.performance.now() : Date.now();
  const resp = await fetch(jsonUrl, { cache: 'no-store' });
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  const txt = await resp.text();
  ROOT = JSON.parse(txt);
  indexPaths(ROOT, '');
  applyTopLevelLines(ROOT.line_coverage);
  applyPathEmployeeIndex(ROOT.path_employee || (ROOT.line_coverage && ROOT.line_coverage.path_employee));
  const dt = (((self.performance && self.performance.now) ? self.performance.now() : Date.now()) - t0) / 1000;
  self.postMessage({
    type: 'ready',
    rootMeta: {
      childCount: Object.keys(ROOT.children || {}).length,
      totalFiles: TOTAL_FILES,
      totalDirs: TOTAL_DIRS,
      totalSize: TOTAL_SIZE,
      loadSeconds: +dt.toFixed(2),
      lineCoverage: ROOT.line_coverage || null,
      pathEmployee: ROOT.path_employee || (ROOT.line_coverage && ROOT.line_coverage.path_employee) || null,
    },
  });
}

function indexPaths(node, prefix) {
  for (const [name, child] of Object.entries(node.children)) {
    const p = prefix ? prefix + '/' + name : name;
    PATH_MAP.set(p, child);
    if (child.type === 'file') TOTAL_FILES++;
    else { TOTAL_DIRS++; indexPaths(child, p); }
  }
}

function allFilePaths(node, prefix, out) {
  for (const [name, child] of Object.entries(node.children)) {
    const p = prefix ? prefix + '/' + name : name;
    if (child.type === 'file') out.push(p);
    else allFilePaths(child, p, out);
  }
  return out;
}

function sendStats() {
  const files = [];
  allFilePaths(ROOT, '', files);
  self.postMessage({ type: 'stats', totalFiles: files.length, totalDirs: TOTAL_DIRS, totalSize: TOTAL_SIZE });
}

/* ---------- 过滤 + 展开 (主逻辑) ---------- */
function fileExt(name) {
  const n = name.toLowerCase();
  if (!n.includes('.')) return '';
  return '.' + n.split('.').pop();
}

function matchesFilter(name, path, filter, ext) {
  if (ext) {
    if (ext === '.yml') {
      if (!name.endsWith('.yml') && !name.endsWith('.yaml')) return false;
    } else if (ext === '.sh') {
      if (!name.endsWith('.sh') && !name.endsWith('.bat')) return false;
    } else if (!name.endsWith(ext)) {
      return false;
    }
  }
  if (filter) {
    const f = filter.toLowerCase();
    if (!path.toLowerCase().includes(f) && !name.toLowerCase().includes(f)) return false;
  }
  return true;
}

function dirHasMatch(node, path, filter, ext) {
  for (const [name, child] of Object.entries(node.children)) {
    const p = path ? path + '/' + name : name;
    if (child.type === 'file') {
      if (matchesFilter(name, p, filter, ext)) return true;
    } else if (dirHasMatch(child, p, filter, ext)) {
      return true;
    }
  }
  return false;
}

function buildRows(filter, ext, expanded) {
  const rows = [];
  const exp = new Set(expanded);
  function recurse(node, prefix, depth) {
    const entries = Object.entries(node.children).sort((a, b) => {
      if (a[1].type !== b[1].type) return a[1].type === 'dir' ? -1 : 1;
      return a[0].localeCompare(b[0]);
    });
    for (const [name, child] of entries) {
      const path = prefix ? prefix + '/' + name : name;
      const isDir = child.type === 'dir';
      if (isDir) {
        if ((filter || ext) && !dirHasMatch(child, path, filter, ext)) continue;
      } else if (!matchesFilter(name, path, filter, ext)) {
        continue;
      }
      const open = exp.has(path);
      const showChildren = isDir && (open || !!(filter || ext));
      const meta = pathMetaForRow(path);
      const lineTags = meta && meta.lines && meta.lines.length
        ? meta.lines
        : (depth === 0 ? (TOP_LINE_MAP.get(name) || null) : null);
      rows.push({
        name, path, isDir, depth,
        expanded: open,
        showChildren,
        child,
        lines: lineTags,
        primary: meta && meta.primary ? meta.primary : null,
        step: meta && meta.step ? meta.step : null,
      });
      if (showChildren && isDir) recurse(child, path, depth + 1);
    }
  }
  recurse(ROOT, '', 0);
  return rows;
}

/* ---------- 流式分块回传（避免 30K 行一次 postMessage 卡住） ---------- */
function buildAndSend(filter, ext, expanded) {
  if (!ROOT) return;
  const rows = buildRows(filter, ext, expanded);
  const CHUNK = 800;
  const total = rows.length;
  for (let i = 0; i < total; i += CHUNK) {
    const slice = rows.slice(i, i + CHUNK);
    self.postMessage({
      type: 'chunk',
      rows: slice,
      offset: i,
      shown: Math.min(i + CHUNK, total),
      done: i + CHUNK >= total,
    });
  }
}
