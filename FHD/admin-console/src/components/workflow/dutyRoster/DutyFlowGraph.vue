/**
 * VueFlow 画布（含自定义 group / default 节点模板）。
 *
 * 由 DutyRosterGraphPanel.vue 模板机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import type { Deref } from './dutyRosterTypes'
import { HEALTH_LABEL, LLM_ACT_LABEL, RUN_STATUS_LABEL } from './dutyRosterConstants'
import type { HealthLv, LlmActLv, RunNodeStatus } from './dutyRosterTypes'
import type { DutyLoopCore } from './useDutyLoopCore'
import type { DutyRosterState } from './useDutyRosterState'
import type { DutyWorkshop } from './useDutyWorkshop'

defineEmits<{
}>()

defineProps<{
  flowNodes: Deref<DutyRosterState['flowNodes']>
  flowEdges: Deref<DutyRosterState['flowEdges']>
  flowBgPatternColor: string
  miniMapMaskColor: string
  nodeLoopActive: Deref<DutyLoopCore['nodeLoopActive']>
  handleNodeClick: Deref<DutyWorkshop['onNodeClick']>
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
                style="width: 100%; height: 100%;"
                @node-click="handleNodeClick"
              >
                <Background :pattern-color="flowBgPatternColor" :gap="24" />
                <Controls position="bottom-left" />
                <MiniMap position="bottom-right" :mask-color="miniMapMaskColor" />

                <!-- 六部门 / 物理分区：父级 group 容器 -->
                <template #node-group="{ label }">
                  <div class="dg-group-node">
                    <span class="dg-group-node__label">{{ label }}</span>
                  </div>
                </template>

                <!-- Custom node: health dot -->
                <template #node-default="{ data, label }">
                  <div class="dg-node-inner" :class="{ 'dg-node-inner--workshop': data?.isWorkshop, 'dg-node-inner--loop': nodeLoopActive(data) }">
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
                      <!-- Self-evolution loop participation dot -->
                      <span
                        v-if="nodeLoopActive(data)"
                        class="dg-node-dot dg-node-dot--loop"
                        title="正在参与自进化 Loop"
                      />
                    </span>
                  </div>
                </template>
              </VueFlow>

              <!-- ── 客户端车间详情（仅管理端） ───────────────────────────── -->
</template>

<style scoped src="../DutyRosterGraphPanel.css"></style>
