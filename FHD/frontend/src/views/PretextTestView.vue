<template>
  <div class="pretext-test-view">
    <h1>Pretext.js 性能测试</h1>
    
    <div class="test-section">
      <h2>单条消息测试</h2>
      <div class="test-input">
        <textarea v-model="testMessage" rows="4" placeholder="输入测试消息..."></textarea>
        <button @click="runSingleTest" :disabled="isTesting">
          {{ isTesting ? '测试中...' : '运行测试' }}
        </button>
      </div>
      <div v-if="singleTestResult" class="test-result">
        <h3>测试结果</h3>
        <table>
          <tr>
            <td>DOM 测量耗时</td>
            <td>{{ singleTestResult.domTime.toFixed(3) }} ms</td>
          </tr>
          <tr>
            <td>Pretext.js 耗时</td>
            <td>{{ singleTestResult.pretextTime.toFixed(3) }} ms</td>
          </tr>
          <tr>
            <td>加速比</td>
            <td class="highlight">{{ singleTestResult.speedup.toFixed(1) }}x</td>
          </tr>
        </table>
      </div>
    </div>
    
    <div class="test-section">
      <h2>批量消息测试</h2>
      <button @click="runBatchTest" :disabled="isTesting">
        {{ isTesting ? '测试中...' : '运行批量测试' }}
      </button>
      <div v-if="batchTestResult" class="test-result">
        <h3>测试结果</h3>
        <table>
          <tr>
            <td>消息数量</td>
            <td>10 条</td>
          </tr>
          <tr>
            <td>DOM 测量耗时</td>
            <td>{{ batchTestResult.domTime.toFixed(3) }} ms</td>
          </tr>
          <tr>
            <td>Pretext.js 耗时</td>
            <td>{{ batchTestResult.pretextTime.toFixed(3) }} ms</td>
          </tr>
          <tr>
            <td>加速比</td>
            <td class="highlight">{{ batchTestResult.speedup.toFixed(1) }}x</td>
          </tr>
        </table>
      </div>
    </div>
    
    <div class="test-section">
      <h2>完整测试套件</h2>
      <button @click="runFullTest" :disabled="isTesting">
        {{ isTesting ? '测试中...' : '运行完整测试' }}
      </button>
      <div v-if="fullTestResults.length > 0" class="test-result">
        <h3>测试结果</h3>
        <table>
          <thead>
            <tr>
              <th>测试项</th>
              <th>DOM (ms)</th>
              <th>Pretext (ms)</th>
              <th>加速比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(result, idx) in fullTestResults" :key="idx">
              <td>{{ result.name }}</td>
              <td>{{ result.domTime.toFixed(3) }}</td>
              <td>{{ result.pretextTime.toFixed(3) }}</td>
              <td class="highlight">{{ result.speedup.toFixed(1) }}x</td>
            </tr>
          </tbody>
        </table>
        <p class="summary">
          平均加速比: <span class="highlight">{{ averageSpeedup.toFixed(1) }}x</span>
        </p>
      </div>
    </div>
    
    <div class="info-section">
      <h2>使用说明</h2>
      <p>在浏览器控制台也可以运行测试：</p>
      <code>
        import { runFullTestSuite } from '@/utils/pretext-performance-test'<br>
        runFullTestSuite()
      </code>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { 
  runSingleMessageTest, 
  runBatchMessageTest, 
  runFullTestSuite 
} from '@/utils/pretext-performance-test';

interface TestResult {
  name: string;
  domTime: number;
  pretextTime: number;
  speedup: number;
  iterations: number;
}

const testMessage = ref('这是一条测试消息，用于测试 Pretext.js 的性能。在实际应用中，消息可能会更长，包含更多的内容。');
const isTesting = ref(false);
const singleTestResult = ref<TestResult | null>(null);
const batchTestResult = ref<TestResult | null>(null);
const fullTestResults = ref<TestResult[]>([]);

const averageSpeedup = computed(() => {
  if (fullTestResults.value.length === 0) return 0;
  return fullTestResults.value.reduce((sum, r) => sum + r.speedup, 0) / fullTestResults.value.length;
});

async function runSingleTest() {
  isTesting.value = true;
  try {
    singleTestResult.value = runSingleMessageTest(testMessage.value, 600, 100);
  } finally {
    isTesting.value = false;
  }
}

async function runBatchTest() {
  isTesting.value = true;
  try {
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
    batchTestResult.value = runBatchMessageTest(messages, 600);
  } finally {
    isTesting.value = false;
  }
}

async function runFullTest() {
  isTesting.value = true;
  try {
    fullTestResults.value = runFullTestSuite();
  } finally {
    isTesting.value = false;
  }
}
</script>

<style scoped>
.pretext-test-view {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
}

h1 {
  margin-bottom: 24px;
  color: #333;
}

.test-section {
  background: white;
  border-radius: 8px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

h2 {
  margin-top: 0;
  margin-bottom: 16px;
  color: #555;
  font-size: 18px;
}

.test-input {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

textarea {
  padding: 12px;
  border: 1px solid #d0d0d0;
  border-radius: 6px;
  font-size: 14px;
  resize: vertical;
}

button {
  padding: 10px 20px;
  background: #1976d2;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  align-self: flex-start;
}

button:hover:not(:disabled) {
  background: #1565c0;
}

button:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.test-result {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e0e0e0;
}

h3 {
  margin-top: 0;
  margin-bottom: 12px;
  color: #666;
  font-size: 16px;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #e0e0e0;
}

th {
  font-weight: 600;
  color: #555;
  background: #f5f5f5;
}

.highlight {
  color: #4caf50;
  font-weight: 600;
}

.summary {
  margin-top: 16px;
  padding: 12px;
  background: #e8f5e9;
  border-radius: 6px;
  font-size: 16px;
}

.info-section {
  background: #f5f5f5;
  border-radius: 8px;
  padding: 24px;
}

code {
  display: block;
  background: #263238;
  color: #aed581;
  padding: 16px;
  border-radius: 6px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.5;
  overflow-x: auto;
}
</style>
