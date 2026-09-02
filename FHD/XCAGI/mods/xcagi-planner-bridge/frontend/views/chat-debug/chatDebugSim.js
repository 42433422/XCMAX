/**
 * 拆分自 ChatDebugView.vue 脚本的纯模拟逻辑（原第 190–198、288–397 行）；
 * 逻辑逐字迁移，行为不变。
 */

export const INTENT_LABEL_MAP = {
  empty: '空输入',
  print: '打印',
  shipment_generate: '开单',
  shipment_and_print: '开单+打印',
  product_query: '产品查询',
  customer_query: '客户查询',
  general_chat: '通用问答'
};

export function classifyIntent(message = '') {
  const text = String(message).trim();
  if (!text) return 'empty';

  const hasPrint = /打印|打标签/.test(text);
  const hasShipment = /生成|开单|发货单/.test(text);
  if (hasPrint && hasShipment) return 'shipment_and_print';
  if (hasPrint) return 'print';
  if (hasShipment) return 'shipment_generate';
  if (/查|查询|价格|型号/.test(text)) return 'product_query';
  if (/客户/.test(text)) return 'customer_query';
  return 'general_chat';
}

export function buildSimulation(message = '', currentMode = 'normal') {
  const text = String(message || '').trim();
  const isPro = currentMode === 'pro';
  const intent = classifyIntent(text);

  if (!text) {
    return {
      modeLabel: isPro ? '专业版' : '普通版',
      intent,
      intentLabel: INTENT_LABEL_MAP.empty,
      flow: '输入校验',
      reply: '请输入测试内容后再执行模拟。',
      steps: ['收到空输入 -> 停止流程'],
      stages: ['输入校验'],
      mockTools: ['none'],
      riskHint: '空输入会直接终止流程，无法进入意图识别。'
    };
  }

  const steps = [
    `收到输入：${text}`,
    `模式判定：${isPro ? '专业版' : '普通版'}`,
    `意图识别：${INTENT_LABEL_MAP[intent] || INTENT_LABEL_MAP.general_chat}`
  ];

  let flow = '';
  let reply = '';
  let riskHint = '';
  let stages = ['输入', '意图识别'];
  let mockTools = ['intent-router'];

  if (isPro) {
    flow = 'professional-simulated';
    stages = [...stages, '任务编排', '运行态跟踪', '结果总结'];
    steps.push('进入专业版任务编排链路（模拟）');
    steps.push('构建多步骤执行计划（模拟）');
    steps.push('输出专业版运行态卡片（模拟）');

    if (intent === 'shipment_and_print') {
      reply = '识别为复合任务：将先开单再打印，展示可执行计划与状态追踪（模拟）。';
      mockTools = ['intent-router', 'planner', 'shipment-generate', 'print-dispatch'];
      riskHint = '复合指令里若缺失客户或时间条件，真实环境需二次确认参数。';
    } else if (intent === 'shipment_generate') {
      reply = '识别为开单任务：将生成待确认任务并提供执行状态（模拟）。';
      mockTools = ['intent-router', 'planner', 'shipment-generate'];
      riskHint = '若产品项不足，真实环境会提示补充明细。';
    } else if (intent === 'print') {
      reply = '识别为打印任务：将检查最近一次可打印上下文后执行打印（模拟）。';
      mockTools = ['intent-router', 'print-context', 'print-dispatch'];
      riskHint = '若无可打印上下文，真实环境会返回“暂无可打印任务”。';
    } else {
      reply = '识别为轻量任务：专业链路将生成简化计划并返回结果（模拟）。';
      mockTools = ['intent-router', 'planner'];
      riskHint = '专业版在轻量查询场景可能略慢于普通版。';
    }
  } else {
    flow = 'normal-simulated';
    stages = [...stages, '单步响应', '可选自动动作'];
    steps.push('进入普通版单步问答链路（模拟）');
    steps.push('生成单轮回复，不做多任务编排（模拟）');

    if (intent === 'shipment_and_print') {
      reply = '识别到复合意图，但普通版会拆解为单步处理并提示分步执行（模拟）。';
      mockTools = ['intent-router', 'single-step-suggestion'];
      riskHint = '普通版无法完整编排多步骤任务，建议切换专业版。';
    } else if (intent === 'shipment_generate') {
      reply = '识别为开单需求：将返回待确认任务卡片（模拟）。';
      mockTools = ['intent-router', 'task-preview'];
      riskHint = '订单号和产品明细在真实流程中仍需确认。';
    } else if (intent === 'print') {
      reply = '识别为打印需求：将检查最近上下文并执行打印动作（模拟）。';
      mockTools = ['intent-router', 'print-context'];
      riskHint = '若未先生成发货单，打印会失败。';
    } else if (intent === 'product_query') {
      reply = '识别为产品查询：可返回查询结果并触发副窗操作（模拟）。';
      mockTools = ['intent-router', 'products-float'];
      riskHint = '关键字过短时可能命中多个产品。';
    } else {
      reply = '识别为通用请求：走基础问答与单次动作判断（模拟）。';
      mockTools = ['intent-router'];
      riskHint = '通用语义过于抽象时，可能需要追问澄清。';
    }
  }

  return {
    modeLabel: isPro ? '专业版' : '普通版',
    intent,
    intentLabel: INTENT_LABEL_MAP[intent] || INTENT_LABEL_MAP.general_chat,
    flow,
    reply,
    steps,
    stages,
    mockTools,
    riskHint
  };
}
