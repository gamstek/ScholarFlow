import { AgentPanel } from '../agent/AgentPanel';
import { PaperList } from '../papers/PaperList';

/** 整体页面布局：左侧 Agent 面板，右侧文献库。 */
export function AppShell() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部标题 */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              ScholarFlow
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              文献采集与检索智能体 v1.1.0
            </p>
          </div>
          <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
            LangGraph + SSE
          </span>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 左栏：Agent */}
          <div>
            <AgentPanel />
          </div>

          {/* 右栏：文献库 */}
          <div className="bg-white rounded-xl p-6 shadow-sm">
            <h2 className="text-lg font-bold text-gray-700 mb-4">文献库</h2>
            <PaperList />
          </div>
        </div>
      </main>
    </div>
  );
}
