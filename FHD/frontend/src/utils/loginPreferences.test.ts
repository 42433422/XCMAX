import { beforeEach, describe, expect, it } from 'vitest';
import { loadLoginPreferences, saveLoginPreferences, clearAutoLoginPreference } from './loginPreferences';

beforeEach(() => {
  localStorage.clear();
});

describe('loginPreferences', () => {
  it('returns defaults when storage empty', () => {
    expect(loadLoginPreferences()).toEqual({
      rememberPassword: false,
      autoLogin: false,
      username: '',
      password: '',
    });
  });

  it('round-trips remembered credentials', () => {
    saveLoginPreferences({
      rememberPassword: true,
      autoLogin: true,
      username: 'alice',
      password: 'p@ss 中文',
    });
    const prefs = loadLoginPreferences();
    expect(prefs.rememberPassword).toBe(true);
    expect(prefs.autoLogin).toBe(true);
    expect(prefs.username).toBe('alice');
    expect(prefs.password).toBe('p@ss 中文');
  });

  it('clears saved credentials when remember disabled', () => {
    saveLoginPreferences({
      rememberPassword: true,
      autoLogin: false,
      username: 'bob',
      password: 'secret',
    });
    saveLoginPreferences({
      rememberPassword: false,
      autoLogin: false,
      username: 'bob',
      password: 'secret',
    });
    const prefs = loadLoginPreferences();
    expect(prefs.username).toBe('');
    expect(prefs.password).toBe('');
    expect(localStorage.getItem('xcagi_login_saved_username')).toBeNull();
  });

  it('clearAutoLoginPreference turns off auto login but keeps saved credentials', () => {
    saveLoginPreferences({
      rememberPassword: true,
      autoLogin: true,
      username: 'alice',
      password: 'secret',
    });
    clearAutoLoginPreference();
    const prefs = loadLoginPreferences();
    expect(prefs.autoLogin).toBe(false);
    expect(prefs.rememberPassword).toBe(true);
    expect(prefs.username).toBe('alice');
    expect(prefs.password).toBe('secret');
  });
});
