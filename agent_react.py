# agent_react.py
"""
ReAct 风格的电影问答 Agent：
- 使用 qwen3-max 做 Agent（Thought + Action）
- 使用 qwen3-8b 做最终回答（深度思考模式）
- 工具调用全部落在 kg_api.py 中定义的函数上
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple
import json
import re
import os

from openai import OpenAI

import kg_api  # 复用你现有的图谱查询接口


# ========= 基础配置 =========

# 使用阿里云百炼兼容 OpenAI 接口
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),  # 请在环境变量中配置
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

AGENT_MODEL = "qwen3-max"   # Agent 模型（负责 ReAct：Thought + Action）
ANSWER_MODEL = "qwen3-8b"   # 回答模型（负责最终回答，支持 enable_thinking）
MAX_STEPS = 5               # Agent 最多迭代步数


# ========= 工具描述（写给大模型看的） =========

TOOL_DESCRIPTIONS = """
你可以使用以下工具（所有工具都基于电影知识图谱）：

1. movie_basic_info
   - 功能：查询一部电影的基本信息（导演、演员、类型、年份、评分等）。
   - 参数(JSON)：
       {
         "title": "电影名（字符串）"
       }

2. movies_by_director
   - 功能：查询某个导演执导的电影，可选年份区间和数量限制。
   - 参数(JSON)：
       {
         "name": "导演姓名（字符串）",
         "year_min": 2000,     # 可选，整数
         "year_max": 2015,     # 可选，整数
         "limit": 10           # 可选，整数
       }

3. movies_by_actor
   - 功能：查询某个演员参演的电影，可选年份区间和数量限制。
   - 参数(JSON)：
       {
         "name": "演员姓名（字符串）",
         "year_min": 2000,     # 可选，整数
         "year_max": 2015,     # 可选，整数
         "limit": 10           # 可选，整数
       }

4. movies_by_genre
   - 功能：按类型查询电影，可选评分下限和数量限制。
   - 参数(JSON)：
       {
         "genre": "类型名称（字符串，如 'Action'）",
         "rating_min": 8.0,    # 可选，浮点数
         "limit": 10           # 可选，整数
       }

5. similar_movies
   - 功能：查询与某部电影相似的电影（基于共同导演/演员/类型等图结构）。
   - 参数(JSON)：
       {
         "title": "电影名（字符串）",
         "limit": 10           # 可选，整数
       }

6. other_movies_by_director_of_movie
   - 功能：先找到一部电影的导演，再列出该导演的其他电影。
   - 参数(JSON)：
       {
         "title": "电影名（字符串）"
       }

7. co_actors
   - 功能：查询某个演员的“合作演员”，按合作次数排序。
   - 参数(JSON)：
       {
         "name": "演员姓名（字符串）",
         "limit": 10           # 可选，整数
       }

当你需要调用工具时，请严格使用下面的格式输出（不要有多余文字）：

Thought: 先说明你在想什么，为什么要调用这个工具。
Action: <工具名或 "finish">
Action Input: <JSON格式的参数对象，例如 { "title": "Inception" }>

如果你认为已经有足够信息回答用户问题，请使用：
Action: finish
Action Input: {}
并在 Thought 中简要说明你打算如何组织最后的回答。
"""

REACT_SYSTEM_PROMPT = f"""
你是一个面向电影领域的智能体（Agent），可以通过调用一组工具在电影知识图谱上进行查询和推理。

你的目标：
- 理解用户的自然语言问题；
- 通过多步工具调用（可以先查导演，再查导演的电影，再筛选等），逐步收集信息；
- 当你认为信息足够时，使用 Action: finish 结束工具调用阶段，之后会由另一个模型来负责生成最终的自然语言回答。

可用工具及参数说明如下：
{TOOL_DESCRIPTIONS}

对每一步，你必须严格按以下格式输出（英文标签 + 冒号）：

Thought: <你的思考过程，用中文，解释你打算做什么>
Action: <上面列出的工具名之一，或者 "finish">
Action Input: <JSON 格式的参数对象，例如 {{ "title": "Inception" }}>

注意：
- 一次回复只能包含一组 Thought / Action / Action Input，不要输出多组。
- Action Input 必须是合法 JSON 对象，键需要用双引号。
- 如果你决定结束并直接回答用户问题，请使用 Action: finish，Action Input 可以是 {{}}。
"""


# ========= 工具调用 ==========

def run_tool(action: str, params: Dict[str, Any]) -> Any:
    """
    根据 action 名字调用对应的 kg_api 函数，返回原始结果。
    这里假设 kg_api 中已经实现了这些函数。
    """
    if action == "movie_basic_info":
        return kg_api.get_movie_basic_info(params.get("title"))

    if action == "movies_by_director":
        return kg_api.get_movies_by_director(
            name=params.get("name"),
            year_min=params.get("year_min"),
            year_max=params.get("year_max"),
            limit=params.get("limit"),
        )

    if action == "movies_by_actor":
        return kg_api.get_movies_by_actor(
            name=params.get("name"),
            year_min=params.get("year_min"),
            year_max=params.get("year_max"),
            limit=params.get("limit"),
        )

    if action == "movies_by_genre":
        return kg_api.get_movies_by_genre(
            genre_name=params.get("genre"),
            rating_min=params.get("rating_min"),
            limit=params.get("limit"),
        )

    if action == "similar_movies":
        return kg_api.get_similar_movies_by_neighbors(
            title=params.get("title"),
            top_k=params.get("limit"),
        )

    if action == "other_movies_by_director_of_movie":
        return kg_api.get_other_movies_by_director_of_movie(
            params.get("title")
        )

    if action == "co_actors":
        return kg_api.get_co_actors(
            name=params.get("name"),
            top_k=params.get("limit"),
        )

    # 未知工具兜底
    return {"error": f"Unknown action: {action}"}


# ========= 历史记录格式化，用于 prompt =========

def format_history_for_prompt(history: List[Dict[str, Any]]) -> str:
    """
    把历史记录拼成一段文本，喂给 Agent 模型作为上下文。
    每步包括：Thought / Action / Action Input / Observation。
    """
    if not history:
        return "（当前还没有任何工具调用记录。）"

    lines: List[str] = []
    for i, step in enumerate(history, start=1):
        lines.append(f"Step {i}:")
        lines.append(f"Thought: {step['thought']}")
        lines.append(f"Action: {step['action']}")
        lines.append(
            f"Action Input: {json.dumps(step['action_input'], ensure_ascii=False)}"
        )
        lines.append(f"Observation: {step['observation_summary']}")
        lines.append("")
    return "\n".join(lines)


def build_react_messages(question: str, history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    构造 ReAct 调用的 messages 列表，传给 qwen3-max。
    """
    history_text = format_history_for_prompt(history)
    user_content = f"""用户问题：
{question}

以下是之前的工具调用历史（Thought / Action / Action Input / Observation）：
{history_text}

请基于上述历史和可用工具，决定下一步要做什么，按指定格式输出下一步的 Thought / Action / Action Input。
"""
    return [
        {"role": "system", "content": REACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ========= 解析 Agent 输出 =========

STEP_PATTERN = re.compile(
    r"Thought:\s*(?P<thought>.+?)\s*Action:\s*(?P<action>[\w_]+)\s*Action Input:\s*(?P<input>\{.*\})",
    re.DOTALL,
)


def parse_react_output(text: str) -> Tuple[str, str, Dict[str, Any]]:
    """
    从模型的输出中提取 Thought / Action / Action Input。
    如果解析失败，就把整段当成 thought，并返回 action=finish。
    """
    m = STEP_PATTERN.search(text)
    if not m:
        # 简单兜底：全部视为思考，直接结束
        return text.strip(), "finish", {}

    thought = m.group("thought").strip()
    action = m.group("action").strip()
    input_str = m.group("input").strip()

    try:
        params = json.loads(input_str)
    except Exception:
        params = {}

    return thought, action, params


# ========= Observation 摘要（给下一轮用） =========

def summarise_observation(action: str, obs: Any, max_items: int = 5) -> str:
    """
    把工具返回的原始结果压缩成一小段文字，给下一步 Agent 使用。
    避免把巨大的 JSON 全贴回 prompt。
    """
    if obs is None:
        return "工具返回 None。"
    if isinstance(obs, dict) and "error" in obs:
        return f"工具执行出错: {obs['error']}"

    try:
        # 根据你 kg_api 的返回结构做针对性摘要
        if action in ("movies_by_director", "movies_by_actor", "movies_by_genre", "similar_movies"):
            items = obs or []
            n = len(items)
            head = items[:max_items]
            titles = [
                f"{(m.get('title') or m.get('movie') or '')}({m.get('year')})"
                for m in head
            ]
            titles = [t for t in titles if t != "()"]
            return f"共找到 {n} 部电影，前 {len(titles)} 部示例：{'； '.join(titles)}"

        if action == "movie_basic_info":
            if not obs:
                return "没有找到该电影的信息。"
            title = obs.get("title") or ""
            year = obs.get("year")
            directors = obs.get("directors") or obs.get("director") or ""
            return f"找到电影《{title}》({year})，导演：{directors}"

        if action == "co_actors":
            items = obs or []
            n = len(items)
            head = items[:max_items]
            names = [
                f"{c.get('name')}（合作 {c.get('count')} 次）"
                for c in head
            ]
            return f"共找到 {n} 位合作演员，前 {len(names)} 位示例：{'； '.join(names)}"
    except Exception:
        pass

    # 默认情况，直接截断字符串形式
    s = str(obs)
    if len(s) > 500:
        s = s[:500] + " ...[truncated]"
    return s


# ========= 最终回答：基于 history 总结 =========

def build_answer_messages_from_history(question: str, history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    把 ReAct 历史记录打包成最终回答模型的输入。
    """
    lines: List[str] = [
        f"用户问题：{question}",
        "",
        "下面是你（作为 Agent）刚刚的推理与工具调用过程（Thought / Action / Observation）：",
        "",
    ]
    for step in history:
        lines.append(f"Step {step['step']}:")
        lines.append(f"Thought: {step['thought']}")
        lines.append(f"Action: {step['action']}")
        lines.append(
            f"Action Input: {json.dumps(step['action_input'], ensure_ascii=False)}"
        )
        lines.append(f"Observation: {step['observation_summary']}")
        lines.append("")
    history_text = "\n".join(lines)

    system_prompt = """
你现在的角色是“回答总结器”。

我会给你：
- 用户的原始问题
- 之前一个 ReAct Agent 的推理与工具调用过程（包括 Thought / Action / Observation）

你的任务：
- 只基于这些 Observation 中的信息，用中文回答用户的问题。
- 不要编造 Observation 里没有的电影或事实。
- 如果 Observation 基本为空或查不到信息，请如实说明“在当前知识图谱/工具中没有查到相关结果”，可以给一点泛化建议，但不要虚构具体片名。

可以使用 Markdown 做简单排版（如小标题、列表、加粗等），但不需要输出很长的推理过程。
"""

    user_content = f"{history_text}\n\n请基于上述过程，给出对用户问题的最终回答。"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def generate_final_answer(question: str, history: List[Dict[str, Any]]) -> str:
    """
    调用 Qwen3-8B（启用 enable_thinking）生成最终回答。
    这里用非流式返回一个完整字符串，如果要流式可以在 FastAPI 那边改成逐块写出。
    """
    messages = build_answer_messages_from_history(question, history)
    completion = client.chat.completions.create(
        model=ANSWER_MODEL,
        messages=messages,
        extra_body={"enable_thinking": True},
        stream=False,
    )
    return completion.choices[0].message.content


# ========= ReAct Agent 主循环 =========

def run_react_agent(question: str, max_steps: int = MAX_STEPS) -> Dict[str, Any]:
    """
    ReAct Agent 的主入口：
    - 输入：自然语言问题 question
    - 输出：包含历史 steps 和 final_answer 的字典，可直接给前端或 FastAPI 使用。
    """
    history: List[Dict[str, Any]] = []

    for step in range(1, max_steps + 1):
        # 1）构造本轮的 prompt
        messages = build_react_messages(question, history)

        # 2）调用 Agent 模型（qwen3-max）
        resp = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=messages,
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""

        # 3）解析模型输出
        thought, action, params = parse_react_output(content)

        step_record: Dict[str, Any] = {
            "step": step,
            "thought": thought,
            "action": action,
            "action_input": params,
            "observation_summary": "",
            "raw_observation": None,
            "raw_agent_output": content,
        }

        # 4）结束条件：finish -> 不再调用工具
        if action == "finish":
            history.append(step_record)
            break

        # 5）调用工具并生成 Observation 摘要
        obs = run_tool(action, params)
        step_record["raw_observation"] = obs
        step_record["observation_summary"] = summarise_observation(action, obs)

        history.append(step_record)

    # 6）用回答模型总结最终答案
    final_answer = generate_final_answer(question, history)

    return {
        "question": question,
        "history": history,
        "final_answer": final_answer,
    }


# ========= 简单命令行测试 =========

if __name__ == "__main__":
    print("ReAct 电影 Agent 测试。输入问题，按回车开始推理，输入空行退出。")
    while True:
        q = input("\n问题> ").strip()
        if not q:
            break
        result = run_react_agent(q)
        print("\n=== ReAct 步骤 ===")
        for step in result["history"]:
            print(f"\nStep {step['step']}")
            print("Thought:", step["thought"])
            print("Action:", step["action"])
            print("Action Input:", step["action_input"])
            print("Observation:", step["observation_summary"])
        print("\n=== 最终回答 ===")
        print(result["final_answer"])
