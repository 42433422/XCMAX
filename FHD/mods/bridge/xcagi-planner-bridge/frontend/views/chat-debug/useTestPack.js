import { ref, watch, onMounted } from 'vue';
import { appAlert, appConfirm } from '@/utils/appDialog';

/**
 * 拆分自 ChatDebugView.vue 脚本（原第 179–180、204–286、417–443 行）；
 * 逻辑逐字迁移，行为不变。加入测试包依赖输入框内容，inputText 经 deps 注入；
 * localStorage 恢复（onMounted）与持久化（watch）保持原时序。
 */
export function useTestPack(deps) {
  const { inputText } = deps;

  const testPack = ref([]);
  const TEST_PACK_STORAGE_KEY = 'xcagi_intent_test_pack_v1';

  function formatTimeLabel(ts) {
    const d = new Date(ts);
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function buildExportFileName(ext = 'json') {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    return `intent-test-pack-${stamp}.${ext}`;
  }

  function triggerDownload(text, type, fileName) {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function addToTestPack() {
    const text = String(inputText.value || '').trim();
    if (!text) {
      await appAlert('请先输入测试句子');
      return;
    }
    const exists = testPack.value.some(item => item.text === text);
    if (exists) {
      await appAlert('该句子已在测试包中');
      return;
    }
    const now = Date.now();
    testPack.value.push({
      id: `${now}-${Math.random().toString(36).slice(2, 8)}`,
      text,
      createdAt: now,
      timeLabel: formatTimeLabel(now)
    });
  }

  function removeTestCase(id) {
    testPack.value = testPack.value.filter(item => item.id !== id);
  }

  async function clearTestPack() {
    if (!testPack.value.length) return;
    if (!(await appConfirm('确定清空测试包列表吗？', { danger: true }))) return;
    testPack.value = [];
  }

  function exportTestPackJson() {
    if (!testPack.value.length) return;
    const payload = {
      name: '意图测试包',
      exported_at: new Date().toISOString(),
      total: testPack.value.length,
      cases: testPack.value.map((item, idx) => ({
        index: idx + 1,
        text: item.text,
        created_at: new Date(item.createdAt).toISOString()
      }))
    };
    triggerDownload(JSON.stringify(payload, null, 2), 'application/json;charset=utf-8', buildExportFileName('json'));
  }

  function exportTestPackTxt() {
    if (!testPack.value.length) return;
    const lines = [
      '# 意图测试包',
      `# 导出时间: ${new Date().toLocaleString('zh-CN')}`,
      `# 总数: ${testPack.value.length}`,
      ''
    ];
    testPack.value.forEach((item, idx) => {
      lines.push(`${idx + 1}. ${item.text}`);
    });
    triggerDownload(lines.join('\n'), 'text/plain;charset=utf-8', buildExportFileName('txt'));
  }

  onMounted(() => {
    try {
      const raw = localStorage.getItem(TEST_PACK_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;
      testPack.value = parsed
        .map(item => {
          const text = String(item?.text || '').trim();
          const createdAt = Number(item?.createdAt || Date.now());
          if (!text) return null;
          return {
            id: String(item?.id || `${createdAt}-${Math.random().toString(36).slice(2, 8)}`),
            text,
            createdAt,
            timeLabel: formatTimeLabel(createdAt)
          };
        })
        .filter(Boolean);
    } catch (_e) {}
  });

  watch(testPack, (val) => {
    try {
      localStorage.setItem(TEST_PACK_STORAGE_KEY, JSON.stringify(val));
    } catch (_e) {}
  }, { deep: true });

  return {
    testPack, addToTestPack, removeTestCase, clearTestPack, exportTestPackJson, exportTestPackTxt,
  };
}
