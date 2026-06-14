import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api';
import { useApi, useMutation } from './useApi';

describe('useApi', () => {
  it('executes api and stores result', async () => {
    const apiFn = vi.fn().mockResolvedValue({ ok: true });
    const onSuccess = vi.fn();
    const { data, loading, error, execute } = useApi(apiFn, { onSuccess });
    expect(loading.value).toBe(false);
    const result = await execute({ q: 'x' });
    expect(result).toEqual({ ok: true });
    expect(data.value).toEqual({ ok: true });
    expect(error.value).toBeNull();
    expect(onSuccess).toHaveBeenCalledWith({ ok: true });
    expect(apiFn).toHaveBeenCalledWith({ q: 'x' });
  });

  it('merges defaultParams', async () => {
    const apiFn = vi.fn().mockResolvedValue(1);
    const { execute } = useApi(apiFn, { defaultParams: { a: 1 } });
    await execute({ b: 2 });
    expect(apiFn).toHaveBeenCalledWith({ a: 1, b: 2 });
  });

  it('maps ApiError to resolved message', async () => {
    const apiFn = vi.fn().mockRejectedValue(
      new ApiError('raw', 400, { error: { code: 'X', message: 'bad' } }),
    );
    const onError = vi.fn();
    const { execute, error } = useApi(apiFn, { onError });
    await expect(execute()).rejects.toThrow();
    expect(error.value).toBeInstanceOf(Error);
    expect(onError).toHaveBeenCalled();
  });

  it('reset clears state', async () => {
    const apiFn = vi.fn().mockResolvedValue('v');
    const { data, execute, reset } = useApi(apiFn);
    await execute();
    reset();
    expect(data.value).toBeNull();
  });
});

describe('useMutation', () => {
  it('mutate calls onSuccess', async () => {
    const apiFn = vi.fn().mockResolvedValue({ id: 1 });
    const onSuccess = vi.fn();
    const { mutate, loading } = useMutation(apiFn, { onSuccess });
    expect(loading.value).toBe(false);
    const out = await mutate({ name: 'a' });
    expect(out).toEqual({ id: 1 });
    expect(onSuccess).toHaveBeenCalledWith({ id: 1 }, { name: 'a' });
  });

  it('mutate calls onError on failure', async () => {
    const apiFn = vi.fn().mockRejectedValue(new Error('fail'));
    const onError = vi.fn();
    const { mutate, error } = useMutation(apiFn, { onError });
    await expect(mutate('x')).rejects.toThrow('fail');
    expect(error.value?.message).toBe('fail');
    expect(onError).toHaveBeenCalled();
  });
});
