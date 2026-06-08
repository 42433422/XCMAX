/**
 * 客户端「车间」注册表 — 仅管理端值班图使用，不向普通用户暴露。
 *
 * 扩展新车间：在此数组追加一条（可选 linkedAreaId / route），无需改顶栏导航。
 */
import type { RouteLocationRaw } from 'vue-router'
import { OFFICE_EMPLOYEE_PKG_IDS } from '@/constants/officeEmployeePack'
import { YUANGON_AREAS } from './yuangonDutyRoster'

export type ClientWorkshopKind = 'gear' | 'page'

export type ClientWorkshop = {
  id: string
  label: string
  description?: string
  kind: ClientWorkshopKind
  enabled: boolean
  route?: { name: string; query?: Record<string, string> }
  linkedAreaId?: keyof typeof YUANGON_AREAS | string
  linkedEmployeeIds?: string[]
  tags?: string[]
}

/** Vue Flow 节点 id 前缀，避免与编制员工 id 冲突 */
export const CLIENT_WORKSHOP_NODE_PREFIX = '__ws__'

export function clientWorkshopNodeId(workshopId: string): string {
  return `${CLIENT_WORKSHOP_NODE_PREFIX}${workshopId}`
}

export function parseClientWorkshopNodeId(nodeId: string): string | null {
  if (!nodeId.startsWith(CLIENT_WORKSHOP_NODE_PREFIX)) return null
  return nodeId.slice(CLIENT_WORKSHOP_NODE_PREFIX.length) || null
}

const CLIENT_WORKSHOPS_SEED: ClientWorkshop[] = [
  {
    id: 'wb-gear-direct',
    label: '聊',
    description: '通用对话档位：直接提问、附件与模型选择。',
    kind: 'gear',
    enabled: true,
    route: { name: 'workbench-home', query: { wbGear: 'direct' } },
    linkedEmployeeIds: [...OFFICE_EMPLOYEE_PKG_IDS],
    tags: ['核心', '档位'],
  },
  {
    id: 'wb-gear-make',
    label: '做',
    description: '制作与编排档位：Mod/员工/Skill 与二档 composer。',
    kind: 'gear',
    enabled: true,
    route: { name: 'workbench-home', query: { wbGear: 'make' } },
    linkedAreaId: 'craft-workshop',
    tags: ['核心', '档位'],
  },
  {
    id: 'wb-gear-voice',
    label: '说',
    description: '语音对话档位：聆听、识别与 TTS。',
    kind: 'gear',
    enabled: true,
    route: { name: 'workbench-home', query: { wbGear: 'voice' } },
    tags: ['核心', '档位'],
  },
  {
    id: 'wb-unified',
    label: '统一工作台',
    description: '仓库、Skill、员工制作与集成入口。',
    kind: 'page',
    enabled: true,
    route: { name: 'workbench-unified', query: { focus: 'repository' } },
    tags: ['功能页'],
  },
  {
    id: 'wb-script-workflows',
    label: '脚本工作流',
    description: '脚本即工作流：列表、编排与运行。',
    kind: 'page',
    enabled: true,
    route: { name: 'workbench-script-workflows' },
    tags: ['功能页'],
  },
  {
    id: 'wb-employees',
    label: '我的员工',
    description: '用户已购/自建员工包管理。',
    kind: 'page',
    enabled: true,
    route: { name: 'workbench-employees' },
    tags: ['功能页'],
  },
  {
    id: 'wb-materials',
    label: '我的素材',
    description: '素材与知识资产。',
    kind: 'page',
    enabled: true,
    route: { name: 'workbench-materials' },
    tags: ['功能页'],
  },
  {
    id: 'wb-download',
    label: '软件下载',
    description: '客户端与工具下载页。',
    kind: 'page',
    enabled: true,
    route: { name: 'workbench-download' },
    tags: ['功能页'],
  },
]

export const CLIENT_WORKSHOPS: readonly ClientWorkshop[] = Object.freeze(
  CLIENT_WORKSHOPS_SEED.map((w) => Object.freeze({ ...w })),
)

export function listClientWorkshops(opts?: { includeDisabled?: boolean }): ClientWorkshop[] {
  const all = [...CLIENT_WORKSHOPS]
  if (opts?.includeDisabled) return all
  return all.filter((w) => w.enabled)
}

export function getClientWorkshop(id: string): ClientWorkshop | undefined {
  return CLIENT_WORKSHOPS.find((w) => w.id === id)
}

export function resolveClientWorkshopRoute(workshop: ClientWorkshop): RouteLocationRaw | null {
  if (!workshop.route?.name) return null
  return {
    name: workshop.route.name,
    query: workshop.route.query ? { ...workshop.route.query } : undefined,
  }
}

export function workshopsForArea(areaId: string): ClientWorkshop[] {
  return CLIENT_WORKSHOPS.filter((w) => w.linkedAreaId === areaId)
}

/** 车间关联的编制 pkg_id（显式列表优先，否则取编制区） */
export function linkedRosterEmployeeIds(workshop: ClientWorkshop): string[] {
  if (workshop.linkedEmployeeIds?.length) return [...workshop.linkedEmployeeIds]
  if (!workshop.linkedAreaId) return []
  const block = YUANGON_AREAS[workshop.linkedAreaId]
  return block ? [...block.ids] : []
}

export type WbGear = 'direct' | 'make' | 'voice'

export function parseWbGearQuery(raw: unknown): WbGear | null {
  const v = String(raw ?? '').trim().toLowerCase()
  if (v === 'direct' || v === 'make' || v === 'voice') return v
  return null
}
