// CI SSOT: generated from config/deployment_modes.yaml — DO NOT EDIT BY HAND
// 改部署模式请编辑该 yaml 后运行: python scripts/dev/deployment_modes_ssot.py generate --apply

export type DeploymentModeId = 'absolute_safe' | 'safe' | 'performance';

export type DeploymentMode = {
  id: DeploymentModeId;
  level: number;
  label: string;
  badge: string;
  summary: string;
  networkScope: string;
  aiMode: 'online' | 'offline';
  databaseMode: 'local_sqlite' | 'remote_postgresql';
  mobileConnection: string;
  performanceProfile: string;
  allowsOutbound: boolean;
  requiresPostgresql: boolean;
  features: string[];
};

export const DEFAULT_DEPLOYMENT_MODE: DeploymentModeId = 'safe';
export const DEPLOYMENT_MODE_IDS = [
  "absolute_safe",
  "safe",
  "performance"
] as const;
export const DEPLOYMENT_MODES = [
  {
    "id": "absolute_safe",
    "level": 1,
    "label": "绝对安全模式",
    "badge": "1级 | 内网 + SQLite",
    "summary": "数据最安全，桌面端与移动端优先局域网直连，AI 不走外网。",
    "networkScope": "lan",
    "aiMode": "offline",
    "databaseMode": "local_sqlite",
    "mobileConnection": "lan_direct",
    "performanceProfile": "conservative",
    "allowsOutbound": false,
    "requiresPostgresql": false,
    "features": [
      "本地部署",
      "零出网",
      "最高数据安全"
    ]
  },
  {
    "id": "safe",
    "level": 2,
    "label": "安全模式",
    "badge": "2级 | 外网 + SQLite",
    "summary": "解放 AI 能力，业务数据仍保留在本机 SQLite。",
    "networkScope": "public",
    "aiMode": "online",
    "databaseMode": "local_sqlite",
    "mobileConnection": "public_relay_with_lan_fallback",
    "performanceProfile": "balanced",
    "allowsOutbound": true,
    "requiresPostgresql": false,
    "features": [
      "AI 能力增强",
      "数据本地留存",
      "安全与效率平衡"
    ]
  },
  {
    "id": "performance",
    "level": 3,
    "label": "性能模式",
    "badge": "3级 | 外网 + PostgreSQL",
    "summary": "全面释放 AI 性能、长期记忆能力与工具调用，适合真实 AI 员工协作。",
    "networkScope": "public",
    "aiMode": "online",
    "databaseMode": "remote_postgresql",
    "mobileConnection": "public_relay_with_lan_fallback",
    "performanceProfile": "performance",
    "allowsOutbound": true,
    "requiresPostgresql": true,
    "features": [
      "PostgreSQL 向量索引",
      "长期记忆",
      "工具调用",
      "高性能协作"
    ]
  }
] as DeploymentMode[];
