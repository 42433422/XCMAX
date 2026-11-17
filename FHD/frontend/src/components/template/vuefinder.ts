/**
 * VueFinder（MIT，4.8.0）宿主侧再导出。
 * Mod 前端位于 frontend/ 之外，裸包名无法从该目录解析 node_modules，统一经 @ 别名引入。
 */
import 'vuefinder/dist/vuefinder.css'
// @ts-expect-error 官方语言包未提供类型声明
import zhCN from 'vuefinder/dist/locales/zhCN.js'

export { VueFinder, VueFinderPlugin, ArrayDriver } from 'vuefinder'
export type { DirEntry } from 'vuefinder'
export { zhCN }
