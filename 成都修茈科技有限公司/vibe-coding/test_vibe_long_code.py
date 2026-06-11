"""Test vibe-coding for long/complex code generation with quantitative analysis."""
import json
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

sys.path.insert(0, r"e:\成都修茈科技有限公司\vibe-coding\src")

from vibe_coding import VibeCoder, OpenAILLM

@dataclass
class ComplexTestCase:
    name: str
    brief: str
    expected_min_lines: int  # minimum expected code lines
    expected_features: List[str]

@dataclass
class ComplexTestResult:
    name: str
    expected_min_lines: int
    success: bool = False
    time_taken: float = 0.0
    error: str = ""
    actual_lines: int = 0
    code_length: int = 0  # character count
    test_cases_count: int = 0
    has_type_hints: bool = False
    has_docstring: bool = False
    has_error_handling: bool = False
    has_logging: bool = False
    has_validation: bool = False
    has_config: bool = False
    function_count: int = 0
    class_count: int = 0
    import_count: int = 0
    complexity_score: float = 0.0  # estimated complexity
    features_found: List[str] = field(default_factory=list)
    features_missing: List[str] = field(default_factory=list)
    code_preview: str = ""


LONG_CODE_TEST_CASES = [
    # Test 1: HTTP API client with retry, timeout, error handling
    {
        "name": "http_api_client",
        "brief": "写一个完整的HTTP API客户端类，包含以下功能：1) 支持base_url和api_key配置 2) GET/POST/PUT/DELETE方法 3) 自动重试机制（最多3次，指数退避） 4) 请求超时设置 5) 统一的错误处理和日志记录 6) 支持自定义headers和query参数",
        "expected_min_lines": 80,
        "features": ["class definition", "retry logic", "error handling", "logging", "timeout", "headers", "HTTP methods"]
    },
    # Test 2: Database connection pool
    {
        "name": "db_connection_pool",
        "brief": "写一个数据库连接池管理类，包含：1) 连接池初始化和配置 2) 获取连接（线程安全） 3) 释放连接回池 4) 连接健康检查 5) 连接超时清理 6) 池大小动态调整 7) 统计信息（活跃连接数、等待队列等）",
        "expected_min_lines": 100,
        "features": ["connection pool", "thread safety", "health check", "timeout", "dynamic sizing", "statistics", "context manager"]
    },
    # Test 3: Event system
    {
        "name": "event_system",
        "brief": "写一个完整的事件系统，包含：1) 事件注册器 2) 事件发射器 3) 同步和异步事件处理 4) 事件优先级 5) 事件拦截器（before/after） 6) 一次性事件监听 7) 事件日志和调试",
        "expected_min_lines": 90,
        "features": ["event registry", "emit", "async support", "priority", "interceptors", "once listener", "event log"]
    },
    # Test 4: Data validation framework
    {
        "name": "data_validator",
        "brief": "写一个数据验证框架，包含：1) 基础验证器（非空、长度、范围、正则） 2) 组合验证器（AND/OR） 3) 嵌套对象验证 4) 自定义错误消息 5) 验证结果报告 6) 内置常用验证规则（邮箱、手机号、URL、IP等）",
        "expected_min_lines": 120,
        "features": ["validators", "composition", "nested validation", "error messages", "result report", "built-in rules", "regex"]
    },
    # Test 5: Cache system with multiple backends
    {
        "name": "multi_backend_cache",
        "brief": "写一个多级缓存系统，包含：1) 内存缓存（LRU） 2) 文件缓存 3) 缓存键生成 4) 缓存过期策略（TTL） 5) 缓存穿透/击穿/雪崩防护 6) 缓存统计（命中率等） 7) 缓存刷新和预热",
        "expected_min_lines": 110,
        "features": ["LRU cache", "file cache", "key generation", "TTL", "cache protection", "statistics", "refresh"]
    },
    # Test 6: Workflow engine
    {
        "name": "workflow_engine",
        "brief": "写一个工作流引擎，包含：1) 节点定义（开始、结束、任务、条件分支、循环） 2) 工作流图构建 3) 工作流执行（顺序、并行） 4) 节点间数据传递 5) 异常处理和重试 6) 工作流状态持久化 7) 执行日志",
        "expected_min_lines": 130,
        "features": ["node types", "graph", "execution", "data passing", "retry", "state persistence", "logging"]
    },
    # Test 7: Rate limiter
    {
        "name": "rate_limiter",
        "brief": "写一个分布式限流器，包含：1) 固定窗口算法 2) 滑动窗口算法 3) 令牌桶算法 4) 漏桶算法 5) 限流规则配置 6) 限流统计和监控 7) 支持多维度的限流（用户/IP/API）",
        "expected_min_lines": 100,
        "features": ["fixed window", "sliding window", "token bucket", "leaky bucket", "rules config", "monitoring", "multi-dimension"]
    },
    # Test 8: Config management system
    {
        "name": "config_manager",
        "brief": "写一个完整的配置管理系统，包含：1) 多格式支持（JSON/YAML/ENV） 2) 配置分层（默认/环境/用户） 3) 配置热更新 4) 配置验证 5) 配置加密 6) 配置版本管理 7) 配置回滚",
        "expected_min_lines": 110,
        "features": ["multi-format", "layers", "hot reload", "validation", "encryption", "versioning", "rollback"]
    },
]


def analyze_long_code(source_code: str, test_case: dict) -> Dict[str, Any]:
    """Analyze generated long code for comprehensive quality metrics."""
    lines = source_code.strip().split("\n")
    
    # Basic metrics
    code_length = len(source_code)
    
    # Structural metrics
    function_count = source_code.count("def ")
    class_count = source_code.count("class ")
    import_count = sum(1 for line in lines if line.strip().startswith(("import ", "from ")))
    
    # Quality indicators
    has_type_hints = "->" in source_code and any(":" in line for line in lines if "def " in line)
    has_docstring = '"""' in source_code or "'''" in source_code
    has_error_handling = source_code.count("try:") > 0 or "except" in source_code
    has_logging = "logging" in source_code or "logger" in source_code or "log" in source_code.lower()
    has_validation = "assert" in source_code or "raise ValueError" in source_code or "validate" in source_code.lower()
    has_config = "config" in source_code.lower() or "settings" in source_code.lower()
    
    # Complexity estimation
    complexity_score = 0
    complexity_score += source_code.count("if ") * 1
    complexity_score += source_code.count("for ") * 1
    complexity_score += source_code.count("while ") * 2
    complexity_score += source_code.count("try:") * 2
    complexity_score += source_code.count("except") * 1
    complexity_score += source_code.count("async ") * 2
    complexity_score += source_code.count("with ") * 1
    complexity_score += source_code.count("lambda ") * 1
    complexity_score += class_count * 3  # classes add complexity
    
    # Feature detection
    features_found = []
    features_missing = []
    for feat in test_case.get("features", []):
        keywords = feat.lower().split()
        if any(kw in source_code.lower() for kw in keywords):
            features_found.append(feat)
        else:
            features_missing.append(feat)
    
    return {
        "actual_lines": len(lines),
        "code_length": code_length,
        "function_count": function_count,
        "class_count": class_count,
        "import_count": import_count,
        "has_type_hints": has_type_hints,
        "has_docstring": has_docstring,
        "has_error_handling": has_error_handling,
        "has_logging": has_logging,
        "has_validation": has_validation,
        "has_config": has_config,
        "complexity_score": complexity_score,
        "features_found": features_found,
        "features_missing": features_missing,
    }


def run_long_code_test():
    API_KEY = "tp-cum1pkvt1sda673mc22tmbyv5cyqyx52y8nd4us9r799w3vr"
    BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    MODEL = "mimo-v2.5-pro"

    llm = OpenAILLM(
        api_key=API_KEY,
        model=MODEL,
        base_url=BASE_URL,
        temperature=0.2,
    )

    coder = VibeCoder(llm=llm, store_dir="./test_vibe_long_code_data", llm_for_repair=True)

    print("=" * 70)
    print("vibe-coding Long Code Generation Test")
    print(f"Model: {MODEL}")
    print(f"Total test cases: {len(LONG_CODE_TEST_CASES)}")
    print("=" * 70)

    results: List[ComplexTestResult] = []

    for i, tc in enumerate(LONG_CODE_TEST_CASES, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(LONG_CODE_TEST_CASES)}] {tc['name']}")
        print(f"Expected min lines: {tc['expected_min_lines']}")
        print(f"Brief: {tc['brief'][:80]}...")
        print("-" * 70)

        result = ComplexTestResult(
            name=tc["name"],
            expected_min_lines=tc["expected_min_lines"],
        )

        start_time = time.time()
        try:
            skill = coder.code(tc["brief"], mode="brief_first")
            elapsed = time.time() - start_time
            result.success = True
            result.time_taken = elapsed

            version = skill.get_active_version()
            analysis = analyze_long_code(version.source_code, tc)
            
            result.actual_lines = analysis["actual_lines"]
            result.code_length = analysis["code_length"]
            result.function_count = analysis["function_count"]
            result.class_count = analysis["class_count"]
            result.import_count = analysis["import_count"]
            result.has_type_hints = analysis["has_type_hints"]
            result.has_docstring = analysis["has_docstring"]
            result.has_error_handling = analysis["has_error_handling"]
            result.has_logging = analysis["has_logging"]
            result.has_validation = analysis["has_validation"]
            result.has_config = analysis["has_config"]
            result.complexity_score = analysis["complexity_score"]
            result.test_cases_count = len(version.test_cases)
            result.features_found = analysis["features_found"]
            result.features_missing = analysis["features_missing"]
            result.code_preview = version.source_code[:200]

            print(f"  Time: {elapsed:.1f}s")
            print(f"  Actual lines: {result.actual_lines} (expected >= {tc['expected_min_lines']})")
            print(f"  Functions: {result.function_count}, Classes: {result.class_count}, Imports: {result.import_count}")
            print(f"  Type hints: {'Yes' if result.has_type_hints else 'No'}")
            print(f"  Docstring: {'Yes' if result.has_docstring else 'No'}")
            print(f"  Error handling: {'Yes' if result.has_error_handling else 'No'}")
            print(f"  Logging: {'Yes' if result.has_logging else 'No'}")
            print(f"  Validation: {'Yes' if result.has_validation else 'No'}")
            print(f"  Complexity: {result.complexity_score}")
            print(f"  Test cases: {result.test_cases_count}")
            print(f"  Features: {len(result.features_found)}/{len(tc['features'])} found")

            if result.actual_lines < tc["expected_min_lines"]:
                print(f"  ⚠️  Code shorter than expected!")

        except Exception as e:
            elapsed = time.time() - start_time
            result.success = False
            result.time_taken = elapsed
            result.error = str(e)[:150]
            print(f"  FAILED after {elapsed:.1f}s: {result.error}")

        results.append(result)
        time.sleep(2)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - Long Code Generation")
    print("=" * 70)

    total_success = sum(1 for r in results if r.success)
    total_rate = total_success / len(results) * 100 if results else 0
    
    print(f"\nTotal: {len(results)} | Success: {total_success} | Rate: {total_rate:.0f}%")
    print(f"Failed: {len(results) - total_success}")

    if total_success > 0:
        successful = [r for r in results if r.success]
        print(f"\nSuccessful generations:")
        print(f"  Avg time: {sum(r.time_taken for r in successful)/len(successful):.1f}s")
        print(f"  Avg lines: {sum(r.actual_lines for r in successful)/len(successful):.0f}")
        print(f"  Avg functions: {sum(r.function_count for r in successful)/len(successful):.1f}")
        print(f"  Avg classes: {sum(r.class_count for r in successful)/len(successful):.1f}")
        print(f"  Type hints coverage: {sum(1 for r in successful if r.has_type_hints)/len(successful)*100:.0f}%")
        print(f"  Docstring coverage: {sum(1 for r in successful if r.has_docstring)/len(successful)*100:.0f}%")
        print(f"  Error handling coverage: {sum(1 for r in successful if r.has_error_handling)/len(successful)*100:.0f}%")
        print(f"  Logging coverage: {sum(1 for r in successful if r.has_logging)/len(successful)*100:.0f}%")
        print(f"  Avg complexity: {sum(r.complexity_score for r in successful)/len(successful):.1f}")
        print(f"  Avg features coverage: {sum(len(r.features_found)/max(len(LONG_CODE_TEST_CASES[i]['features']),1)*100 for i, r in enumerate(results) if r.success)/len(successful):.0f}%")

    # Detailed table
    print("\n" + "=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)
    print(f"{'Name':<25} {'Status':<7} {'Time':<7} {'Lines':<6} {'Func':<5} {'Class':<5} {'Features':<10} {'Complexity':<10}")
    print("-" * 70)

    for r in results:
        status = "PASS" if r.success else "FAIL"
        time_str = f"{r.time_taken:.0f}s" if r.success else "-"
        lines_str = str(r.actual_lines) if r.success else "-"
        func_str = str(r.function_count) if r.success else "-"
        class_str = str(r.class_count) if r.success else "-"
        tc = next((t for t in LONG_CODE_TEST_CASES if t["name"] == r.name), None)
        feat_count = len(tc["features"]) if tc else 0
        feat_str = f"{len(r.features_found)}/{feat_count}" if r.success else "-"
        complex_str = f"{r.complexity_score:.0f}" if r.success else "-"
        
        print(f"{r.name:<25} {status:<7} {time_str:<7} {lines_str:<6} {func_str:<5} {class_str:<5} {feat_str:<10} {complex_str:<10}")

    # Failure analysis
    print("\n" + "=" * 70)
    print("FAILURE ANALYSIS")
    print("=" * 70)

    failed = [r for r in results if not r.success]
    if failed:
        error_patterns = {}
        for r in failed:
            if "expected_output" in r.error.lower():
                error_patterns.setdefault("LLM output format (expected_output not dict)", []).append(r.name)
            elif "json" in r.error.lower():
                error_patterns.setdefault("JSON parse error / truncated", []).append(r.name)
            elif "repair" in r.error.lower():
                error_patterns.setdefault("Repair rounds exhausted", []).append(r.name)
            else:
                error_patterns.setdefault("Other", []).append(r.name)
        
        for pattern, names in error_patterns.items():
            print(f"\n{pattern} ({len(names)} cases):")
            for name in names:
                print(f"  - {name}")
    else:
        print("No failures!")

    return results


if __name__ == "__main__":
    run_long_code_test()
