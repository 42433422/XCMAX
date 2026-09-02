<script setup lang="ts">
import VoicePhoneModal from '../../components/workbench/VoicePhoneModal.vue'
import AgentMarket from '../../components/workbench/AgentMarket.vue'
import MediaGenPanel from '../../components/workbench/MediaGenPanel.vue'
import type { WorkbenchHomeCtx } from './assemble'

// 拆分自 WorkbenchHomeView.vue 模板（原第 714–734 行）；模板逐字迁移，行为不变。
const props = defineProps<{ wb: WorkbenchHomeCtx }>()

const {
  showAgentMarket, showVoicePhone, showMediaGen, mediaGenInitialTab, allBots, onCreateAgent,
  onRemoveAgent, onFavoriteAgent, onStartWithAgent, mediaGenRunner, insertGeneratedToChat, handleVoicePhoneTurn,
} = props.wb
</script>

<template>
              <AgentMarket
                :open="showAgentMarket"
                :bots="allBots"
                @close="showAgentMarket = false"
                @start="onStartWithAgent"
                @create="onCreateAgent"
                @remove="onRemoveAgent"
                @favorite="onFavoriteAgent"
              />
              <VoicePhoneModal
                :open="showVoicePhone"
                :on-turn="handleVoicePhoneTurn"
                @close="showVoicePhone = false"
              />
              <MediaGenPanel
                :open="showMediaGen"
                :initial-tab="mediaGenInitialTab"
                :runner="mediaGenRunner"
                @close="showMediaGen = false"
                @insert="insertGeneratedToChat"
              />
</template>
