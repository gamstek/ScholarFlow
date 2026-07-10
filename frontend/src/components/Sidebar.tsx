import { Search, MessageCircle, BookOpen, FileText, Loader2, Bot } from 'lucide-react';
import type { HealthInfo } from '../lib/api';

const NAV_ITEMS = [
  { key: 'search', label: '文献检索', icon: Search, desc: '智能语义检索' },
  { key: 'agent', label: 'Agent 对话', icon: Bot, desc: '自然语言交互' },
  { key: 'ask', label: '文献查询', icon: MessageCircle, desc: 'RAG 问答' },
  { key: 'library', label: '文献库', icon: BookOpen, desc: '已入库文献' },
  { key: 'review', label: '写综述', icon: FileText, desc: '自动生成综述' },
] as const;

export type TabKey = (typeof NAV_ITEMS)[number]['key'];

interface SidebarProps {
  active: TabKey;
  onNavigate: (tab: TabKey) => void;
  health: HealthInfo | null;
  healthLoading: boolean;
}

export function Sidebar({ active, onNavigate, health, healthLoading }: SidebarProps) {
  return (
    <aside className="w-60 shrink-0 bg-white border-r border-gray-200 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
            <BookOpen className="w-4.5 h-4.5 text-white" strokeWidth={2.2} />
          </div>
          <div>
            <div className="text-[15px] font-semibold text-gray-900 leading-tight">
              ScholarFlow
            </div>
            <div className="text-[10px] text-gray-400 leading-tight">
              个人文献工作站
            </div>
          </div>
        </div>
      </div>

      {/* 导航 */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = active === item.key;
          return (
            <button
              key={item.key}
              onClick={() => onNavigate(item.key)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 group ${
                isActive
                  ? 'bg-indigo-50 text-indigo-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              }`}
            >
              <item.icon
                className={`w-4 h-4 shrink-0 ${isActive ? 'text-indigo-600' : 'text-gray-400 group-hover:text-gray-600'}`}
                strokeWidth={2}
              />
              <div className="text-left">
                <div className="leading-tight">{item.label}</div>
                <div className={`text-[10px] leading-tight ${isActive ? 'text-indigo-400' : 'text-gray-400'}`}>
                  {item.desc}
                </div>
              </div>
            </button>
          );
        })}
      </nav>

      {/* 状态 */}
      <div className="px-4 py-3 border-t border-gray-100 space-y-2">
        {healthLoading ? (
          <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            连接中...
          </div>
        ) : health ? (
          <>
            <StatusRow
              label="LLM"
              value={health.llm.model}
              ok={health.llm.status === 'ok'}
            />
            <StatusRow
              label="Embedding"
              value={health.embedding.model.split('/').pop() || health.embedding.model}
              ok={true}
            />
          </>
        ) : (
          <div className="text-[11px] text-red-500">后端未连接</div>
        )}
      </div>
    </aside>
  );
}

function StatusRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-gray-400">{label}</span>
      <span className="flex items-center gap-1.5 text-gray-600">
        <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
        <span className="truncate max-w-[100px]">{value}</span>
      </span>
    </div>
  );
}
