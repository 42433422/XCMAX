"""Debug sandbox_mismatch failures to understand root cause."""
import json
import sys
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

    coder = VibeCoder(llm=llm, store_dir="./test_vibe_debug_data", llm_for_repair=True)

    # Test 1: string_reverse (was passing before, now sandbox_mismatch)
    brief = "写一个函数，把输入的字符串反转后返回"
    print("=" * 70)
    print(f"Brief: {brief}")
    print("=" * 70)

    try:
        skill = coder.code(brief, mode="brief_first")
        version = skill.get_active_version()
        
        print(f"\nFunction: {version.function_name}")
        print(f"\nSource code:\n{version.source_code}")
        print(f"\nTest cases:")
        for tc in version.test_cases:
            print(f"  Case: {tc.case_id}")
            print(f"    Input:    {tc.input_data}")
            print(f"    Expected: {tc.expected_output}")
            
            # Try running it
            try:
                result = coder.run(skill.skill_id, tc.input_data)
                print(f"    Actual:   {result.output_data}")
                if result.output_data != tc.expected_output:
                    print(f"    MISMATCH! Expected {tc.expected_output}, got {result.output_data}")
                else:
                    print(f"    ✅ PASS")
            except Exception as e:
                print(f"    EXEC ERROR: {e}")
            print()

    except Exception as e:
        print(f"\nGeneration FAILED: {e}")

    # Test 2: fibonacci_cache (was passing before, now sandbox_mismatch)
    print("\n" + "=" * 70)
    brief2 = "写一个带缓存的斐波那契数列计算函数，输入n返回第n个斐波那契数"
    print(f"Brief: {brief2}")
    print("=" * 70)

    try:
        skill2 = coder.code(brief2, mode="brief_first")
        version2 = skill2.get_active_version()
        
        print(f"\nFunction: {version2.function_name}")
        print(f"\nSource code:\n{version2.source_code}")
        print(f"\nTest cases:")
        for tc in version2.test_cases:
            print(f"  Case: {tc.case_id}")
            print(f"    Input:    {tc.input_data}")
            print(f"    Expected: {tc.expected_output}")
            
            try:
                result = coder.run(skill2.skill_id, tc.input_data)
                print(f"    Actual:   {result.output_data}")
                if result.output_data != tc.expected_output:
                    print(f"    MISMATCH! Expected {tc.expected_output}, got {result.output_data}")
                else:
                    print(f"    ✅ PASS")
            except Exception as e:
                print(f"    EXEC ERROR: {e}")
            print()

    except Exception as e:
        print(f"\nGeneration FAILED: {e}")
