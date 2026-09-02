/**
 * VueFlow 画布（含自定义 default 节点模板与健康 / LLM / 能力 / Run 状态点）。
 *
 * 由 AdminDutyEmployeeGraph.vue 模板块机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { HEALTH_LABEL, LLM_ACT_LABEL, RUN_STATUS_LABEL } from './adminDutyConstants'
import type { HealthLv, LlmActLv, RunNodeStatus } from './adminDutyTypes'
import { VueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'

defineProps<{
  flowNodes: Node[]
  flowEdges: Edge[]
  handleNodeClick: (arg: { node: Node }) => void
}>()

</script>

<template>
              <VueFlow
                id="admin-duty-graph"
                :nodes="flowNodes"
                :edges="flowEdges"
                :nodes-connectable="false"
                :elements-selectable="true"
                fit-view-on-init
                class="dg-flow"
                @node-click="handleNodeClick"
              >
                <Background pattern-color="rgba(255,255,255,0.04)" :gap="24" />
                <Controls position="bottom-left" />
                <MiniMap position="bottom-right" mask-color="rgba(0,0,0,0.45)" />

                <!-- Custom node: health dot -->
                <template #node-default="{ data, label }">
                  <div class="dg-node-inner" :class="{ 'dg-node-inner--workshop': data?.isWorkshop }">
                    <span class="dg-node-label">{{ label }}</span>
                    <span v-if="data?.isWorkshop" class="dg-node-workshop-kind">
                      {{ data.workshop?.kind === 'gear' ? '档位' : '页面' }}
                    </span>
                    <span v-if="!data?.isWorkshop" class="dg-node-dots">
                      <!-- Health dot -->
                      <span
                        v-if="data?.healthLevel && data.healthLevel !== 'unknown'"
                        class="dg-node-dot"
                        :style="{ background: data.healthColor }"
                        :title="HEALTH_LABEL[data.healthLevel as HealthLv]"
                      />
                      <!-- LLM activation dot (Phase 4) -->
                      <span
                        v-if="data?.llmActLevel && data.llmActLevel !== 'unknown'"
                        class="dg-node-dot dg-node-dot--llm"
                        :style="{ background: data.llmActColor }"
                        :title="LLM_ACT_LABEL[data.llmActLevel as LlmActLv]"
                      />
                      <!-- Capability dot -->
                      <span
                        v-if="data?.capLevel && data.capLevel !== 'unknown'"
                        class="dg-node-dot dg-node-dot--cap"
                        :style="{ background: data.capColor }"
                        :title="data.capLevel === 'executable' ? '可执行' : '不可执行'"
                      />
                      <!-- Graph-run dot -->
                      <span
                        v-if="data?.runStatus && data.runStatus !== 'idle'"
                        class="dg-node-dot dg-node-dot--run"
                        :style="{ background: data.runStatusColor }"
                        :title="RUN_STATUS_LABEL[data.runStatus as RunNodeStatus]"
                      />
                    </span>
                  </div>
                </template>
              </VueFlow>
</template>

<style scoped src="../AdminDutyEmployeeGraph.css"></style>
