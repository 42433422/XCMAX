import { describe, expect, it } from 'vitest';
import {
  SIDEBAR_CHAT_NAV_KEY,
  isChatLikePath,
  isChatSidebarActive,
  normalizeSidebarActiveKey,
} from './sidebarActiveKey';

describe('sidebarActiveKey', () => {
  it('isChatLikePath recognizes chat routes', () => {
    expect(isChatLikePath('/')).toBe(true);
    expect(isChatLikePath('/chat')).toBe(true);
    expect(isChatLikePath('/mods/foo/chat')).toBe(true);
    expect(isChatLikePath('/chat-debug')).toBe(false);
  });

  it('normalizeSidebarActiveKey maps planner chat to chat', () => {
    expect(normalizeSidebarActiveKey('mod-planner-chat')).toBe(SIDEBAR_CHAT_NAV_KEY);
    expect(
      normalizeSidebarActiveKey('other', { name: 'mod-planner-chat', path: '/x' }),
    ).toBe(SIDEBAR_CHAT_NAV_KEY);
    expect(normalizeSidebarActiveKey('inventory', { name: 'products', path: '/products' })).toBe(
      'inventory',
    );
  });

  it('isChatSidebarActive checks normalized key', () => {
    expect(
      isChatSidebarActive('mod-planner-chat', { name: 'mod-planner-chat', path: '/chat' }),
    ).toBe(true);
    expect(isChatSidebarActive('settings', { name: 'settings', path: '/settings' })).toBe(false);
  });
});
