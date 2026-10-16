// Run with node --test scripts/download_releases.test.mjs; no browser or network.
import { readFileSync } from 'node:fs'
import { Script } from 'node:vm'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const html = readFileSync(new URL('../download-releases.html', import.meta.url), 'utf8')
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)]
  .map((match) => match[1]).filter((source) => source.trim())
function element() {
  return { children: [], textContent: '', className: '',
    set innerHTML(value) { this.markup = value; this.children = [] },
    appendChild(child) { this.children.push(child) },
    replaceChildren(...children) { this.children = children },
    setAttribute() {},
  }
}
async function render(stable) {
  const nodes = new Map()
  const document = { createElement: element,
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id) },
  }
  const fetch = async (url) => {
    if (stable instanceof Error) throw stable
    return { ok: true, headers: { get: () => 'application/json' },
      json: async () => url === '/download-release.json' ? stable : null }
  }
  for (const source of scripts) new Script(source).runInNewContext({ document, fetch })
  await new Promise(setImmediate)
  return (id) => nodes.get(id)
}
test('inline scripts parse and render a manifest on repeated page loads', async () => {
  assert.ok(scripts.length > 0)
  const release = { version: '1.2.3', date: '2026-10-16', notes: ['A change'] }
  for (let load = 0; load < 2; load++) {
    const node = await render({ release_history: [release] })
    assert.equal(node('summary-version').textContent, 'v1.2.3')
    assert.equal(node('summary-date').textContent, release.date)
    assert.equal(node('summary-status').textContent, '稳定版可下载')
    assert.equal(node('summary-changes').children[0].textContent, 'A change')
    assert.equal(node('release-list').children.length, 1)
  }
})
test('missing, empty and failed manifests show honest unavailable state', async () => {
  for (const manifest of [null, { release_history: [] }, new Error('offline')]) {
    const node = await render(manifest)
    assert.equal(node('summary-version').textContent, '—')
    assert.equal(node('summary-status').textContent, '版本信息暂不可用')
    assert.equal(node('summary-changes').children.length, 0)
    assert.match(node('release-list').markup, /未能读取发布清单/)
  }
})
