"""Test vibe-coding with REAL MIMO API - generate a real Python function from NL brief."""
import json
import sys
sys.path.insert(0, r"e:\成都修茈科技有限公司\vibe-coding\src")

from vibe_coding import VibeCoder, OpenAILLM

if __name__ == "__main__":
    # Use MIMO API (OpenAI-compatible)
    API_KEY = "tp-cum1pkvt1sda673mc22tmbyv5cyqyx52y8nd4us9r799w3vr"
    BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    MODEL = "mimo-v2.5-pro"

    llm = OpenAILLM(
        api_key=API_KEY,
        model=MODEL,
        base_url=BASE_URL,
        temperature=0.2,
    )

    coder = VibeCoder(llm=llm, store_dir="./test_vibe_data_real", llm_for_repair=True)

    print("=" * 60)
    print("Testing vibe-coding with REAL MIMO API")
    print(f"Model: {MODEL}")
    print(f"Base URL: {BASE_URL}")
    print("=" * 60)

    # Test 1: Simple function
    brief = "写一个Python函数，接收一个字符串列表，返回其中长度大于3的字符串，按字母顺序排序"
    print(f"\nBrief: {brief}")
    print("\nGenerating code (this may take 10-30s)...")

    try:
        skill = coder.code(brief, mode="brief_first")
        print(f"\nSuccess! Skill: {skill.skill_id}")
        
        version = skill.get_active_version()
        print(f"\nFunction: {version.function_name}")
        print(f"\nSource code:\n{version.source_code}")
        
        print(f"\nTest cases:")
        for tc in version.test_cases:
            print(f"  - {tc.case_id}: input={tc.input_data}, expected={tc.expected_output}")
        
        print(f"\nExecuting skill with input: {{'items': ['hello', 'hi', 'world', 'ok', 'python']}}")
        result = coder.run(skill.skill_id, {"items": ["hello", "hi", "world", "ok", "python"]})
        print(f"Result: {result.output_data}")
        
        print("\n" + "=" * 60)
        print("Test 1 PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nTest 1 FAILED: {e}")
        import traceback
        traceback.print_exc()

    # Test 2: More complex function
    brief2 = "写一个函数，解析JSON格式的CSV数据，提取第2列的数字并求和，返回包含sum和rows计数的字典"
    print(f"\n\nBrief: {brief2}")
    print("\nGenerating code...")

    try:
        skill2 = coder.code(brief2, mode="brief_first")
        print(f"\nSuccess! Skill: {skill2.skill_id}")
        
        version2 = skill2.get_active_version()
        print(f"\nFunction: {version2.function_name}")
        print(f"\nSource code:\n{version2.source_code}")
        
        print(f"\nTest cases:")
        for tc in version2.test_cases:
            print(f"  - {tc.case_id}: input={tc.input_data}, expected={tc.expected_output}")
        
        print("\n" + "=" * 60)
        print("Test 2 PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nTest 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
