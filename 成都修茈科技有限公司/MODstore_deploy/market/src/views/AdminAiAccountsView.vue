<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：账号池 CRUD/QQ 桥接逻辑在 ./admin-ai-accounts/，
// 样式在 ./admin-ai-accounts/adminAiAccounts.css。defineExpose 面保持不变。
import { useAdminAiAccounts } from './admin-ai-accounts/useAdminAiAccounts'

/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问 */
const {
  router, isAdmin, loading, error, items, total,
  filterPlatform, filterEmployee, filterStatus, qqStatus,
  createOpen, createForm, createBusy,
  rotateOpenId, rotateForm, rotateBusy,
  editOpenId, editForm, editBusy,
  host, fullWebhookList, loadAll,
  openCreate, closeCreate, submitCreate,
  openEdit, closeEdit, submitEdit,
  openRotate, closeRotate, submitRotate,
  removeAccount, copyText,
} = useAdminAiAccounts()
/* eslint-enable @typescript-eslint/no-unused-vars */

defineExpose({ fullWebhookList })
</script>

<template>
  <div v-if="!isAdmin" class="aa-denied">
    <p>需要管理员权限</p>
    <button type="button" class="btn" @click="router.push('/')">返回首页</button>
  </div>
  <div v-else class="aa-page">
    <header class="aa-head">
      <div>
        <h1>AI 员工账号池</h1>
        <p class="aa-lead">管理 AI 员工的外部平台账号与密钥。</p>
      </div>
      <div class="aa-actions">
        <button type="button" class="btn ghost" :disabled="loading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <button type="button" class="btn primary" @click="openCreate">+ 新建账号</button>
      </div>
    </header>

    <p v-if="error" class="aa-err">{{ error }}</p>

    <!-- ─── QQ 桥接状态 ───────────────────────────────── -->
    <section v-if="qqStatus" class="aa-card">
      <h2>QQ 桥接</h2>
      <p>
        <span :class="qqStatus.configured ? 'ok' : 'bad'">{{ qqStatus.configured ? '已连接' : '未配置' }}</span>
        <span class="muted"> · {{ qqStatus.credential_source || '-' }} · {{ qqStatus.sandbox ? '沙箱' : '正式' }}</span>
      </p>
      <ul v-if="qqStatus.first_class_employees?.length" class="aa-fc-list">
        <li v-for="emp in qqStatus.first_class_employees" :key="emp.employee_id" class="aa-fc-item">
          <p>
            <strong>{{ emp.employee_id }}</strong>
            <span class="muted">AppID {{ emp.app_id }}</span>
            <span :class="emp.app_secret_present ? 'ok' : 'bad'">{{ emp.app_secret_present ? '✓' : '✕ 密钥缺失' }}</span>
          </p>
          <ul class="aa-url-list">
            <li>
              <code class="aa-code">{{ host() }}{{ emp.by_employee_path }}</code>
              <button type="button" class="btn link" @click="copyText(host() + emp.by_employee_path)">复制</button>
            </li>
          </ul>
        </li>
      </ul>
    </section>

    <!-- ─── 过滤 + 列表 ───────────────────────────────── -->
    <section class="aa-card">
      <div class="aa-filters">
        <label class="aa-field">
          <span>平台</span>
          <select v-model="filterPlatform" class="aa-input" @change="loadAll">
            <option value="">全部</option>
            <option value="qq">qq</option>
            <option value="wechat">wechat</option>
            <option value="email">email</option>
            <option value="slack">slack</option>
            <option value="feishu">feishu</option>
            <option value="discord">discord</option>
          </select>
        </label>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="filterEmployee" class="aa-input" placeholder="如 task-router-officer" @change="loadAll" />
        </label>
        <label class="aa-field">
          <span>状态</span>
          <select v-model="filterStatus" class="aa-input" @change="loadAll">
            <option value="">全部</option>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
        <p class="muted aa-total">共 {{ total }} 条</p>
      </div>

      <div v-if="loading && !items.length" class="muted">加载中…</div>
      <div v-else-if="!items.length" class="muted">暂无账号</div>
      <table v-else class="aa-table">
        <thead>
          <tr>
            <th>#</th>
            <th>平台</th>
            <th>外部 ID</th>
            <th>员工</th>
            <th>状态</th>
            <th>沙箱</th>
            <th>密钥</th>
            <th>入站 URL</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in items" :key="a.id">
            <td>{{ a.id }}</td>
            <td>{{ a.platform }}</td>
            <td><code class="aa-code">{{ a.external_id }}</code></td>
            <td>
              <code class="aa-code">{{ a.employee_id }}</code>
              <p v-if="a.display_name" class="muted">{{ a.display_name }}</p>
            </td>
            <td :class="a.status === 'active' ? 'ok' : 'bad'">{{ a.status }}</td>
            <td>{{ a.sandbox ? '是' : '否' }}</td>
            <td :class="a.has_secret ? 'ok' : 'bad'">{{ a.has_secret ? '已落地' : '缺失' }}</td>
            <td>
              <ul v-if="(a.channel?.paths?.length || 0) > 0" class="aa-url-list">
                <li v-for="p in a.channel.paths" :key="p.path">
                  <span class="muted">{{ p.label }}：</span>
                  <code class="aa-code">{{ host() }}{{ p.path }}</code>
                  <button type="button" class="btn link" @click="copyText(host() + p.path)">复制</button>
                </li>
              </ul>
              <span v-else class="muted">该平台暂未导出 URL</span>
            </td>
            <td class="aa-row-actions">
              <button type="button" class="btn link" @click="openEdit(a)">编辑</button>
              <button type="button" class="btn link" @click="openRotate(a)">轮换密钥</button>
              <button type="button" class="btn link bad" @click="removeAccount(a)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- ─── 新建对话框 ───────────────────────────────── -->
    <div v-if="createOpen" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>新建 AI 员工账号</h2>
        <label class="aa-field">
          <span>平台</span>
          <select v-model="createForm.platform" class="aa-input">
            <option value="qq">qq</option>
            <option value="wechat" disabled>wechat（暂未实现）</option>
            <option value="email" disabled>email（暂未实现）</option>
          </select>
        </label>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="createForm.employee_id" class="aa-input" placeholder="如 task-router-officer" />
        </label>
        <label class="aa-field">
          <span>external_id（QQ 号 / AppID）</span>
          <input v-model="createForm.external_id" class="aa-input" placeholder="如 1903978019" />
        </label>
        <label class="aa-field">
          <span>显示名称（可选）</span>
          <input v-model="createForm.display_name" class="aa-input" placeholder="如 任务路由员主号" />
        </label>
        <label class="aa-field">
          <span>备注（可选）</span>
          <textarea v-model="createForm.notes" class="aa-input" rows="2" />
        </label>
        <label class="aa-check">
          <input v-model="createForm.sandbox" type="checkbox" />
          <span>使用 QQ 沙箱环境</span>
        </label>
        <template v-if="createForm.platform === 'qq'">
          <h3>QQ 凭证</h3>
          <label class="aa-field">
            <span>app_id</span>
            <input v-model="createForm.app_id" class="aa-input" />
          </label>
          <label class="aa-field">
            <span>app_secret</span>
            <input v-model="createForm.app_secret" class="aa-input" type="password" autocomplete="off" />
          </label>
          <label class="aa-field">
            <span>bot_token</span>
            <input v-model="createForm.bot_token" class="aa-input" type="password" autocomplete="off" />
          </label>
        </template>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="createBusy" @click="closeCreate">取消</button>
          <button type="button" class="btn primary" :disabled="createBusy" @click="submitCreate">
            {{ createBusy ? '提交中…' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ─── 编辑对话框 ───────────────────────────────── -->
    <div v-if="editOpenId != null" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>编辑账号 #{{ editOpenId }}</h2>
        <label class="aa-field">
          <span>employee_id</span>
          <input v-model="editForm.employee_id" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>显示名称</span>
          <input v-model="editForm.display_name" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>状态</span>
          <select v-model="editForm.status" class="aa-input">
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
        <label class="aa-check">
          <input v-model="editForm.sandbox" type="checkbox" />
          <span>使用 QQ 沙箱</span>
        </label>
        <label class="aa-field">
          <span>备注</span>
          <textarea v-model="editForm.notes" class="aa-input" rows="2" />
        </label>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="editBusy" @click="closeEdit">取消</button>
          <button type="button" class="btn primary" :disabled="editBusy" @click="submitEdit">
            {{ editBusy ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ─── 轮换密钥对话框 ────────────────────────────── -->
    <div v-if="rotateOpenId != null" class="aa-modal" role="dialog">
      <div class="aa-modal-body">
        <h2>轮换密钥（账号 #{{ rotateOpenId }}）</h2>
        <p class="muted">提交后会**覆盖**密钥文件，旧密钥立刻作废。</p>
        <label class="aa-field">
          <span>app_id</span>
          <input v-model="rotateForm.app_id" class="aa-input" />
        </label>
        <label class="aa-field">
          <span>app_secret</span>
          <input v-model="rotateForm.app_secret" class="aa-input" type="password" autocomplete="off" />
        </label>
        <label class="aa-field">
          <span>bot_token</span>
          <input v-model="rotateForm.bot_token" class="aa-input" type="password" autocomplete="off" />
        </label>
        <div class="aa-modal-actions">
          <button type="button" class="btn ghost" :disabled="rotateBusy" @click="closeRotate">取消</button>
          <button type="button" class="btn primary" :disabled="rotateBusy" @click="submitRotate">
            {{ rotateBusy ? '提交中…' : '提交轮换' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="./admin-ai-accounts/adminAiAccounts.css"></style>
