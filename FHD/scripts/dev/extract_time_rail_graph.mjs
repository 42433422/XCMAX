#!/usr/bin/env node
/**
 * 从 docs/xcagi-dashboard/emp-wf-radial-graph.js 提取 NODES / FLOW_EDGES → JSON。
 * 供 sync_time_rail_workflow_graph.py 与 CI 校验调用。
 */
import fs from 'fs';
import vm from 'vm';

const jsPath = process.argv[2];
if (!jsPath) {
  console.error('usage: node extract_time_rail_graph.mjs <emp-wf-radial-graph.js>');
  process.exit(1);
}

const src = fs.readFileSync(jsPath, 'utf8');

function extractConstArray(name) {
  const marker = `const ${name} = [`;
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`Missing ${name}`);
  let i = start + marker.length - 1;
  let depth = 0;
  let inStr = null;
  let escape = false;
  for (; i < src.length; i++) {
    const c = src[i];
    if (inStr) {
      if (escape) {
        escape = false;
        continue;
      }
      if (c === '\\') {
        escape = true;
        continue;
      }
      if (c === inStr) inStr = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      inStr = c;
      continue;
    }
    if (c === '[') depth++;
    if (c === ']') {
      depth--;
      if (depth === 0) return src.slice(start + marker.length - 1, i + 1);
    }
  }
  throw new Error(`Unclosed array ${name}`);
}

function extractSet(name) {
  const marker = `const ${name} = new Set([`;
  const start = src.indexOf(marker);
  if (start < 0) return [];
  const end = src.indexOf(']);', start);
  if (end < 0) return [];
  const inner = src.slice(start + marker.length, end);
  const items = [];
  for (const m of inner.matchAll(/'([^']*)'/g)) items.push(m[1]);
  return items;
}

function extractObject(name) {
  const marker = `const ${name} = {`;
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`Missing ${name}`);
  let i = start + marker.length - 1;
  let depth = 0;
  let inStr = null;
  let escape = false;
  for (; i < src.length; i++) {
    const c = src[i];
    if (inStr) {
      if (escape) {
        escape = false;
        continue;
      }
      if (c === '\\') {
        escape = true;
        continue;
      }
      if (c === inStr) inStr = null;
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      inStr = c;
      continue;
    }
    if (c === '{') depth++;
    if (c === '}') {
      depth--;
      if (depth === 0) return src.slice(start + marker.length - 1, i + 1);
    }
  }
  throw new Error(`Unclosed object ${name}`);
}

const sotMatch = /SOT_VERSION\s*=\s*[\s\S]*?'([^']+)'/.exec(src);
const centerMatch = /const CENTER_ID = '([^']+)'/.exec(src);

const sandbox = {
  CENTER_ID: centerMatch ? centerMatch[1] : 'daily-hub',
};
const nodes = vm.runInNewContext(extractConstArray('NODES'), sandbox);
const edgesRaw = vm.runInNewContext(extractConstArray('FLOW_EDGES'), sandbox);

const edges = edgesRaw.map((row) => {
  const edge = { from: row[0], to: row[1] };
  if (row[2] === true) edge.optional = true;
  return edge;
});

const out = {
  version: sotMatch ? sotMatch[1] : 'unknown',
  center_id: centerMatch ? centerMatch[1] : 'daily-hub',
  phase_colors: vm.runInNewContext('(' + extractObject('PHASE_COLORS') + ')', sandbox),
  compact_ids: extractSet('COMPACT_IDS'),
  xrail_edge_keys: extractSet('XRAIL_EDGE_KEYS'),
  nodes: nodes.map((n) => {
    const row = { id: n.id, label: n.label, kind: n.kind || 'step' };
    if (n.phase) row.phase = n.phase;
    if (n.desc) row.desc = n.desc;
    return row;
  }),
  edges,
};

process.stdout.write(JSON.stringify(out, null, 2) + '\n');
