// app.js

const API_BASE = "http://localhost:8000"; // 后端地址

const form = document.getElementById("qa-form");
const questionInput = document.getElementById("question-input");
const submitBtn = document.getElementById("submit-btn");
const loadingIndicator = document.getElementById("loading-indicator");
const errorBox = document.getElementById("error-box");
const resultSection = document.getElementById("result-section");

const questionTextEl = document.getElementById("question-text");

const planTaskEl = document.getElementById("plan-task");
const planParamsEl = document.getElementById("plan-params");
const planDetailsEl = document.getElementById("plan-details");
const planJsonEl = document.getElementById("plan-json");

const graphDetailsEl = document.getElementById("graph-details");
const graphJsonEl = document.getElementById("graph-json");

const reasoningViewEl = document.getElementById("reasoning-view");
const answerViewEl = document.getElementById("answer-view");

// 累积回答的 Markdown 文本，用于流式渲染
let answerMarkdownBuffer = "";

function resetUI() {
  errorBox.hidden = true;
  errorBox.textContent = "";
  resultSection.hidden = true;

  planTaskEl.textContent = "（未生成）";
  planParamsEl.textContent = "（未生成）";
  planDetailsEl.hidden = true;
  planJsonEl.textContent = "";

  graphDetailsEl.hidden = true;
  graphJsonEl.textContent = "";

  reasoningViewEl.textContent = "";
  answerViewEl.innerHTML = "";
  answerMarkdownBuffer = "";
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  loadingIndicator.hidden = !isLoading;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  resetUI();
  resultSection.hidden = false;
  questionTextEl.textContent = question;
  setLoading(true);

  try {
    await startStreamingQA(question);
  } catch (err) {
    console.error(err);
    errorBox.textContent = "请求出错：" + (err.message || String(err));
    errorBox.hidden = false;
  } finally {
    setLoading(false);
  }
});

async function startStreamingQA(question) {
  const resp = await fetch(`${API_BASE}/api/qa_stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question }),
  });

  if (!resp.ok || !resp.body) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // 按行切分（每行是一个 JSON）
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      let msg;
      try {
        msg = JSON.parse(line);
      } catch (e) {
        console.warn("JSON parse error:", e, "on line:", line);
        continue;
      }
      handleStreamMessage(msg);
    }
  }

  // 处理缓冲区里最后一行（如果刚好是完整 JSON）
  if (buffer.trim()) {
    try {
      const msg = JSON.parse(buffer);
      handleStreamMessage(msg);
    } catch (e) {
      console.warn("JSON parse error (final buffer):", e, buffer);
    }
  }
}

function handleStreamMessage(msg) {
  const type = msg.type;

  if (type === "meta") {
    // 展示 Plan & Graph Result
    const { plan, graph_result, error } = msg;

    if (error) {
      errorBox.textContent = "后端错误：" + error;
      errorBox.hidden = false;
    }

    if (plan) {
      planTaskEl.textContent = plan.task || "（无）";
      planParamsEl.textContent = plan.params
        ? JSON.stringify(plan.params)
        : "（空）";
      planJsonEl.textContent = JSON.stringify(plan, null, 2);
      planDetailsEl.hidden = false;
    }

    if (graph_result) {
      graphJsonEl.textContent = JSON.stringify(graph_result, null, 2);
      graphDetailsEl.hidden = false;
    }

    return;
  }

  if (type === "reasoning") {
    const text = msg.text || "";
    reasoningViewEl.textContent += text;
    reasoningViewEl.scrollTop = reasoningViewEl.scrollHeight;
    return;
  }

  if (type === "answer") {
    const text = msg.text || "";
    // 累积 Markdown 文本
    answerMarkdownBuffer += text;

    try {
      // 使用 marked 渲染 Markdown
      const rawHtml = marked.parse(answerMarkdownBuffer);
      // 为安全起见，用 DOMPurify 过滤（DOMPurify 在 index.html 里通过 CDN 引入）
      const safeHtml = DOMPurify.sanitize(rawHtml);
      answerViewEl.innerHTML = safeHtml;
      answerViewEl.scrollTop = answerViewEl.scrollHeight;
    } catch (e) {
      console.warn("Markdown 渲染出错：", e);
      // 渲染失败时至少保底用纯文本
      answerViewEl.textContent = answerMarkdownBuffer;
    }
    return;
  }

  if (type === "error") {
    const text = msg.message || "未知错误";
    errorBox.textContent = text;
    errorBox.hidden = false;
    return;
  }

  if (type === "done") {
    // 可选：在这里加一点“已完成”的提示
    return;
  }

  console.warn("未知消息类型:", msg);
}
