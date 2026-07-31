/**
 * api.ts — 类型化 API 调用层
 */

// ============================================================
// 类型定义
// ============================================================

export interface Paper {
  id: number;
  title: string;
  doi: string | null;
  pmid: string | null;
  pmcid: string | null;
  year: number | null;
  status: string;
  domain_score: number;
  journal: string | null;
  authors_json: string | null;
  abstract?: string | null;
  source?: string | null;
  url?: string | null;
  pdf_url?: string | null;
  license?: string | null;
  is_open_access?: number;
  local_pdf_path?: string | null;
  local_text_path?: string | null;
  pipeline_step?: string | null;
  pipeline_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PaperResponse {
  papers: Paper[];
  total?: number;
}

export interface Stat {
  status: string;
  count: number;
}

export interface StatsResponse {
  papers_total: number;
  chunks_total: number;
  paper_status: Stat[];
}

export interface Source {
  source_id: number;
  score: number;
  paper_title: string;
  year: number | null;
  journal: string | null;
  doi: string | null;
  section_title: string | null;
}

// 新版检索结果（search_only 模式）
export interface SearchHit {
  title: string;
  abstract: string | null;
  authors: string[] | null;
  author_affiliations: Array<{ name: string }> | null;
  year: number | null;
  journal: string | null;
  doi: string | null;
  pmid: string | null;
  pmcid: string | null;
  source: string;
  url: string | null;
  pdf_url: string | null;
  license: string | null;
  is_open_access: number;
  citation_count: number | null;
  domain_score: number;
  in_library: boolean;
  paper_id: number | null;
  library_status: string | null;
  tags: string[];
}

export interface SearchResult {
  query: string;
  sources: string[];
  retrieved_count: number;
  deduplicated_count: number;
  keywords: string[] | null;
  domain: string | null;
  sort_by?: string;
  sort_order?: string;
  results: SearchHit[];
  errors: string[];
}

export interface AskResult {
  answer: string;
  sources: Source[];
  model?: string;
}

export interface ReviewResult {
  topic: string;
  review: string;
  sources: Source[];
  evidence_count: number;
  model: string;
}

export interface HealthInfo {
  status: string;
  version: string;
  llm: { provider: string; model: string; status: string };
  embedding: { provider: string; model: string };
}

export interface ImportResult {
  paper_id: number;
  title: string;
  doi: string | null;
  status: string;
  message: string;
}

export interface ProcessResult {
  paper_id: number;
  title: string;
  status: string;
  message: string;
}

export interface AgentChatResult {
  answer: string;
  tool_calls: Array<{
    tool: string;
    input: string;
    output: string;
  }>;
  session_id: string;
  model: string;
}

export interface AgentSession {
  session_id: string;
  title: string;
  created_at: number;
  message_count: number;
}

export interface AgentSessionDetail {
  session_id: string;
  messages: Array<{
    role: string;
    content: string;
    tool_calls?: AgentChatResult['tool_calls'];
  }>;
}

export interface PaperDetail {
  id: number;
  title: string;
  abstract: string | null;
  doi: string | null;
  year: number | null;
  journal: string | null;
  status: string;
  domain_score: number;
  local_pdf_path: string | null;
  local_text_path: string | null;
  authors_json: string | null;
}

export interface PaperText {
  paper_id: number;
  paper_title: string;
  total_chunks: number;
  full_text: string;
}

// ============================================================
// 请求封装
// ============================================================

async function post<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
  return data as T;
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return (await res.json()) as T;
}

async function del<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) throw new Error(`请求失败 (${res.status})`);
  return (await res.json()) as T;
}

// ============================================================
// API 函数
// ============================================================

export const api = {
  health: () => get<HealthInfo>('/health'),
  stats: () => get<StatsResponse>('/stats'),
  papers: (limit = 50) => get<PaperResponse>(`/papers?limit=${limit}`),

  // 新版检索：支持 natural_query
  search: (params: {
    query?: string;
    natural_query?: string;
    sources: string[];
    max_results: number;
    sort_by?: string;
    sort_order?: string;
    author?: string;
    journal?: string;
    preprint_sources?: string[];
    language?: string;
    max_total?: number;
  }) => post<SearchResult>('/search', params),

  // 流式检索：通过 SSE 推送进度
  searchStream: async (
    params: {
      query?: string;
      natural_query?: string;
      sources: string[];
      max_results: number;
      sort_by?: string;
      sort_order?: string;
      author?: string;
      journal?: string;
      preprint_sources?: string[];
      language?: string;
      max_total?: number;
    },
    onProgress: (current: number, total: number, source: string, sourceCount: number) => void,
  ): Promise<SearchResult> => {
    const res = await fetch('/search/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error((errData as { detail?: string }).detail || `请求失败 (${res.status})`);
    }

    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'progress') {
              onProgress(data.current, data.total, data.source, data.source_count ?? 0);
            } else if (data.type === 'result') {
              return data as SearchResult;
            }
          } catch {
            // 跳过无法解析的行
          }
        }
      }
    }
    throw new Error('SSE stream ended without result');
  },

  // 单篇论文入库
  importPaper: (paper: {
    title: string;
    abstract?: string | null;
    authors?: string[] | null;
    author_affiliations?: Array<{ name: string }> | null;
    year?: number | null;
    journal?: string | null;
    doi?: string | null;
    pmid?: string | null;
    pmcid?: string | null;
    source?: string;
    url?: string | null;
    pdf_url?: string | null;
    license?: string | null;
    is_open_access?: number;
    domain_score?: number;
  }) => post<ImportResult>('/papers/import', paper),

  // 触发后台流水线
  processPaper: (paperId: number) =>
    post<ProcessResult>(`/papers/${paperId}/process`, {}),

  // 批量入库（metadata）
  importPapersBatch: (papers: Array<{
    title: string;
    abstract?: string | null;
    authors?: string[] | null;
    author_affiliations?: Array<{ name: string }> | null;
    year?: number | null;
    journal?: string | null;
    doi?: string | null;
    pmid?: string | null;
    pmcid?: string | null;
    source?: string;
    url?: string | null;
    pdf_url?: string | null;
    license?: string | null;
    is_open_access?: number;
    domain_score?: number;
  }>) => post<{
    total: number;
    success_count: number;
    failed_count: number;
    results: Array<{ success: boolean; paper_id?: number; title?: string; error?: string }>;
  }>('/papers/import-batch', { papers }),

  // 批量处理
  processPapersBatch: (paperIds: number[]) => post<{
    total: number;
    triggered: number;
    not_found: number;
    results: Array<{ paper_id: number; success: boolean; title?: string; error?: string }>;
  }>('/papers/process-batch', { paper_ids: paperIds }),

  // 删除文献
  deletePaper: (paperId: number) =>
    del<{ deleted: boolean; paper_id: number; title: string }>(`/papers/${paperId}`),

  // 论文详情
  getPaper: (paperId: number) => get<PaperDetail>(`/papers/${paperId}`),

  // 论文全文
  getPaperText: (paperId: number) => get<PaperText>(`/papers/${paperId}/text`),

  // RAG 问答
  ask: (question: string, top_k = 5) =>
    post<AskResult>('/ask', { question, top_k }),

  // 文献综述
  review: (topic: string, top_k = 15) =>
    post<ReviewResult>('/review', { topic, top_k }),

  // Agent 对话
  agentChat: (message: string, sessionId?: string) =>
    post<AgentChatResult>('/agent/chat', { message, session_id: sessionId }),

  // Agent 会话管理
  agentListSessions: () => get<{ sessions: AgentSession[] }>('/agent/sessions'),
  agentGetSession: (sessionId: string) => get<AgentSessionDetail>(`/agent/sessions/${sessionId}`),
  agentDeleteSession: (sessionId: string) => del<{ deleted: boolean }>(`/agent/sessions/${sessionId}`),

  // 翻译
  translate: (text: string) => post<{ translated: string; original: string; note?: string }>('/translate', { text }),

  // 管理工具 — 清除缓存
  clearSessions: () => post<{ cleared: boolean; message: string }>('/admin/clear-sessions', {}),
  clearAll: () => post<{ cleared: boolean; papers: number; message: string; errors?: string[] | null }>('/admin/clear-all', {}),

  // 手动上传 PDF
  uploadPdf: async (paperId: number, file: File): Promise<{ paper_id: number; message: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`/papers/${paperId}/upload-pdf`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`上传失败 (${res.status})`);
    return (await res.json()) as { paper_id: number; message: string };
  },

  // 独立上传 PDF 入库（不需要预先入库）
  uploadStandalonePdf: async (file: File): Promise<{ paper_id: number; title: string; message: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/papers/upload-pdf', {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`上传失败 (${res.status})`);
    return (await res.json()) as { paper_id: number; title: string; message: string };
  },
};
