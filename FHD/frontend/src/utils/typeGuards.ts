/** Narrow unknown API payloads to object maps */
export function asRecord(value: unknown): Record<string, unknown> {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

export function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function asString(value: unknown, fallback = ''): string {
  return value != null ? String(value) : fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function asBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === 1) return true;
  if (value === 'false' || value === 0) return false;
  return fallback;
}

/** Disposable resource shape used by memory-manager */
export interface DisposableResource {
  dispose?: () => void;
  destroy?: () => void;
  cleanup?: () => void;
}

export function asDisposable(value: unknown): DisposableResource {
  return asRecord(value) as DisposableResource;
}
