import { describe, expect, it } from 'vitest';
import { systemApi } from '@/api/system';

describe('system api module', () => {
  it('exports industry and config helpers', () => {
    expect(typeof systemApi.getIndustries).toBe('function');
    expect(typeof systemApi.getCurrentIndustry).toBe('function');
    expect(typeof systemApi.setIndustry).toBe('function');
    expect(typeof systemApi.getIndustryDetail).toBe('function');
    expect(typeof systemApi.getSystemConfig).toBe('function');
    expect(typeof systemApi.getHostProfile).toBe('function');
    expect(typeof systemApi.getIndustryPresets).toBe('function');
    expect(typeof systemApi.getWorkflowEmployeeCatalog).toBe('function');
    expect(typeof systemApi.getEmployeeRegistryRules).toBe('function');
  });
});
