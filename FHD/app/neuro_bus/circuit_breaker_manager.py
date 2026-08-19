"""Domain-scoped manager and Prometheus export for NeuroBus circuit breakers."""

from __future__ import annotations

from threading import RLock

from app.neuro_bus.circuit_breaker import CircuitBreaker
from app.neuro_bus.circuit_breaker_primitives import CircuitBreakerConfig, CircuitState


class NeuroCircuitBreakerManager:
    """
    NeuroBus 熔断管理器

    管理多个熔断器，按领域和事件类型划分。
    提供 get_all_metrics / get_prometheus_metrics 用于监控集成。
    """

    # 各领域的熔断配置
    DOMAIN_CONFIGS = {
        "payment": CircuitBreakerConfig(
            failure_threshold=3,  # 支付敏感，低阈值
            timeout_seconds=30.0,  # 快速恢复尝试
        ),
        "wechat": CircuitBreakerConfig(
            failure_threshold=5,
            timeout_seconds=60.0,
        ),
        "intent": CircuitBreakerConfig(
            failure_threshold=10,  # 意图识别容忍度高
            timeout_seconds=30.0,
        ),
        "default": CircuitBreakerConfig(),
    }

    # 状态到数值的映射（用于 Prometheus gauge）
    _STATE_TO_INT = {
        CircuitState.CLOSED: 0,
        CircuitState.HALF_OPEN: 1,
        CircuitState.OPEN: 2,
    }

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = RLock()

    def get_breaker(self, domain: str, event_type: str | None = None) -> CircuitBreaker:
        """获取或创建熔断器"""
        key = f"{domain}:{event_type}" if event_type else domain

        with self._lock:
            if key not in self._breakers:
                config = self.DOMAIN_CONFIGS.get(domain, self.DOMAIN_CONFIGS["default"])
                self._breakers[key] = CircuitBreaker(key, config)

            return self._breakers[key]

    def check(self, domain: str, event_type: str | None = None) -> bool:
        """检查是否可以通过"""
        breaker = self.get_breaker(domain, event_type)
        return breaker.can_execute()

    def record_success(self, domain: str, event_type: str | None = None):
        """记录成功"""
        breaker = self.get_breaker(domain, event_type)
        breaker.record_success()

    def record_failure(self, domain: str, event_type: str | None = None):
        """记录失败"""
        breaker = self.get_breaker(domain, event_type)
        breaker.record_failure()

    def get_all_stats(self) -> dict:
        """获取所有熔断器统计（向后兼容）"""
        with self._lock:
            return {key: breaker.get_stats() for key, breaker in self._breakers.items()}

    def get_all_metrics(self) -> dict:
        """
        获取所有熔断器的 Prometheus 兼容指标。

        Returns:
            {breaker_name: metrics_dict} 的字典。
        """
        with self._lock:
            return {key: breaker.get_metrics() for key, breaker in self._breakers.items()}

    def get_prometheus_metrics(self) -> str:
        """
        生成 Prometheus 文本格式指标。

        输出格式符合 Prometheus exposition format，
        可直接由 /metrics 端点返回。

        指标列表：
        - circuit_breaker_state{gauge}
        - circuit_breaker_failure_rate
        - circuit_breaker_slow_call_rate
        - circuit_breaker_total_calls
        - circuit_breaker_successful_calls
        - circuit_breaker_failed_calls
        - circuit_breaker_slow_calls
        - circuit_breaker_rejected_calls
        - circuit_breaker_fallback_calls
        - circuit_breaker_concurrent_executions
        """
        with self._lock:
            lines: list[str] = []
            # 帮助文本
            lines.append(
                "# HELP circuit_breaker_state Circuit breaker state (0=closed,1=half_open,2=open)"
            )
            lines.append("# TYPE circuit_breaker_state gauge")
            lines.append("# HELP circuit_breaker_failure_rate Failure rate in sliding window")
            lines.append("# TYPE circuit_breaker_failure_rate gauge")
            lines.append("# HELP circuit_breaker_total_calls Total calls in sliding window")
            lines.append("# TYPE circuit_breaker_total_calls gauge")
            lines.append(
                "# HELP circuit_breaker_concurrent_executions Current concurrent executions"
            )
            lines.append("# TYPE circuit_breaker_concurrent_executions gauge")

            for name, breaker in self._breakers.items():
                m = breaker.get_metrics()
                # 转义 name 中的特殊字符
                safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
                label = f'name="{safe_name}"'
                state_int = self._STATE_TO_INT.get(CircuitState(m["state"]), 0)
                lines.append(f"circuit_breaker_state{{{label}}} {state_int}")
                lines.append(f"circuit_breaker_failure_rate{{{label}}} {m['failure_rate']}")
                lines.append(f"circuit_breaker_slow_call_rate{{{label}}} {m['slow_call_rate']}")
                lines.append(f"circuit_breaker_total_calls{{{label}}} {m['total_calls']}")
                lines.append(f"circuit_breaker_successful_calls{{{label}}} {m['successful_calls']}")
                lines.append(f"circuit_breaker_failed_calls{{{label}}} {m['failed_calls']}")
                lines.append(f"circuit_breaker_slow_calls{{{label}}} {m['slow_calls']}")
                lines.append(f"circuit_breaker_rejected_calls{{{label}}} {m['rejected_calls']}")
                lines.append(f"circuit_breaker_fallback_calls{{{label}}} {m['fallback_calls']}")
                lines.append(
                    f"circuit_breaker_concurrent_executions{{{label}}} {m['concurrent_executions']}"
                )
            return "\n".join(lines) + "\n" if lines else ""
