import { ref } from 'vue';
import { buildSimulation } from './chatDebugSim';

/**
 * 拆分自 ChatDebugView.vue 脚本（原第 175–188、200–202、399–415 行）；
 * 逻辑逐字迁移，行为不变。
 */
export function useChatDebugSim() {
  const mode = ref('normal');
  const inputText = ref('');
  const result = ref(null);
  const compareResult = ref(null);

  const presetCases = [
    { label: '产品查询', text: '查一下A001的价格' },
    { label: '客户查询', text: '有哪些客户？' },
    { label: '开单需求', text: '给成都客户生成今天发货单' },
    { label: '打印命令', text: '开始打印' },
    { label: '复合任务', text: '给成都客户生成并打印今天发货单' }
  ];

  function applyPreset(text) {
    inputText.value = text;
  }

  function runSimulation() {
    result.value = buildSimulation(inputText.value, mode.value);
    compareResult.value = null;
  }

  function runCompareSimulation() {
    const normal = buildSimulation(inputText.value, 'normal');
    const pro = buildSimulation(inputText.value, 'pro');
    compareResult.value = { normal, pro };
    result.value = mode.value === 'pro' ? pro : normal;
  }

  function resetResult() {
    inputText.value = '';
    result.value = null;
    compareResult.value = null;
  }

  return {
    mode, inputText, result, compareResult, presetCases,
    applyPreset, runSimulation, runCompareSimulation, resetResult,
  };
}
