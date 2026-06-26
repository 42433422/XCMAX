import { describe, expect, it } from 'vitest';
import {
  resolveSuperEmployeeAvatarSrc,
  superEmployeeAvatarKeyForId,
  superEmployeeAvatarSrcForId,
} from './superEmployeeAvatars';

describe('superEmployeeAvatars', () => {
  it('maps super employee ids to avatar keys and brand assets', () => {
    expect(superEmployeeAvatarKeyForId('cursor-super-employee')).toBe('cursor');
    expect(superEmployeeAvatarSrcForId('cursor-super-employee')).toContain('cursor-app-icon.png');
    expect(superEmployeeAvatarSrcForId('codex-super-employee')).toContain('codex-app-icon.png');
    expect(superEmployeeAvatarSrcForId('claude-super-employee')).toContain('claude-app-icon.svg');
  });

  it('prefers explicit avatar url when provided', () => {
    expect(resolveSuperEmployeeAvatarSrc('cursor-super-employee', '/custom.svg')).toBe('/custom.svg');
  });
});
