# api_server_stream.py
# -*- coding: utf-8 -*-

from typing import Any, Dict

import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prompts import PLAN_SYSTEM_PROMPT, PLAN_FEWSHOT, ANSWER_SYSTEM_PROMPT
from llm_client import client, PLAN_MODEL, ANSWER_MODEL
from movie_qa import execute_plan  


app = FastAPI(
    title="Movie KG QA Streaming API",
    description="图增强电影问答",
    version="0.1.0",
)

# CORS：方便前端本地开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QuestionRequest(BaseModel):
    question: str


def build_plan_messages(question: str):
    """用 prompts.py 里的 PLAN_SYSTEM_PROMPT + PLAN_FEWSHOT 构造消息。"""
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


def build_answer_messages(question: str, exec_result: Dict[str, Any]):
    """用 prompts.py 里的 ANSWER_SYSTEM_PROMPT 构造第二步的消息。"""
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


@app.post("/api/qa_stream")
def qa_stream(req: QuestionRequest):
    """
    流式接口：
    - 先返回一条 type = "meta" 的 JSON 行，包含 plan 和 graph_result
    - 再流式返回 qwen3-8b 的 reasoning_content 和 content
    - 每一行都是一个 JSON 对象，末尾有 '\n'
    """

    question = req.question.strip()

    def event_generator():
        # ========== Step 1：生成查询计划（非流式） ==========
        try:
            plan_resp = client.chat.completions.create(
                model=PLAN_MODEL,
                messages=build_plan_messages(question),
                temperature=0.0,
            )
            plan_raw = plan_resp.choices[0].message.content
            plan = json.loads(plan_raw)
        except Exception as e:
            # plan 错了也尽量给前端返回错误信息
            err_msg = f"解析查询计划失败: {e}"
            fallback = {
                "task": "movie_basic_info",
                "params": {"title": question},
            }
            meta = {
                "type": "meta",
                "error": err_msg,
                "plan": fallback,
                "graph_result": None,
            }
            yield json.dumps(meta, ensure_ascii=False) + "\n"
            # 直接结束
            yield json.dumps({"type": "done"}) + "\n"
            return

        # ========== Step 2：在本地图谱上执行计划 ==========
        try:
            graph_result = execute_plan(plan)
        except Exception as e:
            graph_result = None
            plan_error = f"执行图查询失败: {e}"

            meta = {
                "type": "meta",
                "error": plan_error,
                "plan": plan,
                "graph_result": None,
            }
            yield json.dumps(meta, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
            return

        # 把 Plan 和 Graph Result 发给前端
        meta = {
            "type": "meta",
            "plan": plan,
            "graph_result": graph_result,
        }
        yield json.dumps(meta, ensure_ascii=False) + "\n"

        # ========== Step 3：qwen3-8b 深度思考 + 流式输出 ==========
        messages = build_answer_messages(question, graph_result)

        try:
            completion = client.chat.completions.create(
                model=ANSWER_MODEL,
                messages=messages,
                extra_body={"enable_thinking": True},
                stream=True,
            )

            for chunk in completion:
                delta = chunk.choices[0].delta

                # 思考过程
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    pkt = {
                        "type": "reasoning",
                        "text": reasoning,
                    }
                    yield json.dumps(pkt, ensure_ascii=False) + "\n"

                # 最终回答内容
                content = getattr(delta, "content", None)
                if content:
                    pkt = {
                        "type": "answer",
                        "text": content,
                    }
                    yield json.dumps(pkt, ensure_ascii=False) + "\n"

            # 结束标记
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

        except Exception as e:
            err_pkt = {
                "type": "error",
                "message": f"回答阶段出错: {e}",
            }
            yield json.dumps(err_pkt, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}
