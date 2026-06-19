import { describe, it, expect, vi, beforeEach } from 'vitest';
import { parseDatasetFile, KITTEN_DATASET_SAMPLE_LIMIT } from './kittenDatasetParser';

// 辅助：创建带 text() 方法的 File 对象（jsdom 的 File 可能不支持 text/arrayBuffer）
function createFile(content: string, name: string, type: string): File {
  const file = new File([content], name, { type });
  // 确保 text() 方法可用
  if (typeof file.text !== 'function') {
    Object.defineProperty(file, 'text', {
      value: () => Promise.resolve(content),
      configurable: true,
    });
  }
  // 确保 arrayBuffer() 方法可用
  if (typeof file.arrayBuffer !== 'function') {
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(new TextEncoder().encode(content).buffer),
      configurable: true,
    });
  }
  return file;
}

// Mock xlsx 模块（根据输入内容动态解析）
vi.mock('xlsx', () => {
  const parseText = (text: string): unknown[][] => {
    const lines = text.split('\n').filter((l) => l.trim());
    return lines.map((line) => line.split(','));
  };
  const mockRead = vi.fn((input: string | ArrayBuffer) => {
    const text = typeof input === 'string' ? input : new TextDecoder().decode(input);
    const rows = parseText(text);
    const sheet: Record<string, { t: string; v: unknown }> = {};
    rows.forEach((row, rIdx) => {
      row.forEach((val, cIdx) => {
        const cell = String.fromCharCode(65 + cIdx) + (rIdx + 1);
        sheet[cell] = { t: 's', v: val };
      });
    });
    return { Sheets: { Sheet1: sheet }, SheetNames: ['Sheet1'] };
  });
  const mockSheetToJson = vi.fn((sheet, opts) => {
    // 从 sheet 对象重建 rows
    const cells = Object.keys(sheet || {});
    if (cells.length === 0) return [];
    const maxRow = Math.max(...cells.map((c) => parseInt(c.slice(1))));
    const maxCol = Math.max(...cells.map((c) => c.charCodeAt(0) - 64));
    const rows: unknown[][] = [];
    for (let r = 1; r <= maxRow; r++) {
      const row: unknown[] = [];
      for (let c = 1; c <= maxCol; c++) {
        const cell = String.fromCharCode(64 + c) + r;
        row.push(sheet[cell]?.v ?? '');
      }
      rows.push(row);
    }
    if (opts && opts.header === 1) {
      return rows;
    }
    const headers = rows[0] || [];
    return rows.slice(1).map((row) => {
      const obj: Record<string, unknown> = {};
      headers.forEach((h, i) => {
        obj[String(h)] = row[i] ?? '';
      });
      return obj;
    });
  });
  return {
    read: mockRead,
    utils: { sheet_to_json: mockSheetToJson },
    default: { read: mockRead, utils: { sheet_to_json: mockSheetToJson } },
  };
});

// Mock Worker
vi.stubGlobal('Worker', class {
  postMessage() {}
  addEventListener() {}
  removeEventListener() {}
  terminate() {}
});

describe('kittenDatasetParser', () => {
  describe('KITTEN_DATASET_SAMPLE_LIMIT', () => {
    it('导出为 1000', () => {
      expect(KITTEN_DATASET_SAMPLE_LIMIT).toBe(1000);
    });
  });

  describe('parseDatasetFile - CSV', () => {
    it('解析 CSV 文件返回正确结构', async () => {
      const content = 'name,age\nAlice,30\nBob,25';
      const file = createFile(content, 'test.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result).toHaveProperty('rows');
      expect(result).toHaveProperty('columns');
      expect(result).toHaveProperty('preview');
      expect(result).toHaveProperty('sampleRows');
      expect(result).toHaveProperty('fieldProfiles');
    });

    it('CSV 列名正确提取', async () => {
      const content = 'name,age\nAlice,30';
      const file = createFile(content, 'test.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.columns).toEqual(['name', 'age']);
    });

    it('CSV 行数正确', async () => {
      const content = 'name,age\nAlice,30\nBob,25\nCharlie,35';
      const file = createFile(content, 'test.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(3);
    });

    it('CSV preview 包含原始行', async () => {
      const content = 'name,age\nAlice,30';
      const file = createFile(content, 'test.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(Array.isArray(result.preview)).toBe(true);
    });

    it('CSV fieldProfiles 包含字段类型', async () => {
      const content = 'name,age\nAlice,30\nBob,25';
      const file = createFile(content, 'test.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.fieldProfiles.length).toBe(2);
      expect(result.fieldProfiles[0]).toHaveProperty('name');
      expect(result.fieldProfiles[0]).toHaveProperty('type');
      expect(result.fieldProfiles[0]).toHaveProperty('nonEmpty');
      expect(result.fieldProfiles[0]).toHaveProperty('uniqueCount');
    });
  });

  describe('parseDatasetFile - TXT', () => {
    it('解析 TXT 文件（与 CSV 相同逻辑）', async () => {
      const content = 'name,age\nAlice,30';
      const file = createFile(content, 'test.txt', { type: 'text/plain' });
      const result = await parseDatasetFile(file);
      expect(result.columns).toEqual(['name', 'age']);
    });
  });

  describe('parseDatasetFile - JSON', () => {
    it('解析对象数组 JSON', async () => {
      const content = JSON.stringify([{ name: 'Alice', age: 30 }, { name: 'Bob', age: 25 }]);
      const file = createFile(content, 'test.json', { type: 'application/json' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(2);
      expect(result.columns).toContain('name');
      expect(result.columns).toContain('age');
    });

    it('解析空数组 JSON 返回空结构', async () => {
      const content = JSON.stringify([]);
      const file = createFile(content, 'empty.json', { type: 'application/json' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(0);
      expect(result.columns).toEqual([]);
      expect(result.preview).toEqual([]);
      expect(result.sampleRows).toEqual([]);
      expect(result.fieldProfiles).toEqual([]);
    });

    it('解析原始值数组 JSON', async () => {
      const content = JSON.stringify([1, 2, 3]);
      const file = createFile(content, 'values.json', { type: 'application/json' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(3);
      expect(result.columns).toEqual(['value']);
    });

    it('解析对象 JSON（单行）', async () => {
      const content = JSON.stringify({ name: 'Alice', age: 30 });
      const file = createFile(content, 'obj.json', { type: 'application/json' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(1);
      expect(result.columns).toContain('name');
    });

    it('解析 { data: [] } 结构 JSON', async () => {
      const content = JSON.stringify({ data: [{ name: 'Alice' }, { name: 'Bob' }] });
      const file = createFile(content, 'wrapped.json', { type: 'application/json' });
      const result = await parseDatasetFile(file);
      expect(result.rows).toBe(2);
    });

    it('无效 JSON 抛错', async () => {
      const content = 'not valid json';
      const file = createFile(content, 'invalid.json', { type: 'application/json' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/JSON 解析失败/);
    });

    it('不支持的 JSON 结构抛错', async () => {
      const content = JSON.stringify('just a string');
      const file = createFile(content, 'string.json', { type: 'application/json' });
      // normalizeJsonPayload 抛出 "JSON 文件结构不支持"，但 parseJson 的 try/catch 会包装为 "JSON 解析失败"
      await expect(parseDatasetFile(file)).rejects.toThrow(/JSON/);
    });

    it('数字类型 JSON 抛错', async () => {
      const content = JSON.stringify(123);
      const file = createFile(content, 'number.json', { type: 'application/json' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/JSON/);
    });

    it('布尔值 JSON 抛错', async () => {
      const content = JSON.stringify(true);
      const file = createFile(content, 'bool.json', { type: 'application/json' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/JSON/);
    });

    it('null JSON 抛错', async () => {
      const content = JSON.stringify(null);
      const file = createFile(content, 'null.json', { type: 'application/json' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/JSON/);
    });
  });

  describe('parseDatasetFile - Excel', () => {
    it('解析 XLSX 文件', async () => {
      const content = 'fake xlsx content';
      const file = createFile(content, 'test.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const result = await parseDatasetFile(file);
      expect(result).toHaveProperty('rows');
      expect(result).toHaveProperty('columns');
    });

    it('解析 XLS 文件', async () => {
      const content = 'fake xls content';
      const file = createFile(content, 'test.xls', { type: 'application/vnd.ms-excel' });
      const result = await parseDatasetFile(file);
      expect(result).toHaveProperty('rows');
    });
  });

  describe('parseDatasetFile - 不支持的类型', () => {
    it('PDF 文件抛错', async () => {
      const file = createFile("x", 'test.pdf', { type: 'application/pdf' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/暂不支持该文件类型/);
    });

    it('无扩展名文件抛错', async () => {
      const file = createFile("x", 'noext', { type: 'application/octet-stream' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/暂不支持该文件类型/);
    });

    it('DOC 文件抛错', async () => {
      const file = createFile("x", 'test.doc', { type: 'application/msword' });
      await expect(parseDatasetFile(file)).rejects.toThrow(/暂不支持该文件类型/);
    });
  });

  describe('parseDatasetFile - fieldProfiles 类型推断', () => {
    it('数字列被识别为 number 类型', async () => {
      const content = 'name,age\nAlice,30\nBob,25\nCharlie,35';
      const file = createFile(content, 'numeric.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      const ageProfile = result.fieldProfiles.find((p) => p.name === 'age');
      expect(ageProfile?.type).toBe('number');
    });

    it('文本列被识别为 text 类型', async () => {
      // 使用足够多的唯一值（>20）以避免被识别为 category
      const names = Array.from({ length: 25 }, (_, i) => `user${i}`);
      const content = 'name\n' + names.join('\n');
      const file = createFile(content, 'text.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      const nameProfile = result.fieldProfiles.find((p) => p.name === 'name');
      expect(nameProfile?.type).toBe('text');
    });

    it('日期列被识别为 date 类型', async () => {
      const content = 'date\n2024-01-01\n2024-02-01\n2024-03-01\n2024-04-01';
      const file = createFile(content, 'dates.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      const dateProfile = result.fieldProfiles.find((p) => p.name === 'date');
      expect(dateProfile?.type).toBe('date');
    });

    it('category 类型（少量唯一值）', async () => {
      // 重复值多的列会被识别为 category
      const rows = ['status'];
      for (let i = 0; i < 20; i++) {
        rows.push(i < 10 ? 'active' : 'inactive');
      }
      const content = rows.join('\n');
      const file = createFile(content, 'category.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      const statusProfile = result.fieldProfiles.find((p) => p.name === 'status');
      expect(['category', 'text']).toContain(statusProfile?.type);
    });
  });

  describe('parseDatasetFile - sampleRows 限制', () => {
    it('sampleRows 不超过 KITTEN_DATASET_SAMPLE_LIMIT', async () => {
      const rows = ['name'];
      for (let i = 0; i < 1500; i++) {
        rows.push(`user${i}`);
      }
      const content = rows.join('\n');
      const file = createFile(content, 'large.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.sampleRows.length).toBeLessThanOrEqual(KITTEN_DATASET_SAMPLE_LIMIT);
    });
  });

  describe('parseDatasetFile - preview 限制', () => {
    it('preview 最多 3 行', async () => {
      const content = 'name\nA\nB\nC\nD\nE';
      const file = createFile(content, 'preview.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.preview.length).toBeLessThanOrEqual(3);
    });
  });

  describe('parseDatasetFile - 空文件', () => {
    it('空 CSV 文件', async () => {
      const content = '';
      const file = createFile(content, 'empty.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result).toBeDefined();
    });
  });

  describe('parseDatasetFile - 特殊字符', () => {
    it('CSV 含中文', async () => {
      const content = '姓名,年龄\n张三,30\n李四,25';
      const file = createFile(content, 'chinese.csv', { type: 'text/csv' });
      const result = await parseDatasetFile(file);
      expect(result.columns).toContain('姓名');
      expect(result.columns).toContain('年龄');
    });
  });

  describe('parseDatasetFile - 大文件 Worker 路径', () => {
    it('大 CSV 文件尝试 Worker 解析（失败回退主线程）', async () => {
      // 创建大于 96KB 的文件
      const bigContent = 'name,age\n' + Array.from({ length: 5000 }, (_, i) => `user${i},${i}`).join('\n');
      const file = createFile(bigContent, 'big.csv', { type: 'text/csv' });
      // 确保 arrayBuffer 可用（大文件可能走 arrayBuffer 路径）
      Object.defineProperty(file, 'arrayBuffer', {
        value: () => Promise.resolve(new TextEncoder().encode(bigContent).buffer),
        configurable: true,
      });
      // Worker 会创建但消息处理可能失败，应回退到主线程解析
      const result = await parseDatasetFile(file);
      expect(result).toBeDefined();
      expect(result.rows).toBeGreaterThan(0);
    });
  });
});
