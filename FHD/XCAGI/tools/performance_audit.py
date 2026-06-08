# -*- coding: utf-8 -*-
"""
XCAGI 性能审查自动化工具

功能：
1. 定期收集性能指标
2. 生成性能趋势报告
3. 自动检测异常和瓶颈
4. 发送告警通知（可选）
5. 历史数据对比分析

使用方法：
    # 手动运行审查
    python tools/performance_audit.py

    # 设置定时任务 (Linux Cron)
    # 每周一早上9点运行
    0 9 * * 1 cd /path/to/xcagi && python tools/performance_audit.py >> logs/audit.log 2>&1

    # Windows 任务计划程序
    # 创建基本任务 -> 触发器:每周一 9:00 -> 操作: python tools/performance_audit.py
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class PerformanceAuditor:
    """
    性能审查器

    自动化收集和分析性能数据，生成可操作的报告
    """

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(project_root) / output_dir
        self.output_dir.mkdir(exist_ok=True)

        self.history_file = self.output_dir / "performance_history.json"
        self.alerts_file = self.output_dir / "alerts.json"

        self._load_history()

    def _load_history(self):
        """加载历史数据"""
        if self.history_file.exists():
            with open(self.history_file, 'r', encoding='utf-8') as f:
                self.history = json.load(f)
        else:
            self.history = {"records": [], "last_audit": None}

    def _save_history(self):
        """保存历史数据"""
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def collect_metrics(self) -> Dict[str, Any]:
        """
        收集当前性能指标

        Returns:
            包含所有指标的字典
        """
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "components": {},
            "api_stats": {},
            "cache_stats": {},
            "system_resources": {},
            "alerts": [],
        }

        try:
            from app.utils.performance_initializer import get_performance_optimizer
            optimizer = get_performance_optimization()

            if optimizer._initialized:
                status = optimizer.get_status()
                metrics["components"] = status.get("components", {})

                # 缓存统计
                cache = status.get("components", {}).get("redis_cache", {})
                if isinstance(cache, dict):
                    metrics["cache_stats"] = cache.get("stats", {})

                # API统计
                monitor = status.get("components", {}).get("performance_monitor", {})
                if isinstance(monitor, dict):
                    api_summary = monitor.get("metrics_summary", {})
                    metrics["api_stats"] = api_summary.get("api_stats", {})

                    # 提取慢端点
                    slow_endpoints = api_summary.get("top_slow_endpoints", [])
                    if slow_endpoints:
                        metrics["slow_endpoints"] = slow_endpoints[:5]

        except Exception as e:
            metrics["collection_error"] = str(e)
            print(f"⚠️  指标收集失败: {e}")

        # 系统资源
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()

            metrics["system_resources"] = {
                "memory_rss_mb": round(mem_info.rss / (1024 * 1024), 2),
                "memory_vms_mb": round(mem_info.vms / (1024 * 1024), 2),
                "memory_percent": round(process.memory_percent(), 2),
                "cpu_percent": round(process.cpu_percent(), 2),
            }
        except ImportError:
            pass

        return metrics

    def analyze_performance(self, current: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析性能数据，检测异常

        Returns:
            分析结果和建议
        """
        analysis = {
            "overall_score": 100,
            "issues": [],
            "recommendations": [],
            "trends": {},
        }

        score_deductions = []

        # 1. 检查API响应时间
        api_stats = current.get("api_stats", {})
        avg_ms = api_stats.get("avg_ms", 0)

        if avg_ms > 1000:
            analysis["issues"].append({
                "level": "critical",
                "type": "slow_api",
                "message": f"API平均响应时间过高: {avg_ms:.0f}ms (>1000ms)",
                "value": avg_ms,
                "threshold": 1000,
            })
            score_deductions.append(30)
        elif avg_ms > 500:
            analysis["issues"].append({
                "level": "warning",
                "type": "slow_api",
                "message": f"API平均响应时间偏高: {avg_ms:.0f}ms (>500ms)",
                "value": avg_ms,
                "threshold": 500,
            })
            score_deductions.append(15)

        # 2. 检查错误率
        error_4xx = api_stats.get("error_4xx", 0)
        error_5xx = api_stats.get("error_5xx", 0)
        total_requests = api_stats.get("total", 1)
        error_rate = ((error_4xx + error_5xx) / total_requests * 100) if total_requests > 0 else 0

        if error_rate > 10:
            analysis["issues"].append({
                "level": "critical",
                "type": "high_error_rate",
                "message": f"错误率过高: {error_rate:.1f}% (>10%)",
                "value": error_rate,
                "threshold": 10,
            })
            score_deductions.append(25)
        elif error_rate > 5:
            analysis["issues"].append({
                "level": "warning",
                "type": "high_error_rate",
                "message": f"错误率偏高: {error_rate:.1f}% (>5%)",
                "value": error_rate,
                "threshold": 5,
            })
            score_deductions.append(10)

        # 3. 检查缓存命中率
        cache_stats = current.get("cache_stats", {})
        hit_rate = cache_stats.get("hit_rate", 0)

        if hit_rate < 50 and hit_rate > 0:
            analysis["issues"].append({
                "level": "warning",
                "type": "low_cache_hit_rate",
                "message": f"缓存命中率偏低: {hit_rate:.1f}% (<50%)",
                "value": hit_rate,
                "threshold": 50,
            })
            analysis["recommendations"].append(
                "考虑增加缓存TTL或优化缓存策略以提升命中率"
            )
            score_deductions.append(15)

        # 4. 检查内存使用
        system_res = current.get("system_resources", {})
        memory_mb = system_res.get("memory_rss_mb", 0)

        if memory_mb > 1024:
            analysis["issues"].append({
                "level": "warning",
                "type": "high_memory",
                "message": f"内存占用过高: {memory_mb:.0f}MB (>1GB)",
                "value": memory_mb,
                "threshold": 1024,
            })
            analysis["recommendations"].append(
                "建议减小LOCAL_CACHE_SIZE或清理过期缓存"
            )
            score_deductions.append(10)

        # 5. 检查慢端点
        slow_endpoints = current.get("slow_endpoints", [])
        if slow_endpoints and len(slow_endpoints) > 3:
            analysis["issues"].append({
                "level": "info",
                "type": "multiple_slow_endpoints",
                "message": f"发现{len(slow_endpoints)}个慢端点需要优化",
                "count": len(slow_endpoints),
            })

        # 计算总分
        for deduction in score_deductions:
            analysis["overall_score"] = max(0, analysis["overall_score"] - deduction)

        # 趋势分析
        if len(self.history.get("records", [])) >= 2:
            last_record = self.history["records"][-1]
            prev_avg = last_record.get("api_stats", {}).get("avg_ms", 0)
            curr_avg = api_stats.get("avg_ms", 0)

            if prev_avg > 0 and curr_avg > 0:
                change_percent = ((curr_avg - prev_avg) / prev_avg) * 100
                analysis["trends"]["response_time_change"] = round(change_percent, 2)

                if change_percent > 20:
                    analysis["recommendations"].append(
                        f"⚠️ 响应时间较上次上升 {change_percent:.1f}%，需关注"
                    )

        return analysis

    def generate_report(self, metrics: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """
        生成格式化的审查报告

        Returns:
            Markdown格式的报告文本
        """
        timestamp = metrics.get("timestamp", datetime.now().isoformat())
        score = analysis.get("overall_score", 0)
        issues = analysis.get("issues", [])
        recommendations = analysis.get("recommendations", [])

        report = []
        report.append("=" * 70)
        report.append("📊 XCAGI 性能审查报告")
        report.append("=" * 70)
        report.append(f"\n📅 审查时间: {timestamp}")
        report.append(f"📈 综合评分: {score}/100")

        # 评分等级
        if score >= 90:
            grade = "✅ 优秀"
        elif score >= 70:
            grade = "⚠️  良好"
        elif score >= 50:
            grade = "🔶 一般"
        else:
            grade = "❌ 需要改进"
        report.append(f"🎯 评级: {grade}")

        # API统计
        api_stats = metrics.get("api_stats", {})
        report.append("\n--- 📡 API 性能 ---")
        report.append(f"总请求数: {api_stats.get('total', 'N/A')}")
        report.append(f"平均延迟: {api_stats.get('avg_ms', 'N/A')}ms")
        report.append(f"P95延迟: {api_stats.get('slow_count', 'N/A')} 个慢请求")
        report.append(f"4xx错误: {api_stats.get('error_4xx', 0)}")
        report.append(f"5xx错误: {api_stats.get('error_5xx', 0)}")

        # 缓存统计
        cache_stats = metrics.get("cache_stats", {})
        report.append("\n--- 💾 缓存状态 ---")
        report.append(f"命中率: {cache_stats.get('hit_rate', 'N/A')}%")
        report.append(f"本地缓存大小: {cache_stats.get('local_cache_size', 'N/A')}")

        # 系统资源
        sys_res = metrics.get("system_resources", {})
        if sys_res:
            report.append("\n--- 💻 系统资源 ---")
            report.append(f"内存占用: {sys_res.get('memory_rss_mb', 'N/A')}MB ({sys_res.get('memory_percent', 'N/A')}%)")
            report.append(f"CPU使用率: {sys_res.get('cpu_percent', 'N/A')}%")

        # 问题列表
        if issues:
            report.append("\n--- ⚠️ 发现的问题 ---")
            for i, issue in enumerate(issues, 1):
                level_icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(issue.get("level"), "❓")
                report.append(f"{i}. {level_icon} [{issue.get('type', '').upper()}] {issue.get('message', '')}")

        # 建议
        if recommendations:
            report.append("\n--- 💡 优化建议 ---")
            for i, rec in enumerate(recommendations, 1):
                report.append(f"{i}. {rec}")

        # 趋势
        trends = analysis.get("trends", {})
        if trends:
            report.append("\n--- 📉 趋势分析 ---")
            for key, value in trends.items():
                trend_icon = "📈" if value > 0 else "📉"
                report.append(f"{trend_icon} {key}: {value:+.1f}%")

        report.append("\n" + "=" * 70)
        report.append("报告生成完成 | XCAGI Performance Auditor v1.0")
        report.append("=" * 70 + "\n")

        return "\n".join(report)

    def run_audit(self, save_to_history: bool = True) -> Dict[str, Any]:
        """
        运行完整审查流程

        Args:
            save_to_history: 是否保存到历史记录

        Returns:
            审查结果字典
        """
        print("\n🔍 开始性能审查...\n")

        # 1. 收集指标
        print("📊 [1/3] 收集性能指标...")
        metrics = self.collect_metrics()
        print(f"   ✅ 已收集 {len(metrics)} 项指标")

        # 2. 分析数据
        print("🔬 [2/3] 分析性能数据...")
        analysis = self.analyze_performance(metrics)
        print(f"   ✅ 综合评分: {analysis['overall_score']}/100")

        # 3. 生成报告
        print("📝 [3/3] 生成审查报告...")
        report_text = self.generate_report(metrics, analysis)
        print(report_text)

        # 4. 保存结果
        result = {
            "audit_time": metrics.get("timestamp"),
            "score": analysis["overall_score"],
            "metrics": metrics,
            "analysis": analysis,
            "report": report_text,
        }

        if save_to_history:
            self.history["records"].append(result)
            self.history["last_audit"] = metrics.get("timestamp")

            # 只保留最近30条记录
            if len(self.history["records"]) > 30:
                self.history["records"] = self.history["records"][-30:]

            self._save_history()

            # 保存本次报告到文件
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = self.output_dir / f"audit_{date_str}.md"
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report_text)

            print(f"💾 报告已保存: {report_file}")
            print(f"📚 历史记录: {self.history_file}")

        return result


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🚀 XCAGI 性能审查自动化工具")
    print("=" * 60)

    auditor = PerformanceAuditor()
    result = auditor.run_audit()

    # 返回退出码（用于CI/CD）
    score = result.get("score", 0)
    if score >= 80:
        print("\n✅ 审查通过！系统状态良好。")
        return 0
    elif score >= 60:
        print("\n⚠️  审查警告！存在一些问题需要注意。")
        return 1
    else:
        print("\n❌ 审查失败！存在严重性能问题，需要立即处理。")
        return 2


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
