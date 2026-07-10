import { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar, type TabKey } from './components/Sidebar';
import { SearchPage } from './pages/SearchPage';
import { AgentChatPage } from './pages/AgentChatPage';
import { AskPage } from './pages/AskPage';
import { LibraryPage } from './pages/LibraryPage';
import { ReviewPage } from './pages/ReviewPage';
import { PaperDetailPage } from './pages/PaperDetailPage';
import { api, type HealthInfo } from './lib/api';

const queryClient = new QueryClient();

function App() {
  const [tab, setTab] = useState<TabKey>('search');
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);

  // 阅读模式：点击文献标题时进入
  const [readingPaperId, setReadingPaperId] = useState<number | null>(null);

  // 健康检查：失败时重试 3 次（递增间隔），应对服务尚未就绪的竞态
  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    const maxRetries = 3;

    const check = async () => {
      for (let i = 0; i <= maxRetries; i++) {
        try {
          const data = await api.health();
          if (!cancelled) {
            setHealth(data);
            setHealthLoading(false);
          }
          return;
        } catch {
          if (i < maxRetries) {
            await new Promise((r) => setTimeout(r, (i + 1) * 2000));
          }
        }
      }
      if (!cancelled) {
        setHealth(null);
        setHealthLoading(false);
      }
    };

    check();
    return () => { cancelled = true; };
  }, []);

  const handleSelectPaper = (paperId: number) => {
    setReadingPaperId(paperId);
    setTab('library');
  };

  const handleBackToLibrary = () => {
    setReadingPaperId(null);
  };

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex min-h-screen bg-[#fafafa]">
        <Sidebar
          active={tab}
          onNavigate={(t) => {
            setTab(t);
            if (t !== 'library') setReadingPaperId(null);
          }}
          health={health}
          healthLoading={healthLoading}
        />

        {/* 内容区 — 用 display:none 保持各页面 state 不丢失 */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-4xl mx-auto px-8 py-8">
            <div style={{ display: tab === 'search' ? 'block' : 'none' }}>
              <SearchPage onSelectPaper={handleSelectPaper} />
            </div>
            <div style={{ display: tab === 'agent' ? 'flex' : 'none' }} className="flex-col h-[calc(100vh-4rem)]">
              <AgentChatPage />
            </div>
            <div style={{ display: tab === 'ask' ? 'block' : 'none' }}>
              <AskPage />
            </div>
            <div style={{ display: tab === 'library' ? 'block' : 'none' }}>
              {readingPaperId ? (
                <PaperDetailPage paperId={readingPaperId} onBack={handleBackToLibrary} />
              ) : (
                <LibraryPage onSelectPaper={handleSelectPaper} />
              )}
            </div>
            <div style={{ display: tab === 'review' ? 'block' : 'none' }}>
              <ReviewPage />
            </div>
          </div>
        </main>
      </div>
    </QueryClientProvider>
  );
}

export default App;
