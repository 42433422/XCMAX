import { ref, type Ref } from 'vue';
import { ApiError } from '@/api';
import i18n from '@/i18n';
import { resolveApiErrorMessage } from '@/utils/resolveApiError';

export interface UseApiOptions<T> {
  immediate?: boolean;
  defaultParams?: Record<string, any>;
  onSuccess?: (data: T) => void;
  onError?: (error: Error) => void;
}

export interface UseApiReturn<T> {
  data: Ref<T | null>;
  error: Ref<Error | null>;
  loading: Ref<boolean>;
  execute: (params?: Record<string, any>) => Promise<T | null>;
  reset: () => void;
}

function resolveApiError(err: unknown, fallback = ''): Error {
  if (err instanceof ApiError) {
    const data = err.data && typeof err.data === 'object' ? (err.data as Record<string, unknown>) : null;
    const nested =
      data?.error && typeof data.error === 'object'
        ? (data.error as { code?: string; message?: string })
        : null;
    const message = resolveApiErrorMessage(
      (key: string) => String(i18n.global.t(key)),
      nested || { message: err.message },
      err.message || fallback,
    );
    return new Error(message);
  }
  return err instanceof Error ? err : new Error(String(err || fallback));
}

export function useApi<T>(
  apiFn: (params: Record<string, any>) => Promise<T>,
  options: UseApiOptions<T> = {}
): UseApiReturn<T> {
  const data = ref<T | null>(null) as Ref<T | null>;
  const error = ref<Error | null>(null);
  const loading = ref(false);
  const { immediate = false, defaultParams = {} } = options;

  const execute = async (params: Record<string, any> = {}): Promise<T | null> => {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await apiFn({ ...defaultParams, ...params });
      data.value = result as T;
      options.onSuccess?.(result);
      return result;
    } catch (err) {
      const resolved = resolveApiError(err);
      error.value = resolved;
      options.onError?.(resolved);
      throw resolved;
    } finally {
      loading.value = false;
    }
  };

  if (immediate) {
    execute();
  }

  return {
    data,
    error,
    loading,
    execute,
    reset: () => {
      data.value = null;
      error.value = null;
      loading.value = false;
    }
  };
}

export interface UseMutationOptions<T, V = any> {
  onSuccess?: (data: T, variables: V) => void;
  onError?: (error: Error, variables: V) => void;
}

export interface UseMutationReturn<T, V = any> {
  loading: Ref<boolean>;
  error: Ref<Error | null>;
  mutate: (variables: V) => Promise<T | null>;
}

export function useMutation<T, V = any>(
  apiFn: (variables: V) => Promise<T>,
  options: UseMutationOptions<T, V> = {}
): UseMutationReturn<T, V> {
  const { onSuccess, onError } = options;
  const loading = ref(false);
  const error = ref<Error | null>(null);

  const mutate = async (variables: V): Promise<T | null> => {
    loading.value = true;
    error.value = null;
    
    try {
      const result = await apiFn(variables);
      onSuccess?.(result, variables);
      return result;
    } catch (err) {
      const resolved = resolveApiError(err);
      error.value = resolved;
      onError?.(resolved, variables);
      throw resolved;
    } finally {
      loading.value = false;
    }
  };

  return {
    loading,
    error,
    mutate
  };
}
