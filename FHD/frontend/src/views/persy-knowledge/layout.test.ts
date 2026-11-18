import { afterEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const styles: HTMLStyleElement[] = []
afterEach(() => { styles.splice(0).forEach(style => style.remove()); document.body.innerHTML = '' })
function style(css: string) { const element = document.createElement('style'); element.textContent = css; document.head.append(element); styles.push(element) }
it('allows the graph canvas to shrink to the remaining body height instead of clipping a 420px canvas', () => {
  const source = readFileSync(resolve('src/components/persy/PersyKnowledgeGraph.vue'), 'utf8')
  style(source.split('<style scoped>')[1].split('</style>')[0])
  document.body.innerHTML = '<div class="persy-graph"><div class="persy-graph__canvas"></div></div>'
  const canvas = getComputedStyle(document.querySelector('.persy-graph__canvas')!)
  expect(canvas.height).toBe('100%')
  expect(parseFloat(canvas.minHeight)).toBe(0)
})
it('reserves a separate nonshrinking input row and a shrinkable content body', () => {
  style(readFileSync(resolve('src/views/persy-knowledge/persy-knowledge.css'), 'utf8'))
  document.body.innerHTML = '<main class="brain-stage"><div class="brain-stage__body"></div><form class="ask-dock"></form></main>'
  const stage = getComputedStyle(document.querySelector('.brain-stage')!)
  const body = getComputedStyle(document.querySelector('.brain-stage__body')!)
  const dock = getComputedStyle(document.querySelector('.ask-dock')!)
  expect(stage.display).toBe('flex')
  expect(stage.flexDirection).toBe('column')
  expect(body.flexGrow).toBe('1')
  expect(parseFloat(body.minHeight)).toBe(0)
  expect(dock.position).toBe('relative')
  expect(dock.flexShrink).toBe('0')
})
