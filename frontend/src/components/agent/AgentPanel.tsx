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
    <div className="bg-white border-2 border-blue-500 rounded-xl p-6 shadow-sm">
      <h2 className="text-lg font-bold text-blue-700 mb-4">Agent 任务</h2>

      {/* 输入区 */}
      <div className="flex gap-3 mb-3">
        <div className="flex-1">
          <input
            type="text"
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            placeholder="研究意图（选填）"
            disabled={isRunning}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-100"
          />
        </div>
        <div className="flex-[2]">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="具体问题，如：HMO 的 LC-MS/MS 结构解析方法？"
            disabled={isRunning}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:bg-gray-100"
          />
        </div>
      </div>

      {/* 按钮 */}
      <div className="flex gap-2">
        {state.status === 'idle' || state.status === 'done' || state.status === 'error' ? (
          <button
            onClick={handleStart}
            className="bg-blue-500 hover:bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            启动 Agent 任务
          </button>
        ) : null}

        {(state.status === 'done' || state.status === 'error') && (
          <button
            onClick={reset}
            className="bg-gray-200 hover:bg-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm transition-colors"
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
        <p className="text-sm text-gray-500 mt-2">
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
        <div className="bg-red-50 border border-red-300 rounded-lg p-3 my-3 text-sm text-red-700">
          {state.error}
        </div>
      )}

      {/* 回答 */}
      {state.answer && <AnswerCard answer={state.answer} />}

      {/* 来源 */}
      {state.sources.length > 0 && (
        <div className="space-y-2 mt-3">
          <h3 className="font-semibold text-gray-700 text-sm">
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
