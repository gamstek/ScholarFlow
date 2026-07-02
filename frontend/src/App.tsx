import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProtocolPage } from './components/protocol/ProtocolPage';
import { AgentPanel } from './components/agent/AgentPanel';

const queryClient = new QueryClient();

const TABS = [
  { key: 'protocol', label: '课题协议' },
  { key: 'agent', label: 'Agent 工作流' },
] as const;

function App() {
  const [tab, setTab] = useState<string>('protocol');

  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen bg-zinc-950 text-zinc-200">
        {/* 顶栏 */}
        <header className="bg-zinc-900 border-b border-zinc-800 px-6 py-3">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <h1 className="text-xl font-bold tracking-tight">ScholarFlow</h1>
            <div className="flex gap-1">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    tab === t.key
                      ? 'bg-blue-600 text-white'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* 主内容 */}
        <main className="max-w-5xl mx-auto px-6 py-6">
          {tab === 'protocol' && <ProtocolPage />}
          {tab === 'agent' && <AgentPanel />}
        </main>

        {/* 底栏 */}
        <footer className="fixed bottom-0 w-full bg-zinc-900 border-t border-zinc-800 px-6 py-1.5">
          <div className="max-w-7xl mx-auto flex items-center justify-between text-xs text-zinc-600">
            <span>ScholarFlow v1.2.0</span>
            <span>C01: PICO Protocol · Gate 1</span>
          </div>
        </footer>
      </div>
    </QueryClientProvider>
  );
}

export default App;
