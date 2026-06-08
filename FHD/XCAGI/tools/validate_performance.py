# -*- coding: utf-8 -*-
"""
XCAGI 性能优化系统 - 快速启动和验证脚本

用于：
1. 验证所有优化组件是否正常工作
2. 查看当前性能指标
3. 测试缓存、监控等功能
4. 生成性能报告
"""

import sys
import os
import time
import json

# 将项目根目录添加到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def print_banner():
    """打印横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║         🚀 XCAGI 性能优化系统 - 验证工具 v1.0              ║
╠═══════════════════════════════════════════════════════════╣
║   功能: 缓存 | 监控 | 异步任务 | 去重 | 限流 | Prometheus ║
╚═══════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_redis_connection():
    """检查 Redis 连接"""
    print("\n📡 [1/6] 检查 Redis 连接...")
    try:
        from app.utils.redis_cache import get_redis_cache

        cache = get_redis_cache()

        if cache and cache.is_available:
            # 测试基本操作
            test_key = "xcagi:health:check"
            cache.set(test_key, "ok", ttl=10)
            value = cache.get(test_key)
            cache.delete(test_key)

            if value == "ok":
                stats = cache.stats
                print(f"   ✅ Redis 连接成功")
                print(f"      - 本地缓存大小: {stats.get('local_cache_size', 0)}")
                print(f"      - 命中率: {stats.get('hit_rate', 0):.1%}")
                return True

        print("   ⚠️  Redis 未连接（将使用本地缓存）")
        return False

    except Exception as e:
        print(f"   ❌ Redis 检查失败: {e}")
        return False


def check_query_optimizer():
    """检查查询优化器"""
    print("\n🔍 [2/6] 检查查询优化器...")
    try:
        from app.utils.query_optimizer import get_query_optimizer

        optimizer = get_query_optimizer()
        stats = optimizer.stats

        print(f"   ✅ 查询优化器已启用")
        print(f"      - 总查询数: {stats.get('total_queries', 0)}")
        print(f"      - 慢查询数: {stats.get('slow_queries', 0)}")
        print(f"      - 平均耗时: {stats.get('avg_duration_ms', 0):.3f}ms")
        return True

    except Exception as e:
        print(f"   ❌ 查询优化器检查失败: {e}")
        return False


def check_async_tasks():
    """检查异步任务管理"""
    print("\n⚡ [3/6] 检查异步任务管理...")
    try:
        from app.utils.async_tasks import get_async_task_manager

        manager = get_async_task_manager()
        stats = manager.stats

        print(f"   ✅ 异步任务管理已启用")
        print(f"      - 已注册任务: {len(stats.get('registered_tasks', []))}")
        print(f"      - 活跃任务: {stats.get('active_tasks', 0)}")

        registered = stats.get('registered_tasks', [])
        if registered:
            print(f"      - 任务列表: {', '.join(registered[:5])}{'...' if len(registered) > 5 else ''}")

        return True

    except Exception as e:
        print(f"   ❌ 异步任务管理检查失败: {e}")
        return False


def check_request_dedup():
    """检查请求去重"""
    print("\n🔄 [4/6] 检查请求去重...")
    try:
        from app.utils.request_deduplicator import get_request_deduplicator

        deduplicator = get_request_deduplicator()
        stats = deduplicator.stats

        print(f"   ✅ 请求去重已启用")
        print(f"      - 总请求数: {stats.get('total_requests', 0)}")
        print(f"      - 去重命中: {stats.get('deduplicated', 0)}")
        print(f"      - 去重率: {stats.get('dedup_rate', 0):.1f}%")
        return True

    except Exception as e:
        print(f"   ❌ 请求去重检查失败: {e}")
        return False


def check_performance_monitor():
    """检查性能监控"""
    print("\n📊 [5/6] 检查性能监控...")
    try:
        from app.utils.performance_monitor import get_performance_monitor

        monitor = get_performance_monitor()
        summary = monitor.get_metrics_summary(minutes=5)

        if summary.get("message") == "暂无数据":
            print(f"   ✅ 性能监控已启用（暂无数据，等待请求后生成）")
            return True

        api_stats = summary.get("api_stats", {})
        print(f"   ✅ 性能监控已启用")
        print(f"      - 总API调用: {api_stats.get('total', 0)}")
        print(f"      - 平均延迟: {api_stats.get('avg_ms', 0):.2f}ms")
        print(f"      - 错误率: {api_stats.get('error_4xx', 0) + api_stats.get('error_5xx', 0)}")
        print(f"      - 慢端点数: {api_stats.get('slow_count', 0)}")

        memory = summary.get("memory")
        if memory:
            print(f"      - 内存占用: {memory.get('rss_mb', 0):.1f}MB ({memory.get('percent', 0):.1f}%)")

        return True

    except Exception as e:
        print(f"   ❌ 性能监控检查失败: {e}")
        return False


def check_api_endpoints():
    """检查 API 端点是否可访问"""
    print("\n🌐 [6/6] 检查性能API端点...")

    endpoints = [
        ("GET /api/performance/status", "状态接口"),
        ("GET /api/performance/health", "健康检查"),
        ("GET /api/performance/metrics/summary", "指标摘要"),
        ("GET /api/performance/cache/stats", "缓存统计"),
        ("GET /api/performance/metrics/prometheus", "Prometheus"),
    ]

    all_ok = True
    for endpoint, desc in endpoints:
        try:
            import httpx
            response = httpx.get(f"http://localhost:5000{endpoint}", timeout=2)
            status = "✅" if response.status_code == 200 else "⚠️"
            print(f"   {status} {desc}: {response.status_code}")

            if response.status_code != 200:
                all_ok = False

        except Exception:
            print(f"   ⏳  {desc}: 无法连接（服务可能未启动）")
            all_ok = False

    return all_ok


def run_performance_test():
    """运行简单的性能测试"""
    print("\n🧪 运行性能基准测试...")

    results = {}

    # 测试1: 缓存读写
    start = time.perf_counter()
    try:
        from app.utils.redis_cache import get_redis_cache
        cache = get_redis_cache()

        for i in range(100):
            cache.set(f"bench:{i}", f"value_{i}", ttl=60)

        for i in range(100):
            cache.get(f"bench:{i}")

        duration = (time.perf_counter() - start) * 1000
        results["cache_100ops"] = round(duration, 2)
        print(f"   📦 缓存100次读写: {duration:.2f}ms")
    except Exception as e:
        print(f"   ❌ 缓存测试失败: {e}")

    # 测试2: 监控记录
    start = time.perf_counter()
    try:
        from app.utils.performance_monitor import get_performance_monitor
        monitor = get_performance_monitor()

        for i in range(50):
            monitor.record_metric(f"test_metric_{i % 5}", 1.0 + (i * 0.01))

        duration = (time.perf_counter() - start) * 1000
        results["monitor_50records"] = round(duration, 2)
        print(f"   📊 监控50次记录: {duration:.2f}ms")
    except Exception as e:
        print(f"   ❌ 监控测试失败: {e}")

    # 测试3: 去重操作
    start = time.perf_counter()
    try:
        from app.utils.request_deduplicator import get_request_deduplicator
        dedup = get_request_deduplicator()

        def dummy_func(x):
            return x * 2

        for i in range(50):
            dedup.deduplicate(dummy_func, i)

        duration = (time.perf_counter() - start) * 1000
        results["dedup_50ops"] = round(duration, 2)
        print(f"   🔄 去重50次调用: {duration:.2f}ms")
    except Exception as e:
        print(f"   ❌ 去重测试失败: {e}")

    return results


def generate_report(check_results, perf_results):
    """生成验证报告"""
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "4.0-performance",
        "checks": check_results,
        "performance_benchmark": perf_results,
        "summary": {
            "total_components": len(check_results),
            "passed_components": sum(1 for v in check_results.values() if v),
            "overall_status": "✅ 全部通过" if all(check_results.values()) else "⚠️ 部分未通过"
        }
    }

    print("\n" + "=" * 60)
    print("📋 验证报告")
    print("=" * 60)
    print(f"时间: {report['timestamp']}")
    print(f"版本: {report['version']}")
    print("-" * 60)
    print(f"组件状态: {report['summary']['passed_components']}/{report['summary']['total_components']} 通过")
    print(f"总体状态: {report['summary']['overall_status']}")
    print("=" * 60)

    return report


def main():
    """主函数"""
    print_banner()

    print("\n🔎 开始验证 XCAGI 性能优化系统...\n")

    # 执行所有检查
    checks = {
        "Redis连接": check_redis_connection(),
        "查询优化器": check_query_optimizer(),
        "异步任务": check_async_tasks(),
        "请求去重": check_request_dedup(),
        "性能监控": check_performance_monitor(),
        "API端点": check_api_endpoints(),
    }

    # 运行性能测试
    perf_results = run_performance_test()

    # 生成报告
    report = generate_report(checks, perf_results)

    # 保存报告
    output_file = os.path.join(os.path.dirname(__file__), "..", "_perf_validation.json")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n💾 报告已保存: {output_file}")
    except Exception as e:
        print(f"\n⚠️  报告保存失败: {e}")

    # 返回退出码
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    exit(main())
