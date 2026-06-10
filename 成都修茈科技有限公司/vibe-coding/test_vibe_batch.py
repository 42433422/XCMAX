"""Batch test vibe-coding with different difficulty levels to get quantitative data."""
import json
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, r"e:\成都修茈科技有限公司\vibe-coding\src")

from vibe_coding import VibeCoder, OpenAILLM

@dataclass
class TestCase:
    name: str
    brief: str
    difficulty: str  # easy, medium, hard, very_hard
    expected_features: List[str]  # what the generated code should have

@dataclass
class TestResult:
    name: str
    difficulty: str
    success: bool = False
    time_taken: float = 0.0
    error: str = ""
    function_name: str = ""
    code_lines: int = 0
    test_cases_count: int = 0
    has_type_hints: bool = False
    has_docstring: bool = False
    has_error_handling: bool = False
    features_found: List[str] = field(default_factory=list)
    features_missing: List[str] = field(default_factory=list)


# Define test cases with increasing difficulty
TEST_CASES = [
    # Easy - basic string/list manipulation
    TestCase(
        name="string_reverse",
        brief="写一个函数，把输入的字符串反转后返回",
        difficulty="easy",
        expected_features=["text slicing", "return dict"],
    ),
    TestCase(
        name="list_filter_sort",
        brief="写一个Python函数，接收一个字符串列表，返回其中长度大于3的字符串，按字母顺序排序",
        difficulty="easy",
        expected_features=["list comprehension", "sorted", "len filter"],
    ),
    # Medium - data processing
    TestCase(
        name="json_csv_sum",
        brief="写一个函数，解析JSON格式的CSV数据，提取第2列的数字并求和，返回包含sum和rows计数的字典",
        difficulty="medium",
        expected_features=["json.loads", "iteration", "type checking", "error handling"],
    ),
    TestCase(
        name="dict_merge",
        brief="写一个函数，合并两个字典，如果键冲突则把值合并成一个列表",
        difficulty="medium",
        expected_features=["dict iteration", "list append", "key conflict handling"],
    ),
    # Hard - algorithm
    TestCase(
        name="fibonacci_cache",
        brief="写一个带缓存的斐波那契数列计算函数，输入n返回第n个斐波那契数",
        difficulty="hard",
        expected_features=["recursion", "caching/memoization", "base cases"],
    ),
    TestCase(
        name="binary_search",
        brief="写一个二分查找函数，在有序列表中查找目标值，返回索引，找不到返回-1",
        difficulty="hard",
        expected_features=["binary search", "while loop", "mid calculation"],
    ),
    # Very Hard - complex business logic
    TestCase(
        name="text_frequency",
        brief="写一个函数，统计一段英文文本中每个单词的出现频率，返回按频率降序排列的前N个单词和它们的计数",
        difficulty="very_hard",
        expected_features=["text splitting", "frequency counting", "sorting", "top N"],
    ),
    TestCase(
        name="nested_flatten",
        brief="写一个函数，把任意深度的嵌套列表展平为一维列表，支持列表中包含字典和元组",
        difficulty="very_hard",
        expected_features=["recursion", "type checking", "yield/extend"],
    ),
]


def analyze_code(source_code: str, expected_features: List[str]) -> dict:
    """Analyze generated code for quality metrics."""
    lines = source_code.strip().split("\n")
    
    has_type_hints = "->" in source_code and ":" in source_code
    has_docstring = '"""' in source_code or "'''" in source_code
    has_error_handling = "try:" in source_code or "except" in source_code
    has_import = "import" in source_code
    
    # Check for expected features
    features_found = []
    features_missing = []
    for feat in expected_features:
        # Simple heuristic check
        if feat.lower() in source_code.lower() or \
           any(keyword in source_code.lower() for keyword in feat.split()):
            features_found.append(feat)
        else:
            features_missing.append(feat)
    
    return {
        "code_lines": len(lines),
        "has_type_hints": has_type_hints,
        "has_docstring": has_docstring,
        "has_error_handling": has_error_handling,
        "has_import": has_import,
        "features_found": features_found,
        "features_missing": features_missing,
    }


def run_batch_test():
    API_KEY = "tp-cum1pkvt1sda673mc22tmbyv5cyqyx52y8nd4us9r799w3vr"
    BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    MODEL = "mimo-v2.5-pro"

    llm = OpenAILLM(
        api_key=API_KEY,
        model=MODEL,
        base_url=BASE_URL,
        temperature=0.2,
    )

    coder = VibeCoder(llm=llm, store_dir="./test_vibe_batch_data", llm_for_repair=True)

    print("=" * 70)
    print("vibe-coding Batch Test - Quantitative Analysis")
    print(f"Model: {MODEL}")
    print(f"Total test cases: {len(TEST_CASES)}")
    print("=" * 70)

    results: List[TestResult] = []

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{len(TEST_CASES)}] {tc.name} (difficulty: {tc.difficulty})")
        print(f"Brief: {tc.brief}")
        print("-" * 70)

        result = TestResult(
            name=tc.name,
            difficulty=tc.difficulty,
        )

        start_time = time.time()
        try:
            skill = coder.code(tc.brief, mode="brief_first")
            elapsed = time.time() - start_time
            result.success = True
            result.time_taken = elapsed

            version = skill.get_active_version()
            result.function_name = version.function_name
            analysis = analyze_code(version.source_code, tc.expected_features)
            
            result.code_lines = analysis["code_lines"]
            result.has_type_hints = analysis["has_type_hints"]
            result.has_docstring = analysis["has_docstring"]
            result.has_error_handling = analysis["has_error_handling"]
            result.test_cases_count = len(version.test_cases)
            result.features_found = analysis["features_found"]
            result.features_missing = analysis["features_missing"]

            print(f"  Time: {elapsed:.1f}s")
            print(f"  Function: {version.function_name}")
            print(f"  Code lines: {result.code_lines}")
            print(f"  Type hints: {'Yes' if result.has_type_hints else 'No'}")
            print(f"  Docstring: {'Yes' if result.has_docstring else 'No'}")
            print(f"  Error handling: {'Yes' if result.has_error_handling else 'No'}")
            print(f"  Test cases: {result.test_cases_count}")
            print(f"  Features found: {len(result.features_found)}/{len(tc.expected_features)}")

            # Try to execute
            if version.test_cases:
                first_tc = version.test_cases[0]
                try:
                    exec_result = coder.run(skill.skill_id, first_tc.input_data)
                    print(f"  First test exec: {exec_result.output_data}")
                except Exception as e:
                    print(f"  First test exec FAILED: {e}")

        except Exception as e:
            elapsed = time.time() - start_time
            result.success = False
            result.time_taken = elapsed
            result.error = str(e)[:100]
            print(f"  FAILED after {elapsed:.1f}s: {result.error}")

        results.append(result)
        time.sleep(2)  # Rate limit

    # Print summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Group by difficulty
    by_difficulty = {}
    for r in results:
        by_difficulty.setdefault(r.difficulty, []).append(r)

    print(f"\n{'Difficulty':<12} {'Total':<6} {'Success':<8} {'Rate':<8} {'Avg Time':<10} {'Avg Lines':<10} {'Features%':<10}")
    print("-" * 70)

    for diff in ["easy", "medium", "hard", "very_hard"]:
        group = by_difficulty.get(diff, [])
        if not group:
            continue
        total = len(group)
        success_count = sum(1 for r in group if r.success)
        rate = success_count / total * 100
        avg_time = sum(r.time_taken for r in group if r.success) / max(success_count, 1)
        avg_lines = sum(r.code_lines for r in group if r.success) / max(success_count, 1)
        avg_feat = sum(len(r.features_found) / max(len(tc.expected_features), 1) * 100 
                       for r, tc in zip(group, [t for t in TEST_CASES if t.name == r.name]) if r.success) / max(success_count, 1)

        print(f"{diff:<12} {total:<6} {success_count:<8} {rate:<8.0f}% {avg_time:<10.1f}s {avg_lines:<10.0f} {avg_feat:<10.0f}%")

    print("-" * 70)
    total_success = sum(1 for r in results if r.success)
    total_rate = total_success / len(results) * 100
    avg_time_all = sum(r.time_taken for r in results if r.success) / max(total_success, 1)
    print(f"{'TOTAL':<12} {len(results):<6} {total_success:<8} {total_rate:<8.0f}% {avg_time_all:<10.1f}s")

    # Detailed results
    print("\n" + "=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)

    for r in results:
        status = "PASS" if r.success else "FAIL"
        print(f"\n[{status}] {r.name} ({r.difficulty})")
        if r.success:
            print(f"  Time: {r.time_taken:.1f}s, Lines: {r.code_lines}, Tests: {r.test_cases_count}")
            print(f"  Type hints: {'Yes' if r.has_type_hints else 'No'}, "
                  f"Docstring: {'Yes' if r.has_docstring else 'No'}, "
                  f"Error handling: {'Yes' if r.has_error_handling else 'No'}")
            if r.features_missing:
                print(f"  Missing features: {r.features_missing}")
        else:
            print(f"  Error: {r.error}")

    return results


if __name__ == "__main__":
    run_batch_test()
