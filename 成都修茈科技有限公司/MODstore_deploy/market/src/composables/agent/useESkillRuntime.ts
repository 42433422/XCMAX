import { ref, onMounted } from 'vue'
import { skillRegistry } from '../../utils/agent/agentSkillRegistry'
import type { ESkillDef, AgentSkill } from '../../types/agent'
import { api } from '../../api'

/** 把后端 ESkillDef 转换成前端 AgentSkill（简化：直接用 runESkill 执行） */
function adaptRemoteSkill(def: ESkillDef): AgentSkill {
  return {
    id: `remote:${def.skill_id}`,
    name: def.name,
    description: def.description,
    version: def.version,
    trigger: {
      keywords: def.trigger_keywords || [],
      intent: def.trigger_intent || [],
    },
    permission: def.permission,
    metadata: {
      author: 'remote',
      created_at: new Date(def.created_at).getTime(),
      evolution_count: 0,
      usage_count: def.usage_count,
    },
    async execute(context, args) {
      try {
        const res = (await (api as any).runESkill(def.id, {
          context: {
            route: context.route,
            userMessage: context.userMessage,
            pageSummary: context.pageSummary,
          },
          args: args || {},
        })) as { result?: string; message?: string; success?: boolean }
        return {
          success: res.success !== false,
          message: res.result || res.message || '技能已执行',
          assistantReply: res.result || res.message,
        }
      } catch (e: unknown) {
        return { success: false, message: e instanceof Error ? e.message : String(e) }
      }
    },
  }
}

export function useESkillRuntime() {
  const remoteSkills = ref<ESkillDef[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchAndRegisterRemoteSkills() {
    loading.value = true
    error.value = ''
    try {
      const data = (await (api as any).listButlerSkills?.()) as ESkillDef[] | undefined
      if (Array.isArray(data)) {
        remoteSkills.value = data
        for (const def of data) {
          if (def.is_active) {
            skillRegistry.register(adaptRemoteSkill(def))
          }
        }
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void fetchAndRegisterRemoteSkills()
  })

  return { remoteSkills, loading, error, fetchAndRegisterRemoteSkills }
}
