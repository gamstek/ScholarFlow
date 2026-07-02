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