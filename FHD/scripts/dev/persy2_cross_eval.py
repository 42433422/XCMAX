"""persy2 交叉评估脚本：mimo + bai/minimax-m3 交叉测试 persona 拟人度。

交叉逻辑：
- 评估员=mimo → persona 回复用 bai/minimax-m3 生成
- 评估员=bai  → persona 回复用 mimo 生成
避免自评偏差。

用法：
    cd FHD && python scripts/dev/persy2_cross_eval.py [--rounds 10] [--industry 零售业]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
from dotenv import load_dotenv

load_dotenv()

# ========== 模型配置 ==========
MODELS = {
    "mimo": {
        "api_key": os.environ.get("MIMO_API_KEY", ""),
        "base_url": os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
        "model": os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
        "display": "MiMo",
    },
    "bai": {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.b.ai/v1"),
        "model": os.environ.get("OPENAI_MODEL", "MiniMax-M3"),
        "display": "B.AI/MiniMax-M3",
    },
}

# ========== Prompt 模板 ==========
EVALUATOR_SYSTEM = """你是一个真实的用户，正在和一个客服助手聊天。
请像真人一样自然地聊天，多闲聊、拉家常、聊日常，少问业务问题。
可以聊天气、周末、工作、吃喝、追剧、游戏、生活琐事。
不要刻意测试对方，就自然地聊天。
每次只发一条消息，简短自然，像微信聊天一样，不要太长。
直接输出你要说的话，不要输出思考过程，不要输出引号。

重要：你是一个真人用户，不是 AI，不是客服，不是助手。
不要说自己是 AI、客服、助手、机器人，不要用"小助手"这种词。
不要用 emoji 表情符号。
如果对方问你是谁，你就说一个普通职业，比如上班族、学生、自由职业。
打分时只评估客服（对方）的回复，不要因为你自己说的话扣对方的分。"""

SCORER_SYSTEM = """你是一个专业的评估员，刚刚观察了一段客服对话。
请评估客服回复是否像真人，从以下维度打分（0-100）：

1. naturalness：回复是否像真人说话，有无机器味
2. emotion：是否有情感波动，还是冷冰冰
3. consistency：前后回复是否一致，有无矛盾
4. personality：是否有独特个性，还是千篇一律
5. appropriateness：反应是否适度，有无过度或不足

total = 五个维度的加权平均。

请严格只输出一行 JSON，不要输出其他内容：
{"naturalness": 75, "emotion": 60, "consistency": 80, "personality": 50, "appropriateness": 70, "total": 67, "leaks": ["露馅点1", "露馅点2"], "summary": "总体评价"}"""

# 可选的 prompt 增强（优化迭代时使用）
# 第9轮 boost：极简核心规则 + 禁反问（效果最稳定）
PROMPT_BOOST = """聊天规则：
1. 直接说话，不要输出思考过程
2. 不要emoji、不要格式、不要列表、不要分点
3. 每次一两句，不超过30字，像微信聊天
4. 绝对不要反问对方，直接说自己的事
5. 像跟朋友聊天，不像客服，别用建议/方案/请问这些词"""


def strip_think(text: str) -> str:
    """过滤 <think>...</think> 标签。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def llm_chat(model_key: str, messages: list[dict], **params) -> str:
    """调用 LLM API，返回纯文本回复。带重试。"""
    cfg = MODELS[model_key]
    url = cfg["base_url"] + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    payload: dict = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": params.get("temperature", 0.7),
        "max_tokens": params.get("max_tokens", 500),
        "top_p": params.get("top_p", 0.9),
    }
    if params.get("frequency_penalty"):
        payload["frequency_penalty"] = params["frequency_penalty"]
    last_err = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            return strip_think(content)
        except Exception as e:
            last_err = e
            # 429 限流用更长延迟（15秒），其他错误 2 秒
            is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
            delay = 15 if is_rate_limit else 2
            print(f"  [llm_chat 重试 {attempt+1}/3] {model_key} 失败: {type(e).__name__}: {e}")
            await asyncio.sleep(delay)
    raise RuntimeError(f"{model_key} API 调用失败（3次重试）: {type(last_err).__name__}: {last_err}")


def init_persona_service():
    """初始化 PersonaService（mock repo + 真实依赖）。"""
    from app.services.persona.axes_fuser import AxesFuser
    from app.services.persona.identity_resolver import IdentityResolver
    from app.services.persona.param_mapper import PersonaParamMapper
    from app.services.persona.persona_service import PersonaService
    from app.services.persona.prompt_builder import PersonaPromptBuilder
    from app.services.persona.rapport_calculator import RapportCalculator
    from app.services.persona.rule_inferencer import RuleInferencer

    repo = MagicMock()
    repo.find_by_user_id = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    repo.append_event = AsyncMock()

    return PersonaService(
        repo=repo,
        rule_inferencer=RuleInferencer(),
        embedding_inferencer=MagicMock(),
        llm_inferencer=MagicMock(),
        axes_fuser=AxesFuser(),
        rapport_calculator=RapportCalculator(),
        identity_resolver=IdentityResolver(),
        prompt_builder=PersonaPromptBuilder(IdentityResolver()),
        param_mapper=PersonaParamMapper(),
    )


async def run_evaluator(
    eval_model: str,
    cross_model: str,
    persona_service,
    industry: str,
    rounds: int,
    prompt_boost: str,
) -> dict:
    """运行一个评估员的完整对话+打分。

    Args:
        eval_model: 评估员模型 key（"mimo" 或 "bai"）
        cross_model: persona 回复生成模型 key（交叉）
        persona_service: PersonaService 实例
        industry: 行业
        rounds: 对话轮数
        prompt_boost: 额外 prompt 增强（优化迭代用）

    Returns:
        dict: 对话记录 + 打分
    """
    user_id = f"eval-{eval_model}"
    persona_history: list[dict] = []  # persona 视角的对话历史
    eval_messages: list[dict] = [
        {"role": "system", "content": EVALUATOR_SYSTEM},
        {"role": "user", "content": "开始聊天吧，你先说"},
    ]
    dialogue: list[dict] = []  # 完整对话记录（用于输出）

    for i in range(rounds):
        # 1. 评估员生成消息
        t0 = time.time()
        user_msg = await llm_chat(eval_model, eval_messages, max_tokens=400, temperature=0.8)
        if not user_msg or not user_msg.strip():
            user_msg = "嗯嗯，然后呢"
        latency_eval = time.time() - t0
        eval_messages.append({"role": "assistant", "content": user_msg})
        dialogue.append({"round": i + 1, "speaker": "evaluator", "model": eval_model, "content": user_msg, "latency_s": round(latency_eval, 2)})

        # 2. persona 生成回复
        t0 = time.time()
        system_prompt, params = await persona_service.build_prompt_from_message(
            user_id=user_id,
            message=user_msg,
            history=persona_history,
            industry=industry,
            context_prompt="",
        )
        if prompt_boost:
            system_prompt = system_prompt + "\n\n" + prompt_boost

        persona_messages = [{"role": "system", "content": system_prompt}]
        persona_messages.extend(persona_history)
        persona_messages.append({"role": "user", "content": user_msg})

        # 确保 max_tokens 足够大（think 标签会占用 token）
        if params.get("max_tokens", 0) < 800:
            params["max_tokens"] = 800
        persona_reply = await llm_chat(cross_model, persona_messages, **params)
        if not persona_reply or not persona_reply.strip():
            persona_reply = "嗯"
        latency_persona = time.time() - t0

        persona_history.append({"role": "user", "content": user_msg})
        persona_history.append({"role": "assistant", "content": persona_reply})
        eval_messages.append({"role": "user", "content": persona_reply})
        dialogue.append({"round": i + 1, "speaker": "persona", "model": cross_model, "content": persona_reply, "latency_s": round(latency_persona, 2), "system_prompt": system_prompt})

        print(f"  [{i+1}/{rounds}] 评估员({eval_model}): {user_msg[:60]}")
        print(f"  [{i+1}/{rounds}] persona({cross_model}): {persona_reply[:60]}")
        print()
        # 每轮对话之间加 3 秒延迟，避免 API 限流
        if i < rounds - 1:
            await asyncio.sleep(3)

    # 3. 打分（带重试，失败时用短上下文重试）
    score = {"error": "打分失败"}
    for score_attempt in range(3):
        try:
            if score_attempt == 0:
                score_messages = list(eval_messages)
            else:
                # 短上下文重试：只保留 system + 对话摘要
                dialogue_text = "\n".join(
                    [f"{'用户' if d['speaker']=='evaluator' else '客服'}: {d['content']}" for d in dialogue]
                )
                score_messages = [
                    {"role": "system", "content": SCORER_SYSTEM},
                    {"role": "user", "content": f"对话记录：\n{dialogue_text}\n\n请输出打分 JSON"},
                ]
            score_messages.append({"role": "system", "content": SCORER_SYSTEM})
            score_messages.append({"role": "user", "content": "请输出打分 JSON"})
            score_raw = await llm_chat(eval_model, score_messages, max_tokens=1500, temperature=0.3)
            score = parse_score(score_raw)
            if "error" not in score:
                break
            print(f"  [打分重试 {score_attempt+1}/3] 解析失败，重试...")
        except Exception as e:
            print(f"  [打分重试 {score_attempt+1}/3] {type(e).__name__}: {e}")
            score_raw = f"打分异常: {type(e).__name__}: {e}"

    return {
        "eval_model": eval_model,
        "cross_model": cross_model,
        "industry": industry,
        "rounds": rounds,
        "dialogue": dialogue,
        "score_raw": score_raw,
        "score": score,
    }


def parse_score(raw: str) -> dict:
    """解析打分 JSON（容错处理，支持嵌套花括号和 markdown 代码块）。"""
    # 1. 尝试从 markdown 代码块提取
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if code_match:
        raw = code_match.group(1)
    # 2. 尝试直接解析
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass
    # 3. 提取第一个完整的 JSON 对象（支持嵌套花括号）
    depth = 0
    start = -1
    for i, c in enumerate(raw):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    # 4. fallback：旧的正则（不含嵌套花括号）
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"error": "无法解析打分", "raw": raw[:500]}


async def main():
    parser = argparse.ArgumentParser(description="persy2 交叉评估")
    parser.add_argument("--rounds", type=int, default=10, help="对话轮数")
    parser.add_argument("--industry", default="零售业", help="行业")
    parser.add_argument("--boost", default=PROMPT_BOOST, help="prompt 增强（优化迭代用）")
    parser.add_argument("--output", default="resources/persy2/eval_history.jsonl", help="输出文件")
    args = parser.parse_args()

    # 确保在 FHD 目录
    fhd_dir = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(fhd_dir))
    os.chdir(fhd_dir)

    print("=" * 70)
    print(f"persy2 交叉评估 | 行业={args.industry} | 轮数={args.rounds}")
    print(f"评估员1: mimo ({MODELS['mimo']['display']}) → persona用 bai 生成")
    print(f"评估员2: bai  ({MODELS['bai']['display']}) → persona用 mimo 生成")
    if args.boost:
        print(f"Prompt 增强: {args.boost[:80]}...")
    print("=" * 70)

    # 初始化 PersonaService
    persona_service = init_persona_service()

    # 运行两个评估员
    results = {}
    for eval_m, cross_m in [("mimo", "bai"), ("bai", "mimo")]:
        print(f"\n{'='*70}")
        print(f"评估员: {eval_m} | persona 生成: {cross_m}")
        print(f"{'='*70}")
        try:
            result = await run_evaluator(
                eval_model=eval_m,
                cross_model=cross_m,
                persona_service=persona_service,
                industry=args.industry,
                rounds=args.rounds,
                prompt_boost=args.boost,
            )
            results[eval_m] = result
        except Exception as e:
            import traceback
            print(f"评估员 {eval_m} 失败: {type(e).__name__}: {e}")
            traceback.print_exc()
            results[eval_m] = {"error": f"{type(e).__name__}: {e}"}

    # 汇总
    print("\n" + "=" * 70)
    print("评估汇总")
    print("=" * 70)
    for eval_m, result in results.items():
        if "score" in result and "error" not in result.get("score", {}):
            s = result["score"]
            print(f"\n评估员 {eval_m}:")
            print(f"  naturalness:    {s.get('naturalness', '?')}")
            print(f"  emotion:        {s.get('emotion', '?')}")
            print(f"  consistency:    {s.get('consistency', '?')}")
            print(f"  personality:    {s.get('personality', '?')}")
            print(f"  appropriateness:{s.get('appropriateness', '?')}")
            print(f"  total:          {s.get('total', '?')}")
            print(f"  leaks: {s.get('leaks', [])}")
            print(f"  summary: {s.get('summary', '')}")
        else:
            print(f"\n评估员 {eval_m}: 失败 - {result.get('error', '未知')}")

    # 保存到历史
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(),
        "industry": args.industry,
        "rounds": args.rounds,
        "boost": args.boost,
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "dialogue"} for k, v in results.items()},
    }
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 保存完整对话到单独文件
    dialogue_path = output_path.parent / f"dialogue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(dialogue_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n历史记录: {output_path}")
    print(f"完整对话: {dialogue_path}")


if __name__ == "__main__":
    asyncio.run(main())
