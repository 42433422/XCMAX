import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { runInThisContext } from 'node:vm'
import { expect, it } from 'vitest'

const site = join(process.cwd(), '../../成都修茈科技有限公司')
const html = readFileSync(join(site, 'index.html'), 'utf8')
const sharedHeader = readFileSync(join(site, 'partials/header.html'), 'utf8')
const main = readFileSync(join(site, 'main.js'), 'utf8')
const parse = (source: string) => new DOMParser().parseFromString(source, 'text/html')
const market = parse(sharedHeader).querySelector<HTMLAnchorElement>('.nav-actions a[href^="/market"]')!
const selectors = ['#main-nav [data-nav="market"]', '#mobile-menu [data-nav="market"]', '.footer-links [data-nav="market"]']

it('native homepage destinations match the shared header and expose a no-script footer fallback', () => {
  const page = parse(html)
  for (const selector of selectors) {
    const links = page.querySelectorAll<HTMLAnchorElement>(selector)
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe(market.getAttribute('href'))
    expect(links[0].textContent).toBe(market.textContent)
    expect(links[0].closest('[hidden], .nav-secondary, .mobile-secondary')).toBeNull()
  }
  expect(page.querySelector('.footer-links [data-nav="market"]')!.closest('[inert], [hidden], [aria-hidden="true"]')).toBeNull()
})

it('mobile market stays reachable through repeated open, Escape, overlay and link close flows', () => {
  const page = parse(html)
  document.body.replaceChildren(...Array.from(page.body.childNodes, (node) => document.importNode(node, true)))
  runInThisContext(main)
  document.dispatchEvent(new Event('DOMContentLoaded'))
  const toggle = document.getElementById('mobile-menu-toggle')!
  const menu = document.getElementById('mobile-menu')!
  const overlay = document.getElementById('mobile-menu-overlay')!
  const link = menu.querySelector<HTMLAnchorElement>('[data-nav="market"]')!
  link.addEventListener('click', (event) => event.preventDefault())
  for (const close of [() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })), () => overlay.click(), () => link.click()]) {
    toggle.click()
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(menu.getAttribute('aria-hidden')).toBe('false')
    expect(menu.hasAttribute('inert')).toBe(false)
    expect(menu.classList.contains('active')).toBe(true)
    expect(link.getAttribute('href')).toBe(market.getAttribute('href'))
    close()
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(menu.getAttribute('aria-hidden')).toBe('true')
    expect(menu.hasAttribute('inert')).toBe(true)
    expect(document.body.classList.contains('nav-open')).toBe(false)
  }
})
