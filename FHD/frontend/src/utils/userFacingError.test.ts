import { describe, expect, it } from 'vitest';

import { ApiError } from '@/api/core';
import {
  isQrExpiredError,
  looksLikeProductCopy,
  statusFallbackCopy,
  userFacingErrorMessage,
} from './userFacingError';

describe('looksLikeProductCopy', () => {
  it('接受服务端中文产品文案', () => {
    expect(looksLikeProductCopy('二维码已过期，请刷新')).toBe(true);
    expect(looksLikeProductCopy('配对码无效或已过期，请刷新二维码')).toBe(true);
  });

  it('拒绝原始 HTTP/网络文案', () => {
    expect(looksLikeProductCopy('请求失败：401')).toBe(false);
    expect(looksLikeProductCopy('Request failed with status code 500')).toBe(false);
    expect(looksLikeProductCopy('Unauthorized')).toBe(false);
    expect(looksLikeProductCopy('Failed to fetch')).toBe(false);
    expect(looksLikeProductCopy('')).toBe(false);
  });

  it('拒绝过短占位词（未授权等），交给状态码映射升级', () => {
    expect(looksLikeProductCopy('未授权')).toBe(false);
  });
});

describe('userFacingErrorMessage', () => {
  it('401 映射为重新登录提示，而不是原始 401 文案', () => {
    const err = new ApiError('请求失败：401', 401, null);
    expect(userFacingErrorMessage(err)).toBe('登录已过期，请重新登录或重新扫码绑定');
  });

  it('网络错误（status=0）映射为连接失败提示', () => {
    const err = new ApiError('Failed to fetch', 0, null);
    expect(userFacingErrorMessage(err)).toBe('无法连接服务器，请检查网络或稍后重试');
  });

  it('5xx 映射为服务不可用', () => {
    const err = new ApiError('Internal Server Error', 502, null);
    expect(userFacingErrorMessage(err)).toBe('服务暂时不可用，请稍后重试');
  });

  it('服务端中文产品文案原样透传', () => {
    const err = new ApiError('配对码无效或已过期，请刷新二维码', 400, null);
    expect(userFacingErrorMessage(err)).toBe('配对码无效或已过期，请刷新二维码');
  });

  it('无法识别时回退到调用方 fallback', () => {
    const err = new ApiError('bad', 418, null);
    expect(userFacingErrorMessage(err, '发送失败，请稍后重试')).toBe('发送失败，请稍后重试');
    expect(userFacingErrorMessage('oops', '发送失败，请稍后重试')).toBe('发送失败，请稍后重试');
  });

  it('普通 Error 的英文网络文案不上屏', () => {
    expect(userFacingErrorMessage(new Error('NetworkError when attempting to fetch resource'))).toBe(
      '无法连接服务器，请检查网络或稍后重试',
    );
    expect(userFacingErrorMessage(new Error('员工尚未安装'))).toBe('员工尚未安装');
  });
});

describe('statusFallbackCopy', () => {
  it('覆盖常见状态码', () => {
    expect(statusFallbackCopy(429)).toContain('频繁');
    expect(statusFallbackCopy(404)).toContain('没有找到');
    expect(statusFallbackCopy(0)).toContain('无法连接服务器');
  });
});

describe('isQrExpiredError', () => {
  it('401/404/410 视为二维码过期', () => {
    expect(isQrExpiredError(new ApiError('x', 401, null))).toBe(true);
    expect(isQrExpiredError(new ApiError('x', 404, null))).toBe(true);
    expect(isQrExpiredError(new ApiError('x', 410, null))).toBe(true);
    expect(isQrExpiredError(new ApiError('x', 500, null))).toBe(false);
    expect(isQrExpiredError(new Error('x'))).toBe(false);
  });
});
