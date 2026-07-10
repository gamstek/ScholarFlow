import { useState } from 'react';
import { FileText, Loader2, AlertCircle, Download } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { api, type Source } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { SourceCard } from '../components/SourceCard';
import { EmptyState } from '../components/EmptyState';

export function ReviewPage() {
  const [topic, setTopic] = useState('');
  const [topK, setTopK] = useState(15);
  const [loading, setLoading] = useState(false);
  const [review, setReview] = useState('');
  const [sources, setSources] = useState<Source[]>([]);
  const [evidenceCount, setEvidenceCount] = useState(0);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setError('');
    setReview('');
    setSources([]);
    setEvidenceCount(0);
    try {
      const data = await api.review(topic, topK);
      setReview(data.review || '');
      setSources(data.sources || []);
      setEvidenceCount(data.evidence_count || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([review], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `review_${topic.slice(0, 20).replace(/\s+/g, '_')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="写文献综述"
        subtitle="基于本地文献库自动生成结构化 Markdown 综述"
      />

      {/* 输入栏 */}
      <div className="flex gap-2 mb-4">
        <div className="relative flex-1">
          <FileText className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
            placeholder="输入综述主题，如 HMO 的 LC-MS/MS 结构解析方法"
            className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
          />
        </div>
        <select
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="px-3 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-indigo-500"
        >
          {[5, 10, 15, 20, 30].map((n) => (
            <option key={n} value={n}>Top {n}</option>
          ))}
        </select>
        <button
          onClick={handleGenerate}
          disabled={loading || !topic.trim()}
          className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium flex items-center gap-2 transition-colors"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
          {loading ? '生成中...' : '生成综述'}
        </button>
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm mb-4">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* 综述内容 */}
      {review && (
        <div className="animate-fade-in space-y-5">
          {/* 工具栏 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>引用 <strong className="text-gray-700">{evidenceCount}</strong> 条证据</span>
              <span className="text-gray-300">|</span>
              <span>Top {topK} chunks</span>
            </div>
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-xs text-gray-600 transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              下载 .md
            </button>
          </div>

          {/* Markdown 渲染 */}
          <div className="p-6 rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="prose-academic max-w-none">
              <ReactMarkdown>{review}</ReactMarkdown>
            </div>
          </div>

          {/* 来源 */}
          {sources.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                  引用来源
                </span>
                <span className="text-xs text-gray-400">({sources.length})</span>
              </div>
              <div className="space-y-2">
                {sources.map((s) => (
                  <SourceCard key={s.source_id} source={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 空状态 */}
      {!review && !error && !loading && (
        <EmptyState
          icon={FileText}
          title="输入主题生成综述"
          hint="系统将检索本地文献库中最相关的段落，由 LLM 生成结构化综述"
        />
      )}
    </div>
  );
}
