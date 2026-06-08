<script setup lang="ts">
interface DocLink {
  href: string
  title: string
  description: string
  badge?: string
}

const interactive: DocLink[] = [
  {
    href: '/docs',
    title: 'Swagger UI',
    description: '所有 REST 路由的交互式文档，可直接发请求调试',
  },
  {
    href: '/redoc',
    title: 'ReDoc',
    description: '更清爽的 API 浏览界面，适合阅读模型 schema',
  },
  {
    href: '/openapi.json',
    title: 'OpenAPI JSON',
    description: '机器可读的 spec，用来生成 SDK 或 diff breaking change',
  },
]

const guides: DocLink[] = [
  {
    href: '/dev-docs/developer/README.md',
    title: '总览',
    description: '从这里开始：6 篇核心文档的索引与脚本说明',
  },
  {
    href: '/dev-docs/developer/01-quickstart.md',
    title: '01 · Quickstart',
    description: '5 分钟跑通：拿到 Token → 触发员工 → 收到 webhook',
    badge: '推荐起步',
  },
  {
    href: '/dev-docs/developer/02-authentication.md',
    title: '02 · 认证',
    description: 'PAT 与 JWT 双轨认证、scope 设计、安全建议',
  },
  {
    href: '/dev-docs/developer/03-rest-api.md',
    title: '03 · REST API 索引',
    description: '按业务模块分组的端到端调用清单',
  },
  {
    href: '/dev-docs/developer/04-webhooks.md',
    title: '04 · Webhooks',
    description: '出站订阅 + 入站工作流触发、HMAC 验签、调试技巧',
  },
  {
    href: '/dev-docs/developer/04a-event-reference.md',
    title: '04a · 事件参考',
    description: '所有可订阅事件清单与 envelope（自动生成）',
    badge: '自动生成',
  },
  {
    href: '/dev-docs/developer/05-sdk-examples.md',
    title: '05 · 代码示例',
    description: 'Python / TypeScript / curl 三个最常见场景',
  },
  {
    href: '/dev-docs/developer/06-errors-and-limits.md',
    title: '06 · 错误与生产约束',
    description: '状态码、quota、重试、安全约束、速率限制',
  },
]

const contracts: DocLink[] = [
  {
    href: '/dev-docs/contracts/openapi/modstore-server.json',
    title: 'OpenAPI 静态快照',
    description: 'CI 用此文件 diff 检测破坏性变更',
  },
  {
    href: '/dev-docs/contracts/events/README.md',
    title: '事件契约（envelope）',
    description: 'NeuroBus envelope 与跨服务事件命名约定',
  },
]
</script>

<template>
  <div class="docs">
    <section class="docs__section">
      <h2 class="docs__h2">交互式 API 文档</h2>
      <div class="docs__grid">
        <a
          v-for="d in interactive"
          :key="d.href"
          class="docs-card"
          :href="d.href"
          target="_blank"
          rel="noreferrer"
        >
          <h3 class="docs-card__title">{{ d.title }} <span class="docs-card__arrow">↗</span></h3>
          <p class="docs-card__desc">{{ d.description }}</p>
        </a>
      </div>
    </section>

    <section class="docs__section">
      <h2 class="docs__h2">开发者手册</h2>
      <div class="docs__grid">
        <a
          v-for="d in guides"
          :key="d.href"
          class="docs-card"
          :href="d.href"
          target="_blank"
          rel="noreferrer"
        >
          <h3 class="docs-card__title">
            {{ d.title }}
            <span v-if="d.badge" class="docs-card__badge">{{ d.badge }}</span>
            <span class="docs-card__arrow">↗</span>
          </h3>
          <p class="docs-card__desc">{{ d.description }}</p>
        </a>
      </div>
    </section>

    <section class="docs__section">
      <h2 class="docs__h2">机器可读契约</h2>
      <div class="docs__grid">
        <a
          v-for="d in contracts"
          :key="d.href"
          class="docs-card"
          :href="d.href"
          target="_blank"
          rel="noreferrer"
        >
          <h3 class="docs-card__title">{{ d.title }} <span class="docs-card__arrow">↗</span></h3>
          <p class="docs-card__desc">{{ d.description }}</p>
        </a>
      </div>
    </section>

    <section class="docs__tip">
      <strong>更新文档：</strong>
      改完 API 后，跑 <code>python scripts/export_openapi.py</code> 刷新 OpenAPI 快照；
      改完事件契约后，跑 <code>python scripts/generate_event_reference.py</code> 重新生成事件参考页。
      CI 通过 <code>--check</code> 模式拦截过期快照。
    </section>
  </div>
</template>

<style scoped>
.docs {
  display: flex;
  flex-direction: column;
  gap: 28px;
  color: rgba(248, 250, 252, 0.92);
}

.docs__h2 {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
  color: #ffffff;
}

.docs__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.docs-card {
  display: block;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  padding: 14px 16px;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}

.docs-card:hover {
  border-color: rgba(129, 140, 248, 0.55);
  transform: translateY(-2px);
  box-shadow: 0 12px 28px -12px rgba(0, 0, 0, 0.55);
}

.docs-card__title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #f8fafc;
  display: flex;
  align-items: center;
  gap: 6px;
}

.docs-card__arrow {
  color: rgba(148, 163, 184, 0.85);
  font-size: 12px;
}

.docs-card__badge {
  font-size: 10px;
  background: rgba(234, 179, 8, 0.15);
  color: #fbbf24;
  padding: 1px 7px;
  border-radius: 999px;
  letter-spacing: 0.04em;
  font-weight: 500;
}

.docs-card__desc {
  margin: 6px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.5;
}

.docs__tip {
  background: rgba(0, 0, 0, 0.22);
  border: 1px dashed rgba(255, 255, 255, 0.12);
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.6;
}

.docs__tip code {
  background: rgba(15, 23, 42, 0.75);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  color: #e2e8f0;
}
</style>
