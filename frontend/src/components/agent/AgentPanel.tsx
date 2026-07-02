import { useState } from 'react';
import { useAgentRun } from '../../hooks/useAgentRun';
import { ProgressBar } from './ProgressBar';
import { InterruptBanner } from './InterruptBanner';
import { AnswerCard } from './AnswerCard';
import { SourceCard } from '../sources/SourceCard';

/** Agent 任务面板：输入 + 启动 + 进度 + 结果。 */
export function AgentPanel() {
  const [intent, setIntent] = useState('');
  const [question, setQuestion] = useState('');
  const { state, run, resume, reset } = useAgentRun();

  const handleStart = () => {
    if (!question.trim()) return;
    run(intent, question);
  };

  const handleApprove = () => {
    resume(state.threadId, true);
  };

  const handleReject = () => {
    resume(state.threadId, false);
  };

  const isRunning = state.status === 'running' || state.status === 'interrupted';

  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
      <div className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-blue-500 rounded-lg flex items-center justify-center">
          <span className="text-white text-sm font-bold">AI</span>
        </div>
        <div>
          <h2 className="text-sm font-bold text-slate-800">智能体检索</h2>
          <p className="text-[10px] text-slate-400">LangGraph 工作流 · SSE 实时推送</p>
        </div>
      </div>

      {/* 输入区 */}
      <div className="space-y-2 mb-3">
        <input
          type="text"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="研究意图（选填），如：跟踪 HMO 质谱解析文献"
          disabled={isRunning}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent disabled:bg-slate-50 disabled:text-slate-400"
        />
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="具体问题，如：HMO 的 LC-MS/MS 结构解析方法？"
          disabled={isRunning}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !isRunning) handleStart();
          }}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent disabled:bg-slate-50 disabled:text-slate-400"
        />
      </div>

      {/* 按钮 */}
      <div className="flex gap-2">
        {state.status === 'idle' || state.status === 'done' || state.status === 'error' ? (
          <button
            onClick={handleStart}
            disabled={!question.trim()}
            className="bg-gradient-to-r from-indigo-500 to-blue-500 hover:from-indigo-600 hover:to-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium transition-all shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            启动智能体
          </button>
        ) : null}

        {(state.status === 'done' || state.status === 'error') && (
          <button
            onClick={reset}
            className="bg-slate-100 hover:bg-slate-200 text-slate-600 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            重置
          </button>
        )}
      </div>

      {/* 进度条 */}
      {isRunning && (
        <ProgressBar
          currentStage={state.currentStage}
          completedStages={state.completedStages}
        />
      )}

      {/* 状态文字 */}
      {isRunning && (
        <p className="text-xs text-slate-500 mt-2 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-pulse" />
          状态：{state.currentStage || '初始化中...'}
        </p>
      )}

      {/* interrupt 横幅 */}
      {state.status === 'interrupted' && (
        <InterruptBanner
          plan={state.plan}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      {/* 错误 */}
      {state.error && (
        <div className="bg-rose-50 border border-rose-200 rounded-lg p-3 my-3 text-xs text-rose-700">
          {state.error}
        </div>
      )}

      {/* 回答 */}
      {state.answer && <AnswerCard answer={state.answer} />}

      {/* 来源 */}
      {state.sources.length > 0 && (
        <div className="space-y-2 mt-3">
          <h3 className="font-semibold text-slate-700 text-xs flex items-center gap-1.5">
            <span className="w-1 h-3.5 bg-indigo-500 rounded-full" />
            参考来源 ({state.sources.length})
          </h3>
          {state.sources.map((source) => (
            <SourceCard key={source.source_id} source={source} />
          ))}
        </div>
      )}
    </div>
  );
}
