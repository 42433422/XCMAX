import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  runSingleMessageTest,
  runBatchMessageTest,
  runFullTestSuite,
  default as defaultExport,
} from './pretext-performance-test';

// Mock pretext 模块以避免依赖实际测量
vi.mock('./pretext', () => ({
  measureText: vi.fn(() => ({ width: 100, height: 20, lines: 1 })),
  batchMeasure: vi.fn((items: unknown[]) =>
    items.map(() => ({ width: 100, height: 20, lines: 1 }))
  ),
}));

// Mock console 方法以验证输出
describe('pretext-performance-test', () => {
  beforeEach(() => {
    vi.spyOn(console, 'group').mockImplementation(() => undefined as never);
    vi.spyOn(console, 'groupEnd').mockImplementation(() => undefined as never);
    vi.spyOn(console, 'log').mockImplementation(() => undefined as never);
    vi.spyOn(console, 'table').mockImplementation(() => undefined as never);
  });

  describe('runSingleMessageTest', () => {
    it('返回包含正确字段的测试结果', () => {
      const result = runSingleMessageTest('测试消息', 600, 10);
      expect(result).toHaveProperty('name');
      expect(result).toHaveProperty('domTime');
      expect(result).toHaveProperty('pretextTime');
      expect(result).toHaveProperty('speedup');
      expect(result).toHaveProperty('iterations', 10);
    });

    it('名称包含消息字符数', () => {
      const msg = '你好世界';
      const result = runSingleMessageTest(msg, 600, 5);
      expect(result.name).toContain(String(msg.length));
    });

    it('使用默认宽度和迭代次数', () => {
      const result = runSingleMessageTest('默认');
      expect(result.iterations).toBe(100);
    });

    it('domTime 和 pretextTime 为非负数', () => {
      const result = runSingleMessageTest('测试', 600, 5);
      expect(result.domTime).toBeGreaterThanOrEqual(0);
      expect(result.pretextTime).toBeGreaterThanOrEqual(0);
    });

    it('speedup 为 domTime / pretextTime', () => {
      const result = runSingleMessageTest('测试', 600, 5);
      if (result.pretextTime > 0) {
        expect(result.speedup).toBeCloseTo(result.domTime / result.pretextTime, 5);
      }
    });

    it('处理空消息', () => {
      const result = runSingleMessageTest('', 600, 5);
      expect(result.iterations).toBe(5);
      expect(typeof result.domTime).toBe('number');
    });

    it('处理单次迭代', () => {
      const result = runSingleMessageTest('单次', 600, 1);
      expect(result.iterations).toBe(1);
    });

    it('处理大宽度', () => {
      const result = runSingleMessageTest('大宽度', 2000, 3);
      expect(result.iterations).toBe(3);
    });

    it('处理小宽度', () => {
      const result = runSingleMessageTest('小宽度', 100, 3);
      expect(result.iterations).toBe(3);
    });
  });

  describe('runBatchMessageTest', () => {
    it('返回包含正确字段的结果', () => {
      const result = runBatchMessageTest(['消息1', '消息2'], 600);
      expect(result).toHaveProperty('name');
      expect(result).toHaveProperty('domTime');
      expect(result).toHaveProperty('pretextTime');
      expect(result).toHaveProperty('speedup');
      expect(result).toHaveProperty('iterations', 100);
    });

    it('名称包含消息数量', () => {
      const result = runBatchMessageTest(['a', 'b', 'c'], 600);
      expect(result.name).toContain('3');
    });

    it('使用默认宽度', () => {
      const result = runBatchMessageTest(['消息']);
      expect(result.iterations).toBe(100);
    });

    it('处理空数组', () => {
      const result = runBatchMessageTest([], 600);
      expect(result.iterations).toBe(100);
      expect(typeof result.domTime).toBe('number');
    });

    it('处理单条消息数组', () => {
      const result = runBatchMessageTest(['单条'], 600);
      expect(result.name).toContain('1');
    });

    it('处理大量消息', () => {
      const messages = Array.from({ length: 50 }, (_, i) => `消息${i}`);
      const result = runBatchMessageTest(messages, 600);
      expect(result.name).toContain('50');
    });
  });

  describe('runFullTestSuite', () => {
    it('返回测试结果数组', () => {
      const results = runFullTestSuite();
      expect(Array.isArray(results)).toBe(true);
      expect(results.length).toBeGreaterThan(0);
    });

    it('包含单条消息测试结果（短/中/长）', () => {
      const results = runFullTestSuite();
      // 3 个单条消息测试 + 1 个批量测试 = 4
      expect(results.length).toBe(4);
    });

    it('每个结果都有完整字段', () => {
      const results = runFullTestSuite();
      for (const r of results) {
        expect(r).toHaveProperty('name');
        expect(r).toHaveProperty('domTime');
        expect(r).toHaveProperty('pretextTime');
        expect(r).toHaveProperty('speedup');
        expect(r).toHaveProperty('iterations');
      }
    });

    it('调用 console.group 和 groupEnd', () => {
      runFullTestSuite();
      expect(console.group).toHaveBeenCalled();
      expect(console.groupEnd).toHaveBeenCalled();
    });

    it('调用 console.table 显示结果', () => {
      runFullTestSuite();
      expect(console.table).toHaveBeenCalled();
    });

    it('调用 console.log 输出进度', () => {
      runFullTestSuite();
      expect(console.log).toHaveBeenCalled();
    });
  });

  describe('default export', () => {
    it('包含所有导出函数', () => {
      expect(defaultExport.runSingleMessageTest).toBe(runSingleMessageTest);
      expect(defaultExport.runBatchMessageTest).toBe(runBatchMessageTest);
      expect(defaultExport.runFullTestSuite).toBe(runFullTestSuite);
    });

    it('default.runSingleMessageTest 可正常调用', () => {
      const result = defaultExport.runSingleMessageTest('默认导出', 600, 3);
      expect(result.iterations).toBe(3);
    });

    it('default.runBatchMessageTest 可正常调用', () => {
      const result = defaultExport.runBatchMessageTest(['a', 'b'], 600);
      expect(result.iterations).toBe(100);
    });

    it('default.runFullTestSuite 可正常调用', () => {
      const results = defaultExport.runFullTestSuite();
      expect(results.length).toBe(4);
    });
  });
});
