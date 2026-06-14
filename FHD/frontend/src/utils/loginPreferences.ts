const LS_REMEMBER_PASSWORD = 'xcagi_login_remember_password';
const LS_AUTO_LOGIN = 'xcagi_login_auto_login';
const LS_SAVED_USERNAME = 'xcagi_login_saved_username';
const LS_SAVED_PASSWORD = 'xcagi_login_saved_password';

function encodePassword(pw: string): string {
  try {
    return btoa(unescape(encodeURIComponent(pw)));
  } catch {
    return '';
  }
}

function decodePassword(raw: string | null): string {
  if (!raw) return '';
  try {
    return decodeURIComponent(escape(atob(raw)));
  } catch {
    return '';
  }
}

export interface LoginPreferences {
  rememberPassword: boolean;
  autoLogin: boolean;
  username: string;
  password: string;
}

export function loadLoginPreferences(): LoginPreferences {
  if (typeof localStorage === 'undefined') {
    return { rememberPassword: false, autoLogin: false, username: '', password: '' };
  }
  const rememberPassword = localStorage.getItem(LS_REMEMBER_PASSWORD) === '1';
  return {
    rememberPassword,
    autoLogin: localStorage.getItem(LS_AUTO_LOGIN) === '1',
    username: rememberPassword ? String(localStorage.getItem(LS_SAVED_USERNAME) || '').trim() : '',
    password: rememberPassword ? decodePassword(localStorage.getItem(LS_SAVED_PASSWORD)) : '',
  };
}

export function saveLoginPreferences(opts: {
  rememberPassword: boolean;
  autoLogin: boolean;
  username: string;
  password: string;
}): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(LS_REMEMBER_PASSWORD, opts.rememberPassword ? '1' : '0');
  localStorage.setItem(LS_AUTO_LOGIN, opts.autoLogin ? '1' : '0');
  if (opts.rememberPassword) {
    localStorage.setItem(LS_SAVED_USERNAME, opts.username.trim());
    localStorage.setItem(LS_SAVED_PASSWORD, encodePassword(opts.password));
  } else {
    localStorage.removeItem(LS_SAVED_USERNAME);
    localStorage.removeItem(LS_SAVED_PASSWORD);
  }
}

/** 主动退出时关闭自动登录，保留「记住密码」与账号填充（若用户曾勾选） */
export function clearAutoLoginPreference(): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(LS_AUTO_LOGIN, '0');
}
