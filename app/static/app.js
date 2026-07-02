function getValue(id) {
    return document.getElementById(id).value;
}

function setText(id, text) {
    document.getElementById(id).textContent = text;
}

function setHtml(id, html) {
    document.getElementById(id).innerHTML = html;
}

function setStatus(text) {
    setText("statusText", "状态：" + text);
}

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getEmbeddingDevice() {
    const value = getValue("embeddingDeviceInput");

    if (!value) {
        return null;
    }

    return value;
}

function getGenerateValue() {
    return getValue("generateInput") === "true";
}

function buildAskPayload() {
    return {
        question: getValue("questionInput"),
        top_k: Number(getValue("topKInput")),
        min_score: null,
        section_filter: null,
        year_from: null,
        year_to: null,
        max_chars_per_evidence: Number(getValue("maxCharsInput")),
        language: "zh",
        generate: getGenerateValue(),
        embedding_model: "C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
        embedding_device: getEmbeddingDevice(),
        ollama_model: getValue("ollamaModelInput"),
        ollama_base_url: "http://localhost:11434",
        temperature: 0.2,
        num_ctx: Number(getValue("numCtxInput")),
        num_predict: Number(getValue("numPredictInput")),
        timeout: 900,
        think_mode: getValue("thinkModeInput")
    };
}

function renderSources(sources) {
    if (!sources || sources.length === 0) {
        setHtml("sourcesBox", "暂无来源。");
        return;
    }

    const html = sources.map((source) => {
        return `
            <div class="source-card">
                <h3>[${escapeHtml(source.source_id)}] ${escapeHtml(source.paper_title)}</h3>
                <div class="source-meta">
                    <div><strong>score:</strong> ${Number(source.score).toFixed(4)}</div>
                    <div><strong>year:</strong> ${escapeHtml(source.year)}</div>
                    <div><strong>journal:</strong> ${escapeHtml(source.journal)}</div>
                    <div><strong>doi:</strong> ${escapeHtml(source.doi)}</div>
                    <div><strong>section:</strong> ${escapeHtml(source.section_title)}</div>
                    <div><strong>pages:</strong> ${escapeHtml(source.page_start)} - ${escapeHtml(source.page_end)}</div>
                    <div><strong>chunk_id:</strong> ${escapeHtml(source.chunk_id)}</div>
                </div>
            </div>
        `;
    }).join("");

    setHtml("sourcesBox", html);
}

async function askQuestion() {
    const question = getValue("questionInput").trim();

    if (!question) {
        alert("请输入问题。");
        return;
    }

    const askButton = document.getElementById("askButton");
    askButton.disabled = true;

    setStatus("正在请求 RAG，请稍等...");
    setText("answerBox", "生成中...");
    setHtml("sourcesBox", "等待来源...");

    try {
        const payload = buildAskPayload();

        const response = await fetch("/ask", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "请求失败");
        }

        setText("answerBox", data.answer || "模型返回空回答。");
        renderSources(data.sources);
        setStatus("完成。");
    } catch (error) {
        setText("answerBox", "请求失败：" + error.message);
        setHtml("sourcesBox", "暂无来源。");
        setStatus("失败。");
    } finally {
        askButton.disabled = false;
    }
}

async function loadStats() {
    setStatus("正在加载系统状态...");

    try {
        const response = await fetch("/stats");
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "加载失败");
        }

        setText("statsBox", JSON.stringify(data, null, 2));
        setStatus("系统状态加载完成。");
    } catch (error) {
        setText("statsBox", "加载失败：" + error.message);
        setStatus("系统状态加载失败。");
    }
}

async function warmupRetriever() {
    setStatus("正在预热检索器，首次加载 BGE-M3 可能较慢...");

    try {
        const payload = {
            embedding_model: "C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
            embedding_device: getEmbeddingDevice(),
            ollama_model: getValue("ollamaModelInput"),
            ollama_base_url: "http://localhost:11434"
        };

        const response = await fetch("/rag/warmup", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "预热失败");
        }

        setText("statsBox", JSON.stringify(data, null, 2));
        setStatus("检索器预热完成。");
    } catch (error) {
        setText("statsBox", "预热失败：" + error.message);
        setStatus("预热失败。");
    }
}

function clearResults() {
    setText("answerBox", "暂无回答。");
    setHtml("sourcesBox", "暂无来源。");
    setText("statsBox", "尚未加载。");
    setStatus("等待操作");
}

document.getElementById("askButton").addEventListener("click", askQuestion);
document.getElementById("statsButton").addEventListener("click", loadStats);
document.getElementById("warmupButton").addEventListener("click", warmupRetriever);
document.getElementById("clearButton").addEventListener("click", clearResults);

// ============================================================
// Agent 任务面板
// ============================================================

let agentThreadId = null;
let agentSource = null;

function setAgentStatus(text) {
    setText("agentStatusText", "状态：" + text);
}

function showProgress() {
    document.getElementById("agentProgressBar").style.display = "block";
}

function updateProgress(stage) {
    const stages = document.querySelectorAll("#agentProgressStages .stage-dot");
    stages.forEach(function(dot) {
        const ds = dot.getAttribute("data-stage");
        if (ds === stage) {
            dot.classList.add("active");
        } else if (dot.classList.contains("active") && !dot.classList.contains("completed")) {
            dot.classList.remove("active");
            dot.classList.add("completed");
        }
    });
}

function showAgentButtons(type) {
    document.getElementById("agentRunButton").style.display = type === "run" ? "inline-block" : "none";
    document.getElementById("agentApproveButton").style.display = type === "approve" ? "inline-block" : "none";
    document.getElementById("agentRejectButton").style.display = type === "approve" ? "inline-block" : "none";
}

function startAgent() {
    const intent = getValue("agentIntentInput");
    const question = getValue("agentQuestionInput");
    if (!question) {
        setAgentStatus("请输入具体问题");
        return;
    }

    document.getElementById("agentAnswerBox").style.display = "none";
    document.getElementById("agentSourcesBox").style.display = "none";
    showProgress();
    setAgentStatus("正在规划任务...");
    showAgentButtons("none");

    // 重置进度
    document.querySelectorAll("#agentProgressStages .stage-dot").forEach(function(d) {
        d.classList.remove("active", "completed", "error");
    });

    const body = JSON.stringify({
        user_intent: intent,
        user_question: question,
    });

    agentSource = new EventSource("/agent/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
    });

    agentSource.addEventListener("thread", function(e) {
        const data = JSON.parse(e.data);
        agentThreadId = data.thread_id;
    });

    agentSource.addEventListener("node_complete", function(e) {
        const data = JSON.parse(e.data);
        const stage = data.stage || data.node;
        updateProgress(stage);
        setAgentStatus("执行中：" + stage);
    });

    agentSource.addEventListener("interrupt", function(e) {
        const data = JSON.parse(e.data);
        setAgentStatus("等待确认：已规划 " + (data.plan ? data.plan.length : 0) + " 个步骤");
        showAgentButtons("approve");
        agentSource.close();
    });

    agentSource.addEventListener("answer", function(e) {
        const data = JSON.parse(e.data);
        document.getElementById("agentAnswerBox").style.display = "block";
        document.getElementById("agentAnswerBox").innerHTML = escapeHtml(data.answer || "");

        if (data.sources && data.sources.length) {
            renderAgentSources(data.sources);
        }
        setAgentStatus("回答完成");
    });

    agentSource.addEventListener("error", function(e) {
        if (e.data) {
            const data = JSON.parse(e.data);
            setAgentStatus("错误：" + data.error);
        }
    });

    agentSource.addEventListener("done", function() {
        setAgentStatus("流程已完成");
        agentSource.close();
        agentSource = null;
    });

    // Fallback for POST via fetch + SSE
    if (!("withCredentials" in agentSource)) {
        agentSource.close();
        fetchAgentViaFetch(intent, question);
    }
}

function fetchAgentViaFetch(intent, question) {
    fetch("/agent/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_intent: intent, user_question: question }),
    }).then(function(response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        function read() {
            reader.read().then(function(result) {
                if (result.done) {
                    setAgentStatus("流程已完成");
                    return;
                }
                const text = decoder.decode(result.value, { stream: true });
                // Parse SSE lines
                text.split("\n").forEach(function(line) {
                    if (line.startsWith("event: ")) {
                        const eventType = line.slice(7);
                        // next line should be data
                    }
                });
                read();
            });
        }
        read();
    }).catch(function(err) {
        setAgentStatus("错误：" + err.message);
    });
}

function approveAgent() {
    setAgentStatus("正在执行...");
    showAgentButtons("none");
    agentSource = new EventSource("/agent/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: agentThreadId, approved: true }),
    });
    setupResumeListeners();
}

function rejectAgent() {
    agentSource = new EventSource("/agent/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: agentThreadId, approved: false }),
    });
    setupResumeListeners();
}

function setupResumeListeners() {
    agentSource.addEventListener("node_complete", function(e) {
        const data = JSON.parse(e.data);
        updateProgress(data.stage || data.node);
    });

    agentSource.addEventListener("answer", function(e) {
        const data = JSON.parse(e.data);
        document.getElementById("agentAnswerBox").style.display = "block";
        document.getElementById("agentAnswerBox").innerHTML = escapeHtml(data.answer || "");
        if (data.sources) renderAgentSources(data.sources);
    });

    agentSource.addEventListener("done", function() {
        setAgentStatus("流程已完成");
        agentSource.close();
        agentSource = null;
    });
}

function renderAgentSources(sources) {
    const box = document.getElementById("agentSourcesBox");
    box.style.display = "flex";
    let html = "";
    sources.forEach(function(s) {
        const category = s.category === "新发现" ? "new" : "existing";
        const badge = s.category === "新发现"
            ? '<span class="source-badge badge-new">新发现</span>'
            : '<span class="source-badge badge-existing">已收录</span>';
        html += '<div class="source-card ' + category + '">' +
            '<h3>' + escapeHtml(s.source_id || "") + '. ' + escapeHtml(s.paper_title || "") + badge + '</h3>' +
            '<div class="source-meta">' +
            (s.year ? '年份: ' + s.year + ' | ' : '') +
            (s.doi ? 'DOI: ' + s.doi + ' | ' : '') +
            (s.score ? '评分: ' + s.score.toFixed(2) : '') +
            '</div></div>';
    });
    box.innerHTML = html;
}

document.getElementById("agentRunButton").addEventListener("click", startAgent);
document.getElementById("agentApproveButton").addEventListener("click", approveAgent);
document.getElementById("agentRejectButton").addEventListener("click", rejectAgent);