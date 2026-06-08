#!/usr/bin/env python3
"""
第二阶段：性能基准测试和优化验证执行脚本
执行性能基准测试，验证优化效果，生成性能报告
"""

import asyncio
import subprocess
import json
import time
import sys
from pathlib import Path
from datetime import datetime

class Phase2PerformanceRunner:
    """第二阶段性能测试运行器"""
    
    def __init__(self):
        self.phase_name = "第二阶段：性能基准测试和优化验证"
        self.start_time = None
        self.report_file = Path("test_reports") / f"phase2_performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.performance_results = {}
    
    def run_performance_test(self, command, description, timeout=600):
        """运行性能测试命令"""
        print(f"🚀 开始执行: {description}")
        print(f"   命令: {command}")
        
        start_time = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            duration = time.time() - start_time
            success = result.returncode == 0
            
            status = "✅ 通过" if success else "❌ 失败"
            print(f"   {status} - 耗时: {duration:.1f}s")
            
            # 解析性能指标
            performance_metrics = self.parse_performance_metrics(result.stdout)
            
            return {
                "success": success,
                "duration": duration,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "performance_metrics": performance_metrics
            }
            
        except subprocess.TimeoutExpired:
            duration = timeout
            print(f"   ⏰ 超时 - 耗时: {duration:.1f}s")
            return {
                "success": False,
                "duration": duration,
                "error": "性能测试超时"
            }
    
    def parse_performance_metrics(self, stdout):
        """解析性能指标"""
        metrics = {}
        
        # 解析响应时间指标
        if "平均响应时间" in stdout:
            lines = stdout.split('\n')
            for line in lines:
                if "平均响应时间" in line:
                    try:
                        value = float(line.split(':')[1].split('ms')[0].strip())
                        metrics["avg_response_time"] = value
                    except:
                        pass
                elif "吞吐量" in line:
                    try:
                        value = float(line.split(':')[1].split('req')[0].strip())
                        metrics["throughput"] = value
                    except:
                        pass
        
        return metrics
    
    def run_reflex_performance_tests(self):
        """运行反射弧性能测试"""
        print("\n" + "="*60)
        print("⚡ 反射弧性能基准测试")
        print("="*60)
        
        reflex_tests = [
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestNeuroPerformanceBenchmark::test_reflex_arc_performance_comparison -v -s", 
             "反射弧性能对比测试"),
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestNeuroPerformanceBenchmark::test_concurrent_performance_benchmark -v -s", 
             "反射弧并发性能测试")
        ]
        
        reflex_results = {}
        for command, description in reflex_tests:
            result = self.run_performance_test(command, description)
            reflex_results[description] = result
        
        self.performance_results["reflex_performance"] = reflex_results
        return reflex_results
    
    def run_domain_coordination_performance_tests(self):
        """运行神经域协同性能测试"""
        print("\n" + "="*60)
        print("🧠 神经域协同性能测试")
        print("="*60)
        
        coordination_tests = [
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestNeuroPerformanceBenchmark::test_domain_coordination_performance -v -s", 
             "神经域协同响应时间测试"),
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestNeuroPerformanceBenchmark::test_concurrent_performance_benchmark -v -s", 
             "高并发协同性能测试")
        ]
        
        coordination_results = {}
        for command, description in coordination_tests:
            result = self.run_performance_test(command, description)
            coordination_results[description] = result
        
        self.performance_results["coordination_performance"] = coordination_results
        return coordination_results
    
    def run_fault_tolerance_performance_tests(self):
        """运行容错性能测试"""
        print("\n" + "="*60)
        print("🛡️  容错性能基准测试")
        print("="*60)
        
        fault_tolerance_tests = [
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestFaultTolerancePerformance::test_fault_recovery_performance -v -s", 
             "故障恢复性能测试"),
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestFaultTolerancePerformance::test_graceful_degradation_performance -v -s", 
             "优雅降级性能测试")
        ]
        
        fault_tolerance_results = {}
        for command, description in fault_tolerance_tests:
            result = self.run_performance_test(command, description)
            fault_tolerance_results[description] = result
        
        self.performance_results["fault_tolerance_performance"] = fault_tolerance_results
        return fault_tolerance_results
    
    def run_resource_usage_tests(self):
        """运行资源使用测试"""
        print("\n" + "="*60)
        print("💾 内存和资源使用测试")
        print("="*60)
        
        resource_tests = [
            ("pytest tests/neuro_optimization/test_performance_benchmark.py::TestMemoryAndResourceUsage::test_memory_usage_under_load -v -s", 
             "负载下内存使用测试")
        ]
        
        resource_results = {}
        for command, description in resource_tests:
            result = self.run_performance_test(command, description)
            resource_results[description] = result
        
        self.performance_results["resource_usage"] = resource_results
        return resource_results
    
    def analyze_performance_improvement(self):
        """分析性能提升效果"""
        print("\n" + "="*60)
        print("📈 性能提升分析")
        print("="*60)
        
        # 性能目标定义
        performance_targets = {
            "reflex_response_time": {"target": 0.5, "unit": "ms", "description": "反射弧响应时间"},
            "domain_coordination_time": {"target": 50, "unit": "ms", "description": "神经域协同时间"},
            "fault_recovery_time": {"target": 10000, "unit": "ms", "description": "故障恢复时间"},
            "throughput": {"target": 500, "unit": "req/s", "description": "系统吞吐量"}
        }
        
        improvement_analysis = {}
        
        # 分析各项性能指标
        for test_category, test_results in self.performance_results.items():
            for test_name, result in test_results.items():
                if result["success"] and "performance_metrics" in result:
                    metrics = result["performance_metrics"]
                    
                    for metric_name, target_info in performance_targets.items():
                        if metric_name in metrics:
                            actual_value = metrics[metric_name]
                            target_value = target_info["target"]
                            
                            # 计算达成度
                            if "time" in metric_name:
                                # 时间类指标：越小越好
                                achievement = (target_value - actual_value) / target_value * 100
                                status = "✅ 达标" if actual_value <= target_value else "❌ 未达标"
                            else:
                                # 吞吐量类指标：越大越好
                                achievement = (actual_value - target_value) / target_value * 100
                                status = "✅ 达标" if actual_value >= target_value else "❌ 未达标"
                            
                            improvement_analysis[f"{test_category}_{metric_name}"] = {
                                "actual": actual_value,
                                "target": target_value,
                                "achievement": achievement,
                                "status": status,
                                "description": target_info["description"]
                            }
                            
                            print(f"{target_info['description']}: {actual_value}{target_info['unit']} vs 目标{target_value}{target_info['unit']} ({status})")
        
        return improvement_analysis
    
    def generate_performance_report(self, improvement_analysis):
        """生成性能报告"""
        total_duration = time.time() - self.start_time
        
        # 统计测试结果
        total_tests = 0
        passed_tests = 0
        
        for category_results in self.performance_results.values():
            total_tests += len(category_results)
            passed_tests += sum(1 for r in category_results.values() if r["success"])
        
        report = {
            "phase": self.phase_name,
            "timestamp": datetime.now().isoformat(),
            "total_duration": total_duration,
            "summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0
            },
            "performance_analysis": improvement_analysis,
            "detailed_results": self.performance_results
        }
        
        # 确保报告目录存在
        self.report_file.parent.mkdir(exist_ok=True)
        
        # 保存报告
        with open(self.report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        return report
    
    def print_performance_summary(self, report, improvement_analysis):
        """打印性能摘要"""
        print("\n" + "="*60)
        print("📊 第二阶段性能测试摘要")
        print("="*60)
        
        summary = report["summary"]
        
        print(f"⏱️  总测试时间: {report['total_duration']:.1f}s")
        print(f"📄 性能报告文件: {self.report_file}")
        print()
        
        print("🧪 性能测试结果:")
        print(f"   通过: {summary['passed_tests']}/{summary['total_tests']}")
        print(f"   成功率: {summary['success_rate']:.1f}%")
        print()
        
        print("📈 性能提升分析:")
        for metric_key, analysis in improvement_analysis.items():
            print(f"   {analysis['description']}: {analysis['actual']} vs 目标{analysis['target']} ({analysis['status']})")
        print()
        
        # 总体评估
        performance_targets_met = sum(1 for a in improvement_analysis.values() if "✅" in a["status"])
        total_targets = len(improvement_analysis)
        
        if total_targets > 0:
            target_success_rate = performance_targets_met / total_targets * 100
            print(f"性能目标达成率: {target_success_rate:.1f}% ({performance_targets_met}/{total_targets})")
        
        overall_success = summary["success_rate"] > 80 and (total_targets == 0 or target_success_rate > 70)
        status = "✅ 第二阶段测试通过" if overall_success else "❌ 第二阶段测试失败"
        print(f"总体评估: {status}")
        
        return overall_success
    
    def run(self):
        """运行第二阶段性能测试"""
        print("🚀 开始执行第二阶段性能测试")
        print(f"阶段: {self.phase_name}")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.start_time = time.time()
        
        try:
            # 执行性能测试
            self.run_reflex_performance_tests()
            self.run_domain_coordination_performance_tests()
            self.run_fault_tolerance_performance_tests()
            self.run_resource_usage_tests()
            
            # 分析性能提升
            improvement_analysis = self.analyze_performance_improvement()
            
            # 生成报告
            report = self.generate_performance_report(improvement_analysis)
            
            # 打印摘要
            success = self.print_performance_summary(report, improvement_analysis)
            
            return success
            
        except Exception as e:
            print(f"❌ 性能测试执行出错: {e}")
            return False

async def main():
    """主函数"""
    runner = Phase2PerformanceRunner()
    success = runner.run()
    
    if success:
        print("\n🎉 第二阶段性能测试完成，可以进入第三阶段")
        sys.exit(0)
    else:
        print("\n💥 第二阶段性能测试失败，请检查问题后重试")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())