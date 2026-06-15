"""Test vibe-coding with MockLLM - generate a real Python function from NL brief."""
import json
import sys
sys.path.insert(0, r"e:\成都修茈科技有限公司\vibe-coding\src")

from vibe_coding import VibeCoder, MockLLM

def run_test():
    # Construct MockLLM responses for brief_first mode:
    # Round 1: spec generation (signature, test cases, etc.)
    spec_response = json.dumps({
        "skill_id": "string-reverse",
        "name": "字符串反转",
        "domain": "string manipulation",
        "function_name": "reverse_string",
        "purpose": "Reverse a given string",
        "signature": {
            "params": ["text"],
            "return_type": "dict",
            "required_params": ["text"]
        },
        "dependencies": [],
        "test_cases": [
            {"case_id": "normal", "input_data": {"text": "hello"}, "expected_output": {"result": "olleh"}},
            {"case_id": "empty", "input_data": {"text": ""}, "expected_output": {"result": ""}},
            {"case_id": "single", "input_data": {"text": "a"}, "expected_output": {"result": "a"}}
        ],
        "quality_gate": {"required_keys": ["result"]},
        "domain_keywords": ["string", "reverse"]
    })

    # Round 2: code generation (based on the spec)
    code_response = json.dumps({
        "source_code": "def reverse_string(text):\n    return {'result': text[::-1]}\n"
    })

    # Create MockLLM with the two responses (queue mode)
    llm = MockLLM([spec_response, code_response])

    # Create VibeCoder
    coder = VibeCoder(llm=llm, store_dir="./test_vibe_data")

    print("=" * 60)
    print("Testing vibe-coding: NL brief -> Code -> Sandbox -> Result")
    print("=" * 60)

    brief = "写一个函数，把输入的字符串反转后返回"
    print(f"\nBrief: {brief}")
    print(f"\nGenerating code...")

    skill = coder.code(brief, mode="brief_first")
    print(f"\nSuccess! Skill generated: {skill.skill_id}")
    
    version = skill.get_active_version()
    print(f"\nFunction: {version.function_name}")
    print(f"\nSource code:\n{version.source_code}")
    
    print(f"\nTest cases:")
    for tc in version.test_cases:
        print(f"  - {tc.case_id}: input={tc.input_data}, expected={tc.expected_output}")
    
    # Now execute the skill with actual input
    print(f"\nExecuting skill with input: {{'text': 'hello world'}}")
    result = coder.run(skill.skill_id, {"text": "hello world"})
    print(f"Result: {result.output_data}")
    print(f"Stage: {result.stage}")
    
    if result.error:
        print(f"Error: {result.error}")
    
    # Try another input
    print(f"\nExecuting skill with input: {{'text': 'vibe-coding'}}")
    result2 = coder.run(skill.skill_id, {"text": "vibe-coding"})
    print(f"Result: {result2.output_data}")
    
    # Show history
    print(f"\nSkill history:")
    history = coder.history(skill.skill_id)
    print(f"  Total versions: {len(history)}")
    for record in history:
        print(f"  - {record}")
    
    print(f"\nReport: {coder.report()}")
    
    print("\n" + "=" * 60)
    print("Test PASSED! vibe-coding works correctly.")
    print("=" * 60)


if __name__ == "__main__":
    run_test()
