import Foundation
import MetricKit
import os

/// iOS 端性能监控入口,指标名对齐 `mobile_tri_platform_ssot.md`。
final class MobilePerformanceMonitor: NSObject, MXMetricManagerSubscriber {
    static let shared = MobilePerformanceMonitor()

    private let logger = Logger(subsystem: "com.xiuci.xcagi.mobile", category: "performance")
    private var started = false

    private override init() {}

    func start() {
        guard !started else { return }
        MXMetricManager.shared.add(self)
        started = true
        logger.info("mobile_perf monitor_started platform=ios")
    }

    func stop() {
        guard started else { return }
        MXMetricManager.shared.remove(self)
        started = false
    }

    func markStart() -> Date {
        Date()
    }

    func record(name: String, startedAt: Date, status: String = "ok", attributes: [String: String] = [:]) {
        let durationMs = max(0, Int(Date().timeIntervalSince(startedAt) * 1000))
        record(name: name, durationMs: durationMs, status: status, attributes: attributes)
    }

    func record(name: String, durationMs: Int, status: String = "ok", attributes: [String: String] = [:]) {
        let attrs = attributes
            .sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value)" }
            .joined(separator: " ")
        logger.info(
            "mobile_perf name=\(name, privacy: .public) duration_ms=\(durationMs, privacy: .public) status=\(status, privacy: .public) attrs=\(attrs, privacy: .public)"
        )
    }

    func didReceive(_ payloads: [MXMetricPayload]) {
        logger.info("mobile_perf metric_payload_count=\(payloads.count, privacy: .public)")
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        logger.info("mobile_perf diagnostic_payload_count=\(payloads.count, privacy: .public)")
    }
}
