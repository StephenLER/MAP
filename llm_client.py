# llm_client.py
# -*- coding: utf-8 -*-

import os
from typing import List, Dict

from openai import OpenAI

# 建议通过环境变量设置 key：
#   Linux / macOS: export DASHSCOPE_API_KEY="你的真实key"
#   Windows CMD:   set DASHSCOPE_API_KEY=你的真实key
API_KEY = "sk-4442f7376d3d4740848837c522ab62a9"

if not API_KEY:
    raise RuntimeError("请先在环境变量 DASHSCOPE_API_KEY 中配置你的 API Key")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 计划阶段用的模型
PLAN_MODEL = "qwen3-max"
# 回答阶段用的深度思考模型
ANSWER_MODEL = "qwen3-8b"


def stream_chat(
    model: str,
    messages: List[Dict[str, str]],
    enable_thinking: bool = False,
    debug_name: str = "",
) -> str:
    """
    统一的流式调用封装：
    - 支持普通模式（如 qwen3-max）
    - 支持深度思考模式（enable_thinking=True, 如 qwen3-8b）
    - 会把中间过程和最终回复流式打印出来
    - 返回最终 content 的完整字符串（用于后续 json 解析或直接展示）
    """
    extra_args = {}
    if enable_thinking:
        extra_args["extra_body"] = {"enable_thinking": True}

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        **extra_args,
    )

    full_content = ""
    is_answering = False

    if enable_thinking:
        print(f"\n{'=' * 20}{debug_name} 思考过程{'=' * 20}")
    else:
        print(f"\n{'=' * 20}{debug_name} 流式输出{'=' * 20}")

    for chunk in completion:
        delta = chunk.choices[0].delta

        # 深度思考模式的“思考过程”
        if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
            if not is_answering:
                print(delta.reasoning_content, end="", flush=True)

        # 最终回复内容
        if hasattr(delta, "content") and delta.content:
            if enable_thinking and not is_answering:
                print("\n" + "=" * 20 + f"{debug_name} 完整回复" + "=" * 20)
                is_answering = True
            print(delta.content, end="", flush=True)
            full_content += delta.content

    print("\n" + "=" * 20 + f"{debug_name} 结束" + "=" * 20 + "\n")
    return full_content
