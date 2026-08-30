<script setup lang="ts">
  import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
  import { xcmaxAdminApi, type DiagnosticTerminalResult } from '../api/xcmaxAdmin';
  import { xcmaxAutomationPolicyOpenUrl } from '../constants/xcmaxDashboardEmbed';

  type Entry = {
    id: number;
    command: string;
    startedAt: string;
    result?: DiagnosticTerminalResult;
    error?: string;
  };

  const commandInput = ref('');
  const commandField = ref<HTMLInputElement | null>(null);
  const outputPanel = ref<HTMLElement | null>(null);
  const entries = ref<Entry[]>([]);
  const running = ref(false);
  const history = ref<string[]>([]);
  const historyIndex = ref(-1);
  let nextId = 1;

  const quickCommands = [
    ['一键体检', 'doctor'],
    ['当前问题', 'problems'],
    ['异常任务', 'scheduler failing'],
    ['错误日志', 'logs error --limit 20'],
    ['交付卡点', 'delivery pending'],
    ['健康路由', 'routes health'],
  ];
  const statusLabels: Record<string, string> = {
    healthy: '正常',
    attention: '需关注',
    degraded: '异常',
    info: '信息',
  };

  const stringify = (value: unknown) => JSON.stringify(value, null, 2);
  const statusLabel = (status: string) => statusLabels[status] || status || '未知';
  function metric(value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }

  async function scrollLatest(): Promise<void> {
    await nextTick();
    if (outputPanel.value) outputPanel.value.scrollTop = outputPanel.value.scrollHeight;
  }

  async function runCommand(raw?: string): Promise<void> {
    const command = String(raw ?? commandInput.value).trim() || 'doctor';
    if (command === 'clear' || command === '清屏') {
      entries.value = [];
      commandInput.value = '';
      return;
    }
    if (running.value) return;
    running.value = true;
    if (history.value.at(-1) !== command) history.value.push(command);
    historyIndex.value = history.value.length;
    commandInput.value = '';
    const entry: Entry = { id: nextId++, command, startedAt: new Date().toISOString() };
    entries.value.push(entry);
    await scrollLatest();
    try {
      entry.result = await xcmaxAdminApi.executeDiagnosticTerminalCommand(command);
    } catch (error: unknown) {
      entry.error = error instanceof Error ? error.message : String(error || '诊断请求失败');
    } finally {
      running.value = false;
      await scrollLatest();
      commandField.value?.focus();
    }
  }

  function moveHistory(direction: -1 | 1): void {
    if (!history.value.length) return;
    historyIndex.value = Math.max(
      0,
      Math.min(history.value.length, historyIndex.value + direction)
    );
    commandInput.value =
      historyIndex.value === history.value.length ? '' : history.value[historyIndex.value] || '';
  }

  async function copyResult(result: DiagnosticTerminalResult): Promise<void> {
    await navigator.clipboard.writeText(stringify(result));
  }

  function exportResult(entry: Entry): void {
    if (!entry.result) return;
    const url = URL.createObjectURL(
      new Blob([stringify(entry.result)], { type: 'application/json;charset=utf-8' })
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `xcmax-diagnostic-${entry.result.command}-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function globalShortcut(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      commandField.value?.focus();
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', globalShortcut);
    void runCommand('doctor');
  });
  onBeforeUnmount(() => window.removeEventListener('keydown', globalShortcut));
</script>

<template>
  <main id="view-diagnostic-terminal" class="diagnostic-terminal-view">
    <header class="terminal-header">
      <div>
        <div class="terminal-title">
          <i class="fa fa-terminal" aria-hidden="true"></i>
          <h2>XC 诊断终端</h2>
          <span>只读</span>
        </div>
        <p>跨账号、交付、调度器、事件、日志与 API 路由快速定位问题；命令为白名单，不执行 Shell。</p>
      </div>
      <div class="header-actions">
        <a :href="xcmaxAutomationPolicyOpenUrl()" target="_blank" rel="noopener noreferrer"
          >全景监控</a
        >
        <button type="button" @click="runCommand('help')">命令帮助</button>
      </div>
    </header>

    <section class="quick-commands" aria-label="常用诊断命令">
      <button
        v-for="item in quickCommands"
        :key="item[1]"
        type="button"
        :disabled="running"
        @click="runCommand(item[1])"
      >
        <strong>{{ item[0] }}</strong
        ><code>{{ item[1] }}</code>
      </button>
    </section>

    <section ref="outputPanel" class="terminal-output" aria-live="polite">
      <article v-for="entry in entries" :key="entry.id" class="terminal-entry">
        <div class="command-line">
          <b>xcmax&gt;</b><code>{{ entry.command }}</code
          ><time>{{ new Date(entry.startedAt).toLocaleTimeString() }}</time>
        </div>
        <div v-if="entry.error" class="terminal-error">
          <strong>命令失败</strong><span>{{ entry.error }}</span
          ><button @click="runCommand(entry.command)">重试</button>
        </div>
        <p v-else-if="!entry.result" class="terminal-running">
          <i class="fa fa-circle-o-notch fa-spin"></i> 正在读取真实运行状态…
        </p>
        <div v-else class="terminal-result">
          <div class="result-head">
            <span :class="`status-${entry.result.status}`">{{
              statusLabel(entry.result.status)
            }}</span>
            <strong>{{ entry.result.summary }}</strong
            ><small>{{ entry.result.elapsed_ms }} ms</small>
            <div>
              <button @click="copyResult(entry.result)">复制 JSON</button
              ><button @click="exportResult(entry)">导出</button>
            </div>
          </div>
          <dl v-if="Object.keys(entry.result.metrics || {}).length" class="metrics">
            <div v-for="(value, key) in entry.result.metrics" :key="key">
              <dt>{{ key }}</dt>
              <dd :title="metric(value)">{{ metric(value) }}</dd>
            </div>
          </dl>
          <div v-if="entry.result.items.length" class="evidence-list">
            <article
              v-for="(item, index) in entry.result.items"
              :key="`${item.kind}-${item.reference || index}`"
              :class="`severity-${item.severity}`"
            >
              <i></i>
              <div>
                <div class="evidence-title">
                  <span>{{ item.kind }}</span
                  ><strong>{{ item.title }}</strong>
                </div>
                <p v-if="item.detail">{{ item.detail }}</p>
                <small>{{
                  [item.source, item.reference, item.timestamp].filter(Boolean).join(' · ')
                }}</small>
                <details v-if="item.data">
                  <summary>结构化证据</summary>
                  <pre>{{ stringify(item.data) }}</pre>
                </details>
              </div>
            </article>
          </div>
          <p v-else class="empty">没有匹配证据。</p>
          <ul v-if="entry.result.hints.length" class="hints">
            <li v-for="hint in entry.result.hints" :key="hint">{{ hint }}</li>
          </ul>
        </div>
      </article>
    </section>

    <form class="command-form" @submit.prevent="runCommand()">
      <label for="diagnostic-command">xcmax&gt;</label>
      <input
        id="diagnostic-command"
        ref="commandField"
        v-model="commandInput"
        autocomplete="off"
        spellcheck="false"
        placeholder="doctor / find 关键词 / account 用户名 / logs error"
        :disabled="running"
        @keydown.up.prevent="moveHistory(-1)"
        @keydown.down.prevent="moveHistory(1)"
      />
      <kbd>⌘K</kbd
      ><button type="submit" :disabled="running">{{ running ? '查询中' : '执行' }}</button>
      <button type="button" class="clear" :disabled="running" @click="runCommand('clear')">
        清屏
      </button>
    </form>
  </main>
</template>

<style scoped src="./DiagnosticTerminalView.css"></style>
