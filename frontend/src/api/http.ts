import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { attachAxiosDbReadInterceptor } from "./attachAxiosDbReadInterceptor";
import { readCsrfTokenFromCookie } from "@/utils/csrfCookie";

export const api = axios.create({
  baseURL: "",
  timeout: 30000,
});

/** Cookie 会话下的 DELETE/POST 等须带 ``X-CSRF-Token``，否则后端返回 403 CSRF token missing。 */
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const m = (config.method || "get").toUpperCase();
  if (m === "GET" || m === "HEAD" || m === "OPTIONS") return config;
  const h = config.headers;
  const auth = typeof h.get === "function" ? String(h.get("Authorization") || "") : "";
  if (auth.toLowerCase().startsWith("bearer ")) return config;
  const existing =
    typeof h.get === "function"
      ? String(h.get("X-CSRF-Token") || h.get("x-csrf-token") || "")
      : "";
  if (existing.trim()) return config;
  const tok = readCsrfTokenFromCookie();
  if (!tok) return config;
  if (typeof h.set === "function") h.set("X-CSRF-Token", tok);
  else (h as Record<string, string>)["X-CSRF-Token"] = tok;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status;

    if (status === 401) {
      const current = window.location.pathname;
      if (!current.includes("/login")) {
        window.location.href = "/login?redirect=" + encodeURIComponent(current);
      }
      return Promise.reject(error);
    }

    if (status && status >= 500) {
      console.error(`[API] Server error ${status}:`, error.config?.url);
    }

    return Promise.reject(error);
  },
);

const _retryableMethods = new Set(["get", "head", "options"]);

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as InternalAxiosRequestConfig & { _retried?: boolean };
  if (!config || config._retried) return Promise.reject(error);

  const method = config.method?.toLowerCase() ?? "";
  if (!_retryableMethods.has(method)) return Promise.reject(error);

  if (!error.response || (error.response.status >= 500 && error.response.status < 600)) {
    config._retried = true;
    return api.request(config);
  }

  return Promise.reject(error);
});

attachAxiosDbReadInterceptor(api);
