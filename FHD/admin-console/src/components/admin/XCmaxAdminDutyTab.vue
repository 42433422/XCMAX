<template>
  <div class="xcmax-admin-duty">
    <div class="duty-actions">
      <router-link class="btn btn-primary btn-sm" :to="{ name: 'duty-roster-graph' }">
        <i class="fa fa-sitemap" aria-hidden="true"></i>
        打开日更全链路编制图
      </router-link>
      <button
        class="btn btn-secondary btn-sm"
        type="button"
        :disabled="staffingBusy"
        @click="runOnboard"
      >
        登记缺岗到 Catalog
      </button>
      <button
        class="btn btn-secondary btn-sm"
        type="button"
        :disabled="staffingBusy || !firstMissing"
        @click="installFirstMissing"
      >
        安装首个缺岗到本地
      </button>
    </div>
    <XCmaxAdminOpsTab />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import XCmaxAdminOpsTab from '@/components/admin/XCmaxAdminOpsTab.vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { appAlert } from '@/utils/appDialog'
import { buildDutyRosterRows } from '@/utils/dutyRosterEmployeeList'

const staffingBusy = ref(false)
const missingIds = ref<string[]>([])

const firstMissing = computed(() => missingIds.value[0] || '')

async function loadMissing() {
  try {
    const health = await xcmaxOpsApi.dutyHealth()
    const h = health && typeof health === 'object' ? (health as Record<string, unknown>) : {}
    missingIds.value = buildDutyRosterRows(h)
      .filter((r) => r.status === 'missing')
      .map((r) => r.pkgId)
  } catch {
    missingIds.value = []
  }
}

async function runOnboard() {
  staffingBusy.value = true
  try {
    await loadMissing()
    const res = await xcmaxOpsApi.staffingOnboard({
      employee_ids: missingIds.value,
      dry_run: false,
    })
    await appAlert(JSON.stringify(res, null, 2).slice(0, 500) || '已提交登记')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    staffingBusy.value = false
  }
}

async function installFirstMissing() {
  if (!firstMissing.value) return
  staffingBusy.value = true
  try {
    const res = await xcmaxOpsApi.staffingInstallLocal({ employee_id: firstMissing.value })
    await appAlert(JSON.stringify(res, null, 2).slice(0, 500) || '已触发本地安装')
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    staffingBusy.value = false
  }
}

void loadMissing()
</script>

<style scoped>
.xcmax-admin-duty {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.duty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}
.btn-primary {
  background: #1890ff;
  color: #fff;
}
.btn-secondary {
  background: rgba(24, 144, 255, 0.1);
  color: #1890ff;
}
.btn:disabled {
  opacity: 0.55;
}
</style>
