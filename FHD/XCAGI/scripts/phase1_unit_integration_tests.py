#!/usr/bin/env python3
"""
第一阶段：基础单元测试和集成测试执行脚本
执行单元测试和集成测试，生成测试报告
"""

import asyncio
import subprocess
import json
import time
import sys
from pathlib import Path
from datetime import datetime

class Phase1TestRunner:
    """第一阶段测试运行器"""
    
    def __init__(self):
        self.phase_name = "第一阶段：基础单元测试和集成测试"
        self.start_time = None
        self.report_file = Path("test_reports") / f"phase1_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.test_results = {}
    
    def run_command(self, command, description, timeout=300):
        """运行测试命令"""
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
            
            return {
                "success": success,
                "duration": duration,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
            
        except subprocess.TimeoutExpired:
            duration = timeout
            print(f"   ⏰ 超时 - 耗时: {duration:.1f}s")
            return {
                "success": False,
                "duration": duration,
                "error": "测试超时"
            }
    
    def run_unit_tests(self):
        """运行单元测试"""
        print("\n" + "="*60)
        print("🧪 执行单元测试")
        print("="*60)
        
        unit_test_commands = [
            ("pytest tests/neuro_optimization/ -m unit -v --tb=short", 
             "神经突触协同机制单元测试"),
            ("pytest tests/neuro_optimization/ -m 'unit and not integration' -v", 
             "自适应容错框架单元测试"),
            ("pytest tests/neuro_optimization/ -m 'unit and not stress' -v", 
             "多级反射引擎单元测试")
        ]
        
        unit_results = {}
        for command, description in unit_test_commands:
            result = self.run_command(command, description)
            unit_results[description] = result
        
        self.test_results["unit_tests"] = unit_results
        return unit_results
    
    def run_integration_tests(self):
        """运行集成测试"""
        print("\n" + "="*60)
        print("🔗 执行集成测试")
        print("="*60)
        
        integration_test_commands = [
            ("pytest tests/neuro_optimization/ -m integration -v --tb=short", 
             "神经域协同集成测试"),
            ("pytest tests/neuro_optimization/test_domain_coordination_integration.py -v", 
             "跨域状态同步集成测试"),
            ("pytest tests/neuro_optimization/ -m 'integration and not stress' -v", 
             "容错能力集成测试")
        ]
        
        integration_results = {}
        for command, description in integration_test_commands:
            result = self.run_command(command, description, timeout=600)  # 集成测试超时10分钟
            integration_results[description] = result
        
        self.test_results["integration_tests"] = integration_results
        return integration_results
    
    def calculate_coverage(self):
        """计算测试覆盖率"""
        print("\n" + "="*60)
        print("📊 计算测试覆盖率")
        print("="*60)
        
        coverage_commands = [
            ("pytest tests/neuro_optimization/ --cov=app.neuro_domains --cov-report=term-missing", 
             "神经域模块覆盖率"),
            ("pytest tests/neuro_optimization/ --cov=app.neuro_bus --cov-report=term-missing", 
             "神经总线模块覆盖率"),
            ("pytest tests/neuro_optimization/ --cov=app --cov-report=html", 
             "生成HTML覆盖率报告")
        ]
        
        coverage_results = {}
        for command, description in coverage_commands:
            result = self.run_command(command, description, timeout=600)
            coverage_results[description] = result
        
        self.test_results["coverage"] = coverage_results
        return coverage_results
    
    def generate_report(self):
        """生成测试报告"""
        total_duration = time.time() - self.start_time
        
        # 统计测试结果
        unit_success = sum(1 for r in self.test_results.get("unit_tests", {}).values() if r["success"])
        unit_total = len(self.test_results.get("unit_tests", {}))
        
        integration_success = sum(1 for r in self.test_results.get("integration_tests", {}).values() if r["success"])
        integration_total = len(self.test_results.get("integration_tests", {}))
        
        report = {
            "phase": self.phase_name,
            "timestamp": datetime.now().isoformat(),
            "total_duration": total_duration,
            "summary": {
                "unit_tests": {
                    "passed": unit_success,
                    "total": unit_total,
                    "success_rate": (unit_success / unit_total * 100) if unit_total > 0 else 0
                },
                "integration_tests": {
                    "passed": integration_success,
                    "total": integration_total,
                    "success_rate": (integration_success / integration_total * 100) if integration_total > 0 else 0
                }
            },
            "detailed_results": self.test_results
        }
        
        # 确保报告目录存在
        self.report_file.parent.mkdir(exist_ok=True)
        
        # 保存报告
        with open(self.report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        return report
    
    def print_summary(self, report):
        """打印测试摘要"""
        print("\n" + "="*60)
        print("📋 第一阶段测试摘要")
        print("="*60)
        
        unit_summary = report["summary"]["unit_tests"]
        integration_summary = report["summary"]["integration_tests"]
        
        print(f"⏱️  总测试时间: {report['total_duration']:.1f}s")
        print(f"📄 测试报告文件: {self.report_file}")
        print()
        
        print("🧪 单元测试结果:")
        print(f"   通过: {unit_summary['passed']}/{unit_summary['total']}")
        print(f"   成功率: {unit_summary['success_rate']:.1f}%")
        print()
        
        print("🔗 集成测试结果:")
        print(f"   通过: {integration_summary['passed']}/{integration_summary['total']}")
        print(f"   成功率: {integration_summary['success_rate']:.1f}%")
        print()
        
        # 总体评估
        overall_success = unit_summary["success_rate"] > 80 and integration_summary["success_rate"] > 70
        status = "✅ 第一阶段测试通过" if overall_success else "❌ 第一阶段测试失败"
        print(f"总体评估: {status}")
        
        return overall_success
    
    def run(self):
        """运行第一阶段测试"""
        print("🚀 开始执行第一阶段测试")
        print(f"阶段: {self.phase_name}")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        self.start_time = time.time()
        
        try:
            # 执行测试
            self.run_unit_tests()
            self.run_integration_tests()
            self.calculate_coverage()
            
            # 生成报告
            report = self.generate_report()
            
            # 打印摘要
            success = self.print_summary(report)
            
            return success
            
        except Exception as e:
            print(f"❌ 测试执行出错: {e}")
            return False

async def main():
    """主函数"""
    runner = Phase1TestRunner()
    success = runner.run()
    
    if success:
        print("\n🎉 第一阶段测试完成，可以进入第二阶段")
        sys.exit(0)
    else:
        print("\n💥 第一阶段测试失败，请检查问题后重试")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())