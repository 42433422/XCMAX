<template>
  <div
    class="perm-overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="perm-title"
    @click.self="$emit('dismiss')"
  >
    <div class="perm-card">
      <div class="perm-icon"><svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="3" y="4" width="10" height="7" rx="1.5"/><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5"/></svg></div>
      <h2 id="perm-title" class="perm-title">AI 数字管家 — 隐私提示</h2>
      <p class="perm-sub">为了提供更好的服务，AI 助手需要：</p>
      <ul class="perm-list">
        <li>📊 记录您的使用习惯，以便主动建议</li>
        <li>📄 读取当前页面内容，以便理解上下文</li>
        <li>🖱️ 代替您执行操作，提高使用效率</li>
      </ul>
      <p class="perm-note">所有数据仅用于改善您的使用体验，不会分享给第三方。</p>
      <div class="perm-actions">
        <button type="button" class="perm-btn perm-btn--primary" @click="$emit('agree')">
          同意并继续
        </button>
        <button type="button" class="perm-btn perm-btn--ghost" @click="$emit('dismiss')">
          稍后再说
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineEmits<{
  (e: 'agree'): void
  (e: 'dismiss'): void
}>()
</script>

<style scoped>
.perm-overlay {
  position: fixed;
  inset: 0;
  z-index: 12100;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  backdrop-filter: blur(4px);
}

.perm-card {
  width: min(400px, 100%);
  background: #141414;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  padding: 28px 24px 22px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
  text-align: center;
}

.perm-icon {
  font-size: 2.5rem;
  margin-bottom: 10px;
}

.perm-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #fff;
  margin: 0 0 8px;
}

.perm-sub {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
  margin: 0 0 12px;
}

.perm-list {
  list-style: none;
  padding: 0;
  margin: 0 0 14px;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.perm-list li {
  font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.75);
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 8px;
}

.perm-note {
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.4);
  margin: 0 0 20px;
  line-height: 1.4;
}

.perm-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
}

.perm-btn {
  padding: 9px 22px;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}

.perm-btn--primary {
  background: linear-gradient(135deg, #00dcff, #0080ff);
  color: #fff;
}

.perm-btn--primary:hover {
  opacity: 0.9;
}

.perm-btn--ghost {
  background: rgba(255, 255, 255, 0.07);
  color: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.perm-btn--ghost:hover {
  background: rgba(255, 255, 255, 0.12);
}
</style>
