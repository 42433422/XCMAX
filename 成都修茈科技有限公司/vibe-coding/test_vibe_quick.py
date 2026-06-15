"""Quick test for vibe-coding - 4 key test cases to verify optimization."""
import json
import sys
import time

sys.path.insert(0, r"e:\成都修茈科技有限公司\vibe-coding\src")

from vibe_coding import VibeCoder, OpenAILLM

if __name__ == "__main__":
    API_KEY = "tp-cum1pkvt1sda673mc22tmbyv5cyqyx52y8nd4us9r799w3vr"
    BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    MODEL = "mimo-v2.5-pro"

    llm = OpenAILLM(
        api_key=API_KEY,
        model=MODEL,
        base_url=BASE_URL,
        temperature=0.2,
    )

    coder = VibeCoder(llm=llm, store_dir="./test_vibe_quick_data", llm_for_repair=True)

    briefs = [
        ("string_reverse", "easy", "写一个函数，把输入的字符串反转后返回"),
        ("dict_merge", "medium", "写一个函数，合并两个字典，如果键冲突则把值合并成一个列表"),
        ("fibonacci_cache", "hard", "写一个带缓存的斐波那契数列计算函数，输入n返回第n个斐波那契数"),
        ("text_frequency", "very_hard", "写一个函数，统计一段英文文本中每个单词的出现频率，返回按频率降序排列的前N个单词和它们的计数"),
    ]

    results = []

    print("=" * 70)
    print("Quick Test - vibe-coding Optimization Verification")
    print(f"Model: {MODEL}")
    print("=" * 70)

    for name, diff, brief in briefs:
        print(f"\n{'='*70}")
        print(f"[{diff}] {name}: {brief}")
        print("-" * 70)

        start = time.time()
        try:
            skill = coder.code(brief, mode="brief_first")
            elapsed = time.time() - start
            version = skill.get_active_version()
            
            print(f"  PASS in {elapsed:.0f}s")
            print(f"  Function: {version.function_name}")
            print(f"  Lines: {version.source_code.count(chr(10)) + 1}")
            has_doc = '"""' in version.source_code or "'''" in version.source_code
            print(f"  Docstring: {'Yes' if has_doc else 'No'}")
            print(f"  Test cases: {len(version.test_cases)}")
            
            # Run first test case
            first_tc = version.test_cases[0]
            result = coder.run(skill.skill_id, first_tc.input_data)
            print(f"  First test: {result.output_data}")
            
            results.append((name, diff, True, elapsed, version.source_code.count(chr(10)) + 1))
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"  FAIL after {elapsed:.0f}s: {str(e)[:120]}")
            results.append((name, diff, False, elapsed, 0))
        
        time.sleep(2)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    success = sum(1 for _, _, ok, _, _ in results if ok)
    total = len(results)
    avg_time = sum(t for _, _, ok, t, _ in results if ok) / max(success, 1)
    avg_lines = sum(l for _, _, ok, _, l in results if ok) / max(success, 1)
    
    print(f"Success rate: {success}/{total} ({success/total*100:.0f}%)")
    print(f"Avg time (success): {avg_time:.0f}s")
    print(f"Avg lines (success): {avg_lines:.0f}")
    
    print(f"\n{'Name':<20} {'Diff':<10} {'Status':<6} {'Time':<7} {'Lines':<5}")
    print("-" * 70)
    for name, diff, ok, t, lines in results:
        print(f"{name:<20} {diff:<10} {'PASS' if ok else 'FAIL':<6} {t:<7.0f}s {lines:<5}")
