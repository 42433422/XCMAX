import { describe, expect, it, vi } from 'vitest'
import { RouteScrollMemory } from './routeScrollMemory'

function setup() {
  const root = document.createElement('section')
  root.innerHTML = '<div class="shell"><div id="orders" class="scrollable"><p>Orders</p></div></div>'
  const scroller = root.querySelector<HTMLElement>('#orders')!
  return { root, scroller }
}

describe('RouteScrollMemory', () => {
  it('restores vertical and horizontal offset without rescanning the DOM', () => {
    const { root, scroller } = setup()
    const memory = new RouteScrollMemory()
    scroller.scrollTop = 180
    scroller.scrollLeft = 23
    memory.remember('/orders', root)
    scroller.scrollTop = 0
    scroller.scrollLeft = 0
    const scan = vi.spyOn(root, 'querySelectorAll')
    memory.restore('/orders', root)
    expect(scroller.scrollTop).toBe(180)
    expect(scroller.scrollLeft).toBe(23)
    expect(scan).not.toHaveBeenCalled()
    scan.mockRestore()
  })

  it('refuses to apply stored positions to a changed destination node', () => {
    const { root, scroller } = setup()
    const memory = new RouteScrollMemory()
    scroller.scrollTop = 80
    memory.remember('/orders', root)
    scroller.scrollTop = 0
    scroller.className = 'other-section'
    memory.restore('/orders', root)
    expect(scroller.scrollTop).toBe(0)
  })

  it('bounds remembered routes and clears all scope-specific offsets', () => {
    const { root, scroller } = setup()
    const memory = new RouteScrollMemory(2)
    scroller.scrollTop = 20; memory.remember('A', root)
    scroller.scrollTop = 30; memory.remember('B', root)
    scroller.scrollTop = 40; memory.remember('C', root)
    scroller.scrollTop = 0
    memory.restore('A', root)
    expect(scroller.scrollTop).toBe(0)
    memory.restore('B', root)
    expect(scroller.scrollTop).toBe(30)
    memory.clear()
    scroller.scrollTop = 0
    memory.restore('C', root)
    expect(scroller.scrollTop).toBe(0)
  })

  it('records only a bounded number of scroll positions', () => {
    const root = document.createElement('main')
    const nodes = Array.from({ length: 10 }, (_, i) => {
      const node = document.createElement('div')
      node.id = String(i)
      node.scrollTop = i + 1
      root.appendChild(node)
      return node
    })
    const memory = new RouteScrollMemory(2, 3)
    memory.remember('/large', root)
    nodes.forEach(node => { node.scrollTop = 0 })
    memory.restore('/large', root)
    expect(nodes.map(node => node.scrollTop)).toEqual([1, 2, 3, 0, 0, 0, 0, 0, 0, 0])
  })
})
