import { useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { TopBar } from './TopBar';
import { SideNav } from './SideNav';
import { RightPanel } from './RightPanel';
import { BottomBar } from './BottomBar';
import { ProtocolPage } from '../../pages/ProtocolPage';
import { DiscoveryPage } from '../../pages/DiscoveryPage';
import { ScreeningPage } from '../../pages/ScreeningPage';
import { ReadingPage } from '../../pages/ReadingPage';
import { EvidenceGraphPage } from '../../pages/EvidenceGraphPage';
import { WritingPage } from '../../pages/WritingPage';
import { MonitorPage } from '../../pages/MonitorPage';
import { SettingsPage } from '../../pages/SettingsPage';
import type { PageKey } from '../../types/nav';

/** 整体页面布局：顶栏 + 左导航 + 主工作区 + 右面板 + 底栏。 */
export function AppShell() {
  const [activePage, setActivePage] = useState<PageKey>('discovery');
  const queryClient = useQueryClient();

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  const renderPage = () => {
    switch (activePage) {
      case 'protocol':
        return <ProtocolPage />;
      case 'discovery':
        return <DiscoveryPage />;
      case 'screening':
        return <ScreeningPage />;
      case 'reading':
        return <ReadingPage />;
      case 'graph':
        return <EvidenceGraphPage />;
      case 'writing':
        return <WritingPage />;
      case 'monitor':
        return <MonitorPage />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <DiscoveryPage />;
    }
  };

  return (
    <div className="flex flex-col h-screen bg-slate-50 overflow-hidden">
      {/* 顶栏 */}
      <TopBar onRefresh={handleRefresh} />

      {/* 主区域 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧导航 */}
        <SideNav activePage={activePage} onPageChange={setActivePage} />

        {/* 主工作区 */}
        <main className="flex-1 overflow-y-auto">
          {renderPage()}
        </main>

        {/* 右侧面板 */}
        <RightPanel />
      </div>

      {/* 底栏 */}
      <BottomBar />
    </div>
  );
}
