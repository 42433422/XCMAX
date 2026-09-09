/** Semantic controls shared by the screen transport, including runtime Mod routes. */
import { nextTick } from 'vue'
import type { Router } from 'vue-router'

type Params = Record<string, unknown>
type Result = Record<string, unknown>

export function privateControl(el: Element): boolean {
  return el.matches('input[type="password"]') || !!el.closest('[data-ai-private]')
}

export function controlState(el: Element): Result {
  const field = el as HTMLInputElement
  const secret = privateControl(el)
  const state: Result = {
    role: el.getAttribute('role') || '',
    label: el.getAttribute('aria-label') || field.labels?.[0]?.textContent?.trim() || '',
    disabled: el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true',
    readonly: !!field.readOnly || el.getAttribute('aria-readonly') === 'true',
    required: !!field.required || el.getAttribute('aria-required') === 'true',
    sensitive: secret,
  }
  if (!secret && 'value' in el) state.value = field.value
  if (!secret && el instanceof HTMLInputElement && el.type === 'file') {
    state.accept = el.accept
    state.multiple = el.multiple
    state.input_type = 'file'
    state.files = Array.from(el.files ?? [], file => ({ name: file.name, size: file.size, type: file.type }))
  }
  if (el.matches('input[type="checkbox"], input[type="radio"]')) state.checked = field.checked
  for (const key of ['checked', 'expanded', 'selected', 'invalid']) {
    if (el.hasAttribute(`aria-${key}`)) state[key] = el.getAttribute(`aria-${key}`)
  }
  if (el instanceof HTMLSelectElement) {
    state.multiple = el.multiple
    state.options = Array.from(el.options, (option) => ({
      value: option.value, label: option.label, selected: option.selected, disabled: option.disabled,
    }))
  }
  return state
}

export function screenRoutes(router: Router | null): Result {
  if (!router) return { success: false, message: 'router 未就绪' }
  return {
    success: true,
    route: router.currentRoute.value.fullPath,
    routes: router.getRoutes().map((route) => ({
      path: route.path,
      name: String(route.name || ''),
      title: String(route.meta.title || ''),
      parameterized: route.path.includes(':'),
      redirect: !!route.redirect,
    })),
    instruction: '页面目录包含当前已挂载的 Mods。跳转仍由当前账号的路由守卫检查；参数化路径需要真实对象 ID。',
  }
}

export function ensureEditable(el: HTMLElement): void {
  if (!el.isConnected) throw new Error('控件已从页面移除，请重新获取快照')
  for (let node: HTMLElement | null = el; node; node = node.parentElement) {
    const style = window.getComputedStyle(node)
    if (node.hidden || style.display === 'none' || style.visibility === 'hidden') {
      throw new Error('控件不可见，未执行操作')
    }
  }
  if (el.matches(':disabled') || el.closest('[inert]') || el.getAttribute('aria-disabled') === 'true') {
    throw new Error('控件已禁用，未执行操作')
  }
  if ((el as HTMLInputElement).readOnly || el.getAttribute('aria-readonly') === 'true') {
    throw new Error('控件只读，未执行操作')
  }
}

export async function navigateScreen(router: Router | null, path: string): Promise<Result> {
  if (!router) return { success: false, message: 'router 未就绪' }
  const target = router.resolve(path)
  if (!target.matched.length) return { success: false, code: 'SCREEN_ROUTE_NOT_FOUND', path }
  await router.push(path)
  await nextTick()
  const route = router.currentRoute.value.fullPath
  const success = route === target.fullPath
  return {
    success, route, requested_route: target.fullPath,
    verification: success ? 'route_reached' : 'route_not_reached',
    ...(success ? {} : { code: 'SCREEN_NAVIGATION_INTERRUPTED', message: '页面未到达请求位置，请检查权限、重定向或路由守卫' }),
  }
}

export async function selectScreenOption(el: HTMLElement, params: Params): Promise<Result> {
  ensureEditable(el)
  if (!(el instanceof HTMLSelectElement)) {
    return { success: false, message: '目标不是原生下拉框；自定义下拉框请点击并从新快照选择选项' }
  }
  const raw = params.values
  if (!Array.isArray(raw) || raw.some((value) => typeof value !== 'string')) {
    return { success: false, message: 'values 必须是字符串数组' }
  }
  const values = new Set(raw as string[])
  if (!el.multiple && values.size !== 1) return { success: false, message: '单选框必须选择一个值' }
  const options = Array.from(el.options)
  if ([...values].some((value) => !options.some((option) => option.value === value && !option.disabled && !option.closest('optgroup:disabled')))) {
    return { success: false, message: '选项不存在或已禁用，未修改选择' }
  }
  for (const option of options) option.selected = values.has(option.value)
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
  await nextTick()
  const actual = Array.from(el.selectedOptions, (option) => option.value)
  return { success: actual.length === values.size && actual.every((value) => values.has(value)), selected: actual }
}

export async function checkScreenControl(el: HTMLElement, params: Params): Promise<Result> {
  ensureEditable(el)
  if (typeof params.checked !== 'boolean') return { success: false, message: 'checked 必须是布尔值' }
  const native = el instanceof HTMLInputElement && ['checkbox', 'radio'].includes(el.type)
  const aria = ['checkbox', 'switch', 'radio'].includes(el.getAttribute('role') || '')
  if (!native && !aria) return { success: false, message: '目标不是勾选控件' }
  const checked = () => native ? (el as HTMLInputElement).checked : el.getAttribute('aria-checked') === 'true'
  if (checked() !== params.checked) el.click()
  await nextTick()
  return { success: checked() === params.checked, checked: checked() }
}

export async function pressScreenKey(el: HTMLElement, params: Params): Promise<Result> {
  ensureEditable(el)
  const key = String(params.key || '')
  if (!['Enter', 'Escape', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', ' '].includes(key)) {
    return { success: false, message: '不支持的按键' }
  }
  el.focus()
  const accepted = el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  // Synthetic keyboard events do not perform browser defaults. Implement only
  // native activation; application handlers cancelling keydown remain authoritative.
  if (accepted && key === 'Enter' && el.matches('button, a[href], input[type="submit"]')) el.click()
  if (accepted && key === ' ' && el.matches('button, input[type="checkbox"], input[type="radio"]')) el.click()
  el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }))
  await nextTick()
  return { success: true, key, verification: 'keyboard_event_dispatched', instruction: '请回读快照验证页面或业务结果' }
}
