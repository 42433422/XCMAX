/**
 * Pretext.js 性能测试工具
 * 对比 DOM 测量 vs Pretext.js 数学计算
 */

import { measureText, batchMeasure } from './pretext';

interface TestResult {
  name: string;
  domTime: number;
  pretextTime: number;
  speedup: number;
  iterations: number;
}

/**
 * 测试 DOM 测量性能
 */
function testDOMMeasurement(text: string, width: number): number {
  const start = performance.now();
  
  // 创建临时元素
  const el = document.createElement('div');
  el.style.cssText = `
    position: absolute;
    visibility: hidden;
    width: ${width}px;
    font-size: 14px;
    line-height: 1.5;
    font-family: system-ui, -apple-system, sans-serif;
    white-space: pre-wrap;
    word-wrap: break-word;
  `;
  el.textContent = text;
  document.body.appendChild(el);
  
  // 强制重排并测量
  const height = el.offsetHeight;
  
  // 清理
  document.body.removeChild(el);
  
  const end = performance.now();
  return end - start;
}

/**
 * 测试 Pretext.js 性能
 */
function testPretextMeasurement(text: string, width: number): number {
  const start = performance.now();
  
  measureText({
    text,
    width,
    fontSize: 14,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
  });
  
  const end = performance.now();
  return end - start;
}

/**
 * 运行单条消息测试
 */
export function runSingleMessageTest(
  message: string,
  width: number = 600,
  iterations: number = 100
): TestResult {
  // 预热
  for (let i = 0; i < 10; i++) {
    testDOMMeasurement(message, width);
    testPretextMeasurement(message, width);
  }
  
  // 测试 DOM 测量
  let domTotalTime = 0;
  for (let i = 0; i < iterations; i++) {
    domTotalTime += testDOMMeasurement(message, width);
  }
  const domAvgTime = domTotalTime / iterations;
  
  // 测试 Pretext.js
  let pretextTotalTime = 0;
  for (let i = 0; i < iterations; i++) {
    pretextTotalTime += testPretextMeasurement(message, width);
  }
  const pretextAvgTime = pretextTotalTime / iterations;
  
  return {
    name: `单条消息 (${message.length} 字符)`,
    domTime: domAvgTime,
    pretextTime: pretextAvgTime,
    speedup: domAvgTime / pretextAvgTime,
    iterations,
  };
}

/**
 * 运行批量消息测试
 */
export function runBatchMessageTest(
  messages: string[],
  width: number = 600
): TestResult {
  const iterations = 100;
  
  // 预热
  for (let i = 0; i < 10; i++) {
    messages.forEach(msg => testDOMMeasurement(msg, width));
    batchMeasure(messages.map(msg => ({
      text: msg,
      width,
      fontSize: 14,
      lineHeight: 1.5,
      whiteSpace: 'pre-wrap',
    })));
  }
  
  // 测试 DOM 批量测量
  let domTotalTime = 0;
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    messages.forEach(msg => testDOMMeasurement(msg, width));
    domTotalTime += performance.now() - start;
  }
  const domAvgTime = domTotalTime / iterations;
  
  // 测试 Pretext.js 批量测量
  let pretextTotalTime = 0;
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    batchMeasure(messages.map(msg => ({
      text: msg,
      width,
      fontSize: 14,
      lineHeight: 1.5,
      whiteSpace: 'pre-wrap',
    })));
    pretextTotalTime += performance.now() - start;
  }
  const pretextAvgTime = pretextTotalTime / iterations;
  
  return {
    name: `批量消息 (${messages.length} 条)`,
    domTime: domAvgTime,
    pretextTime: pretextAvgTime,
    speedup: domAvgTime / pretextAvgTime,
    iterations,
  };
}

/**
 * 运行完整测试套件
 */
export function runFullTestSuite(): TestResult[] {
  const results: TestResult[] = [];
  
  // 测试数据
  const shortMessage = '这是一条短消息。';
  const mediumMessage = '这是一条中等长度的消息，包含一些常见的对话内容。在实际应用中，这种长度的消息非常常见。';
  const longMessage = '这是一条很长的消息，模拟 AI 回复的详细内容。在实际应用中，AI 可能会返回较长的回复，包含多个段落和详细说明。这种消息需要更复杂的布局计算，包括换行、段落间距等。Pretext.js 的优势在这种情况下会更加明显，因为它可以完全避免 DOM 重排带来的性能损耗。';
  
  const messages = [
    '你好！',
    '这是一个测试消息。',
    'Pretext.js 是一个用于文本测量的 JavaScript 库。',
    '它通过数学计算而不是 DOM 操作来测量文本尺寸。',
    '这种方式比传统的 DOM 测量快数百倍。',
    '特别适用于需要频繁测量文本的场景。',
    '例如聊天应用、虚拟列表等。',
    '它支持多行文本、不同字体、对齐方式等。',
    '并且完全在 JavaScript 中完成，不依赖浏览器布局引擎。',
    '这使得它可以在 Web Worker 中使用。',
  ];
  
  console.group('🚀 Pretext.js 性能测试');
  
  // 单条消息测试
  console.log('📊 单条消息测试...');
  results.push(runSingleMessageTest(shortMessage, 600, 100));
  results.push(runSingleMessageTest(mediumMessage, 600, 100));
  results.push(runSingleMessageTest(longMessage, 600, 100));
  
  // 批量消息测试
  console.log('📊 批量消息测试...');
  results.push(runBatchMessageTest(messages, 600));
  
  // 打印结果
  console.log('\n📈 测试结果：');
  console.table(results.map(r => ({
    测试项: r.name,
    'DOM 耗时 (ms)': r.domTime.toFixed(3),
    'Pretext 耗时 (ms)': r.pretextTime.toFixed(3),
    '加速比': `${r.speedup.toFixed(1)}x`,
    '迭代次数': r.iterations,
  })));
  
  const avgSpeedup = results.reduce((sum, r) => sum + r.speedup, 0) / results.length;
  console.log(`\n✅ 平均加速比: ${avgSpeedup.toFixed(1)}x`);
  
  console.groupEnd();
  
  return results;
}

/**
 * 在控制台运行测试
 * 使用: import { runFullTestSuite } from '@/utils/pretext-performance-test'
 *       runFullTestSuite()
 */
export default {
  runSingleMessageTest,
  runBatchMessageTest,
  runFullTestSuite,
};
