# movie_qa.py
# -*- coding: utf-8 -*-

"""
图增强的电影问答主逻辑：

流程：
1. 用户输入自然语言问题
2. 调用 generate_plan(question)：让 qwen3-max 生成“查询计划 JSON”（流式打印）
3. execute_plan(plan)：在本地知识图谱上执行查询
4. generate_answer(question, exec_result)：用 qwen3-8b 深度思考模式，根据结果回答（流式打印）
"""

import json
from typing import Dict, Any

from llm_client import stream_chat, PLAN_MODEL, ANSWER_MODEL
from prompts import PLAN_SYSTEM_PROMPT, PLAN_FEWSHOT, ANSWER_SYSTEM_PROMPT
import kg_api


# ----------------------------------------------------------------------
# 1. 生成查询计划（第一次调用：qwen3-max）
# ----------------------------------------------------------------------

def build_plan_messages(question: str):
    """
    构造让大模型生成“查询计划 JSON”的对话消息。
    使用 prompts.py 中的 PLAN_SYSTEM_PROMPT 和 PLAN_FEWSHOT。
    """
    messages = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
    ]

    for ex in PLAN_FEWSHOT:
        messages.append({"role": "user", "content": ex["user"]})
        messages.append({
            "role": "assistant",
            "content": json.dumps(ex["assistant"], ensure_ascii=False),
        })

    messages.append({"role": "user", "content": question})
    return messages


def generate_plan(question: str) -> Dict[str, Any]:
    """
    调用 qwen3-max，将自然语言问题转换为查询计划 JSON（dict）。
    带流式调试输出。
    """
    messages = build_plan_messages(question)
    raw = stream_chat(
        model=PLAN_MODEL,
        messages=messages,
        enable_thinking=False,
        debug_name="生成查询计划",
    )

    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        # 调试时如果解析失败，打印一下原始内容
        print("解析查询计划 JSON 失败，原始模型输出：", raw)
        # 简单兜底：把用户问题当成 title
        plan = {
            "task": "movie_basic_info",
            "params": {"title": question.strip()},
        }
    return plan


# ----------------------------------------------------------------------
# 2. 执行查询计划：调用 kg_api
# ----------------------------------------------------------------------

def execute_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据查询计划调用 kg_api，并把结果包装成结构化 dict。

    返回统一结构：
    {
      "task": "...",
      "params": {...},
      "result": ...   # 直接是 kg_api 对应函数的返回值
    }
    """
    task = plan.get("task")
    params = plan.get("params") or {}

    if task == "movie_basic_info":
        title = params.get("title")
        data = kg_api.get_movie_basic_info(title)
        return {"task": task, "params": params, "result": data}

    elif task == "movies_by_director":
        name = params.get("name")
        year_min = params.get("year_min")
        year_max = params.get("year_max")
        limit = params.get("limit")
        data = kg_api.get_movies_by_director(
            name,
            year_min=year_min,
            year_max=year_max,
            limit=limit,
        )
        return {"task": task, "params": params, "result": data}

    elif task == "movies_by_actor":
        name = params.get("name")
        year_min = params.get("year_min")
        year_max = params.get("year_max")
        limit = params.get("limit")
        data = kg_api.get_movies_by_actor(
            name,
            year_min=year_min,
            year_max=year_max,
            limit=limit,
        )
        return {"task": task, "params": params, "result": data}

    elif task == "movies_by_genre":
        genre = params.get("genre")
        rating_min = params.get("rating_min")
        limit = params.get("limit")
        data = kg_api.get_movies_by_genre(
            genre_name=genre,
            rating_min=rating_min,
            sort_by_rating=True,
            limit=limit,
        )
        return {"task": task, "params": params, "result": data}

    elif task == "similar_movies":
        title = params.get("title")
        limit = params.get("limit")
        raw = kg_api.get_similar_movies_by_neighbors(
            title,
            top_k=(limit or 10),
        )
        return {"task": task, "params": params, "result": raw}

    elif task == "other_movies_by_director_of_movie":
        title = params.get("title")
        data = kg_api.get_other_movies_by_director_of_movie(title)
        return {"task": task, "params": params, "result": data}

    elif task == "co_actors":
        name = params.get("name")
        limit = params.get("limit")
        data = kg_api.get_co_actors(name, top_k=limit)
        return {"task": task, "params": params, "result": data}

    else:
        # 未知 task 的兜底
        return {
            "task": task,
            "params": params,
            "result": None,
            "error": f"Unknown task: {task}",
        }


# ----------------------------------------------------------------------
# 3. 根据查询结果生成自然语言回答（第二次调用：qwen3-8b + 思考模式）
# ----------------------------------------------------------------------

def build_answer_messages(question: str, exec_result: Dict[str, Any]):
    """
    构造让大模型“根据图查询结果来回答问题”的消息。
    使用 prompts.py 中的 ANSWER_SYSTEM_PROMPT。
    """
    system_prompt = ANSWER_SYSTEM_PROMPT

    user_content = f"""用户问题：
{question}

图查询结果（JSON）：
{json.dumps(exec_result, ensure_ascii=False, indent=2)}
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def generate_answer(question: str, exec_result: Dict[str, Any]) -> str:
    """
    调用 qwen3-8b 深度思考模式，把图查询结果转成自然语言回答。
    带思考过程和流式输出。
    """
    messages = build_answer_messages(question, exec_result)
    answer = stream_chat(
        model=ANSWER_MODEL,
        messages=messages,
        enable_thinking=True,
        debug_name="回答问题",
    )
    return answer


# ----------------------------------------------------------------------
# 4. 对外主接口：answer_question
# ----------------------------------------------------------------------

def answer_question(question: str) -> str:
    """
    对外的主接口：给一个自然语言问题 → 返回一个图增强的回答。
    """
    # 1. 生成查询计划
    plan = generate_plan(question)
    print("计划解析结果:", json.dumps(plan, ensure_ascii=False, indent=2))

    # 2. 执行计划
    exec_result = execute_plan(plan)
    print("图查询结果:", json.dumps(exec_result, ensure_ascii=False, indent=2))

    # 3. 生成回答（深度思考）
    answer = generate_answer(question, exec_result)
    return answer


if __name__ == "__main__":
    # 简单命令行交互 demo
    print("图增强电影问答已启动，输入 q 退出。")
    while True:
        try:
            q = input("\n你可以问我任何和电影相关的问题：\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not q or q.lower() == "q":
            break

        resp = answer_question(q)
        print("\n最终回答：", resp)
