import { useState } from 'react';
import { MessageCircle, Loader2, AlertCircle, MessageSquare } from 'lucide-react';
import { api, type Source } from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { SourceCard } from '../components/SourceCard';
import { EmptyState } from '../components/EmptyState';

export function AskPage() {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState('');
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState('');

  const handleAsk = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError('');
    setAnswer('');
    setSources([]);
    try {
      const data = await api.ask(question, 5);
      setAnswer(data.answer || '');
      setSources(data.sources || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="文献查询"
        subtitle="基于本地文献库的 RAG 问答 — 检索相关段落并由 LLM 生成回答"
      />

      {/* 输入栏 */}
      <div className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <MessageCircle className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
            placeholder="输入问题，如 HMO 的 LC-MS/MS 结构解析通常用哪些方法？"
            className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
          />
        </div>
        <button
          onClick={handleAsk}
          disabled={loading || !question.trim()}
          className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium flex items-center gap-2 transition-colors"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <MessageSquare className="w-4 h-4" />}
          {loading ? '查询中...' : '提问'}
        </button>
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm mb-4">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* 回答 */}
      {answer && (
        <div className="animate-fade-in space-y-5">
          <div className="p-5 rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="flex items-center gap-2 mb-3 pb-3 border-b border-gray-100">
              <MessageCircle className="w-4 h-4 text-indigo-500" />
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">回答</span>
            </div>
            <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
              {answer}
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
      {!answer && !error && !loading && (
        <EmptyState
          icon={MessageCircle}
          title="输入问题开始查询"
          hint="系统将从本地文献库中检索相关段落并生成回答"
        />
      )}
    </div>
  );
}
