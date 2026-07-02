import { useState } from 'react';

interface PicoData {
  population: string;
  intervention: string;
  comparison: string | null;
  outcome: string;
}

interface Criterion {
  criterion: string;
  rationale: string;
}

interface ProtocolData {
  protocol_id: number;
  status: string;
  pico: PicoData;
  keywords_en: string[];
  keywords_zh: string[];
  search_query: string;
  inclusion_criteria: Criterion[];
  exclusion_criteria: Criterion[];
  time_from: number;
  time_to: number;
  study_types: string[];
  data_sources: string[];
}

/** C01 课题协议页 — PICO 卡片 + 纳排编辑 + 审批。 */
export function ProtocolPage() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [protocol, setProtocol] = useState<ProtocolData | null>(null);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError('');
    setProtocol(null);

    try {
      const res = await fetch('/agent/protocol/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_question: input }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setProtocol(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!protocol) return;
    try {
      const res = await fetch('/agent/protocol/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ protocol_id: protocol.protocol_id }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setProtocol({ ...protocol, status: 'approved' });
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="space-y-4">
      {/* 输入区 */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <h2 className="text-lg font-bold text-zinc-200 mb-3">课题协议</h2>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={3}
          placeholder="输入你的研究课题，如：人乳寡糖（HMO）的 LC-MS/MS 结构解析方法研究"
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
        <button
          onClick={handleCreate}
          disabled={loading}
          className="mt-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          {loading ? '正在生成协议...' : '生成研究协议'}
        </button>
        {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
      </div>

      {/* PICO 卡片 */}
      {protocol && (
        <div className="space-y-4">
          {/* 状态 */}
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              protocol.status === 'approved' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
            }`}>
              {protocol.status === 'approved' ? '已批准' : '待审批'}
            </span>
            <span className="text-xs text-zinc-500">ID: {protocol.protocol_id}</span>
          </div>

          {/* PICO 四要素卡片 */}
          <div className="grid grid-cols-2 gap-3">
            <PicoCard label="P - Population" content={protocol.pico.population} icon="🧬" />
            <PicoCard label="I - Intervention" content={protocol.pico.intervention} icon="🔬" />
            <PicoCard label="C - Comparison" content={protocol.pico.comparison || '（无）'} icon="📊" />
            <PicoCard label="O - Outcome" content={protocol.pico.outcome} icon="🎯" />
          </div>

          {/* 关键词 + 检索式 */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
              <h3 className="text-sm font-bold text-zinc-300 mb-2">英文关键词</h3>
              <div className="flex flex-wrap gap-1">
                {protocol.keywords_en.map((kw, i) => (
                  <span key={i} className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded-full">{kw}</span>
                ))}
              </div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
              <h3 className="text-sm font-bold text-zinc-300 mb-2">中文关键词</h3>
              <div className="flex flex-wrap gap-1">
                {protocol.keywords_zh.map((kw, i) => (
                  <span key={i} className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded-full">{kw}</span>
                ))}
              </div>
            </div>
          </div>

          {/* 检索式 */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <h3 className="text-sm font-bold text-zinc-300 mb-2">推荐检索式（可编辑后执行）</h3>
            <code className="text-xs text-emerald-400 bg-zinc-800 block p-3 rounded-lg whitespace-pre-wrap">{protocol.search_query}</code>
          </div>

          {/* 纳排标准 */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-zinc-900 border border-emerald-800 rounded-xl p-4">
              <h3 className="text-sm font-bold text-emerald-400 mb-2">纳入标准</h3>
              <ul className="space-y-2">
                {protocol.inclusion_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-zinc-300">
                    <span className="text-emerald-500">+</span> {c.criterion}
                    <span className="text-zinc-500 block ml-4">理由: {c.rationale}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="bg-zinc-900 border border-red-800 rounded-xl p-4">
              <h3 className="text-sm font-bold text-red-400 mb-2">排除标准</h3>
              <ul className="space-y-2">
                {protocol.exclusion_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-zinc-300">
                    <span className="text-red-500">-</span> {c.criterion}
                    <span className="text-zinc-500 block ml-4">理由: {c.rationale}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* 范围 + 审批 */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex items-center justify-between">
            <div className="text-xs text-zinc-400 space-x-4">
              <span>时间: {protocol.time_from}–{protocol.time_to}</span>
              <span>类型: {protocol.study_types.join(', ')}</span>
              <span>来源: {protocol.data_sources.join(', ')}</span>
            </div>
            {protocol.status !== 'approved' && (
              <button
                onClick={handleApprove}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                批准协议
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function PicoCard({ label, content, icon }: { label: string; content: string; icon: string }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{icon}</span>
        <span className="text-xs font-bold text-zinc-400">{label}</span>
      </div>
      <p className="text-sm text-zinc-200">{content || '（待填充）'}</p>
    </div>
  );
}
