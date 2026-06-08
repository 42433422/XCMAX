import { test, expect } from '@playwright/test';
import { imUserHeaders } from './helpers';

/**
 * IM V0：双用户 REST 互发（不依赖 Web UI 登录态，用 X-User-ID 头与后端测试约定一致）。
 */
test.describe('IM V0 双用户互发 @5001', () => {
  test('用户 1 → 用户 2 消息 <3s 可达', async ({ request }) => {
    const health = await request.get('/api/health', { timeout: 15_000 });
    test.skip(!health.ok(), '后端未启动');

    await request.get('/', { timeout: 10_000 });

    const h1 = await imUserHeaders(request, '1');
    const h2 = await imUserHeaders(request, '2');

    const conv = await request.post('/api/im/conversations/direct', {
      headers: h1,
      data: { peer_user_id: 2 },
      timeout: 15_000,
    });
    expect(conv.ok(), await conv.text()).toBeTruthy();
    const convBody = await conv.json();
    const convId = convBody.conversation?.id;
    expect(convId).toBeTruthy();

    const text = `e2e-im-${Date.now()}`;
    const t0 = Date.now();
    const sent = await request.post(`/api/im/conversations/${convId}/messages`, {
      headers: h1,
      data: { body: text },
      timeout: 15_000,
    });
    expect(sent.ok(), await sent.text()).toBeTruthy();

    let found = false;
    for (let i = 0; i < 15; i++) {
      const list = await request.get(`/api/im/conversations/${convId}/messages`, {
        headers: h2,
        timeout: 15_000,
      });
      expect(list.ok()).toBeTruthy();
      const listBody = await list.json();
      const messages = listBody.messages || listBody.data?.messages || [];
      if (Array.isArray(messages) && messages.some((m: { body?: string }) => m.body === text)) {
        found = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 200));
    }

    const elapsed = Date.now() - t0;
    expect(found, 'peer should see message').toBeTruthy();
    expect(elapsed, 'delivery should be under 3s').toBeLessThan(3000);
  });
});
