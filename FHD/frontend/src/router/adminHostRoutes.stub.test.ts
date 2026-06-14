import { describe, expect, it } from 'vitest';
import { ADMIN_HOST_ROUTE_RECORDS } from './adminHostRoutes.stub';

describe('adminHostRoutes.stub', () => {
  it('exports empty placeholder route records for enterprise SPA', () => {
    expect(ADMIN_HOST_ROUTE_RECORDS).toEqual([]);
  });
});
