import { CLIENT_PRIMARY_ERP_MOD_ID } from '@/constants/genericModPack';
import type { ModInfo } from '@/types/modInfo';

/** 与 mods/attendance-industry/manifest.json frontend.menu 保持一致 */
export const ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU: NonNullable<ModInfo['menu']> = [
  {
    id: 'attendance-industry-home',
    label: '考勤表转换',
    icon: 'fa-file-excel-o',
    path: '/attendance-industry',
  },
];

export const ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES: NonNullable<ModInfo['menu_overrides']> = [];

/** 与 mods/sz-qsm-pro/manifest.json frontend.menu_overrides 保持一致 */
export const COATING_CUSTOM_MOD_FALLBACK_OVERRIDES: NonNullable<ModInfo['menu_overrides']> = [
  { key: 'products', label: '产品管理' },
  { key: 'customers', label: '客户管理' },
  { key: 'materials', label: '原材料仓库' },
  { key: 'orders', label: '出货单管理' },
  { key: 'shipment-records', label: '出货记录' },
  { key: 'print', label: '标签打印' },
];

/** @deprecated 使用 ATTENDANCE_INDUSTRY_* 命名 */
export const SUNBIRD_CLIENT_MOD_FALLBACK_MENU = ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU;
export const SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES = ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES;

/** API 尚未返回考勤行业包时，侧栏/设置页仍可展示考勤转换入口 */
export function buildAttendanceIndustryModStub(): ModInfo {
  return {
    id: CLIENT_PRIMARY_ERP_MOD_ID,
    name: '考勤行业包',
    version: '1.0.0',
    author: 'XCAGI',
    description: '考勤行业通用包',
    primary: true,
    frontend: { pro_entry_path: '/attendance-industry' },
    menu: ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU.map((row) => ({ ...row })),
    menu_overrides: [],
    industry: {
      id: '考勤',
      name: '考勤/人事行业',
    },
  };
}

/** API 尚未返回奇士美定制 Mod 时，侧栏仍可展示涂料业务菜单覆盖 */
export function buildCoatingCustomModStub(): ModInfo {
  return {
    id: 'sz-qsm-pro',
    name: '奇士美 PRO',
    version: '1.0.0',
    author: 'XCAGI',
    description: '奇士美客户定制 Mod',
    primary: true,
    frontend: { pro_entry_path: '/qsm-pro' },
    menu: [
      {
        id: 'qsm-pro-home',
        label: '奇士美工作台',
        icon: 'fa-paint-brush',
        path: '/qsm-pro',
      },
    ],
    menu_overrides: COATING_CUSTOM_MOD_FALLBACK_OVERRIDES.map((row) => ({ ...row })),
    industry: {
      id: '涂料',
      name: '涂料/化工行业',
    },
  };
}

/** @deprecated 使用 buildAttendanceIndustryModStub */
export const buildSunbirdClientModStub = buildAttendanceIndustryModStub;
