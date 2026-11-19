<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { xiaocAdminApi, type XiaoCMemory, type XiaoCMemoryInput } from '../../application/xiaocAdminApi'
import { ApiError } from '../../infrastructure/http/client'
import { errorMessage } from '../../utils/typeNarrowing'

const memories = ref<XiaoCMemory[]>([])
const draft = ref<(XiaoCMemoryInput & { memory_id?: string }) | null>(null)
const busy = ref(false)
const error = ref('')
const loaded = ref(false)

function memoryError(failure: unknown) {
  if (failure instanceof ApiError) {
    if (failure.status === 503) return '小 C 暂时连不上记忆服务，请稍后重试。'
    if (failure.status === 403) return '当前账号无法访问小 C 的私有记忆。'
    if (failure.status === 404) return '这条记忆已不存在，请刷新列表。'
    if (failure.status === 422) return '请检查记忆主题和内容。'
  }
  return errorMessage(failure, '记忆操作失败，请重试。')
}

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await action()
  } catch (failure) {
    error.value = memoryError(failure)
  } finally {
    busy.value = false
  }
}

function refresh() {
  return run(async () => {
    memories.value = []
    loaded.value = false
    memories.value = (await xiaocAdminApi.listMemory()).memories
    loaded.value = true
  })
}

function edit(memory?: XiaoCMemory) {
  error.value = ''
  draft.value = memory
    ? { memory_id: memory.memory_id, key: memory.key, statement: memory.statement }
    : { key: '', statement: '' }
}

function save() {
  if (!draft.value) return
  const { memory_id, key, statement } = draft.value
  const input = { key: key.trim(), statement: statement.trim() }
  if (!input.key || !input.statement) {
    error.value = '请填写记忆主题和内容。'
    return
  }
  return run(async () => {
    const { memory } = await xiaocAdminApi.saveMemory(input, memory_id)
    memories.value = [memory, ...memories.value.filter((entry) => entry.memory_id !== memory.memory_id)]
    draft.value = null
  })
}

function remove(memory: XiaoCMemory) {
  if (!window.confirm(`删除「${memory.key}」？小 C 往后将不再使用这条记忆。`)) return
  return run(async () => {
    await xiaocAdminApi.deleteMemory(memory.memory_id)
    memories.value = memories.value.filter((entry) => entry.memory_id !== memory.memory_id)
  })
}

onMounted(refresh)
</script>

<template>
  <section aria-label="我的记忆" :aria-busy="busy">
    <p class="xiaoc-muted">把希望小 C 在下次对话中沿用的工作偏好和约定记下来。</p>
    <div v-if="!draft" class="xiaoc-toolbar">
      <button type="button" :disabled="busy || !loaded" @click="edit()">新增记忆</button>
      <button type="button" :disabled="busy" @click="refresh">刷新</button>
      <span v-if="busy" class="xiaoc-muted" role="status">正在处理…</span>
    </div>
    <p v-if="error" class="xiaoc-error" role="alert">{{ error }}</p>

    <form v-if="draft" class="memory-form" @submit.prevent="save">
      <label>
        主题
        <input v-model="draft.key" :disabled="busy" maxlength="80" required placeholder="例如：交付口径" />
      </label>
      <label>
        内容
        <textarea v-model="draft.statement" :disabled="busy" maxlength="600" rows="4" required />
      </label>
      <div class="xiaoc-toolbar">
        <button type="submit" :disabled="busy">保存</button>
        <button type="button" :disabled="busy" @click="draft = null; error = ''">取消</button>
      </div>
    </form>

    <ul v-else-if="memories.length" class="memory-list">
      <li v-for="memory in memories" :key="memory.memory_id">
        <strong>{{ memory.key }}</strong>
        <p class="memory-statement">{{ memory.statement }}</p>
        <span v-if="memory.source === 'settings_ui'" class="xiaoc-muted">你手动保存</span>
        <div class="xiaoc-toolbar">
          <button type="button" :disabled="busy" @click="edit(memory)">修改</button>
          <button type="button" :disabled="busy" @click="remove(memory)">删除</button>
        </div>
      </li>
    </ul>
    <p v-else-if="loaded && !busy && !error" class="xiaoc-muted">还没有保存的记忆。</p>
  </section>
</template>

<style scoped>
.memory-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.memory-list li { padding: 10px; border: 1px solid var(--xiaoc-border); border-radius: 8px; }
.memory-statement { margin: 6px 0; white-space: pre-wrap; }
.memory-form, .memory-form label { display: grid; gap: 6px; }
.memory-form { gap: 10px; }
.memory-form input, .memory-form textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 6px 8px;
  color: inherit;
  border: 1px solid var(--xiaoc-border);
  border-radius: 7px;
  background: var(--xiaoc-bg);
  font: inherit;
}
.memory-form textarea { resize: vertical; }
</style>
