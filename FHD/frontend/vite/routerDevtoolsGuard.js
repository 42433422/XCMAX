/** vue-router 4.6 RouterView 在 ref.i 为空时写入 __vrv_devtools，管理端首屏因此中断。 */

export function guardRouterDevtoolsAssignment(code) {
  if (!code.includes('__vrv_devtools') || code.includes('component.ref && component.ref.i')) return code
  return code
    .replaceAll('component.ref.map((r) => r.i)', 'component.ref.map((r) => r && r.i)')
    .replaceAll('[component.ref.i]', '[component.ref && component.ref.i]')
    .replaceAll(
      '.forEach((instance) => {\n          instance.__vrv_devtools = info;',
      '.filter(Boolean).forEach((instance) => {\n          instance.__vrv_devtools = info;',
    )
    .replaceAll(
      '.forEach((instance)=>{instance.__vrv_devtools=info;',
      '.filter(Boolean).forEach((instance)=>{instance.__vrv_devtools=info;',
    )
}

export function routerDevtoolsNullGuard() {
  return {
    name: 'vue-router-devtools-null-guard',
    enforce: 'pre',
    transform(code, id) {
      if (!id.includes('vue-router') || !code.includes('instance.__vrv_devtools')) return null
      const next = guardRouterDevtoolsAssignment(code)
      return next === code ? null : next
    },
  }
}
