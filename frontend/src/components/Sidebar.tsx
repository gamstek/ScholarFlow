import { useState } from 'react';
import { Search, MessageCircle, BookOpen, FileText, Loader2, Bot, Wrench, Trash2, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { api, type HealthInfo } from '../lib/api';
import { ClearAllDialog } from './ClearAllDialog';
import { Logo } from './Logo';

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
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(null), 2500);
  };

  const handleClearFrontend = () => {
    localStorage.removeItem('scholarflow_search_state');
    localStorage.removeItem('scholarflow_agent_session');
    setToolMenuOpen(false);
    showSuccess('已清除前端缓存');
  };

  const handleClearHistory = async () => {
    localStorage.removeItem('scholarflow_search_state');
    localStorage.removeItem('scholarflow_agent_session');
    setToolMenuOpen(false);
    try {
      await api.clearSessions();
      showSuccess('已清除前端缓存 + 对话历史');
    } catch {
      showSuccess('已清除前端缓存（历史清除失败）');
    }
  };

  const handleClearAll = async () => {
    setConfirmOpen(false);
    setClearing(true);
    try {
      const res = await api.clearAll();
      localStorage.removeItem('scholarflow_search_state');
      localStorage.removeItem('scholarflow_agent_session');
      showSuccess(res.message);
    } catch {
      showSuccess('清除失败，请稍后重试');
    } finally {
      setClearing(false);
    }
  };

  return (
    <aside className="w-60 shrink-0 bg-white border-r border-gray-200 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-gray-100">
        <Logo size={32} />
        <div className="text-[10px] text-gray-400 leading-tight mt-1.5 ml-0.5">
          生物医学文献智能体
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

      {/* 工具菜单 */}
      <div className="relative px-3 pb-2">
        <button
          onClick={() => setToolMenuOpen(!toolMenuOpen)}
          className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
            toolMenuOpen ? 'bg-gray-100 text-gray-800' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
          }`}
        >
          <Wrench className="w-3.5 h-3.5 shrink-0" strokeWidth={1.8} />
          <span>工具</span>
        </button>
        {toolMenuOpen && (
          <div className="absolute bottom-full left-3 right-3 mb-1 bg-white border border-gray-200 rounded-xl shadow-lg py-1 z-50 animate-fade-in">
            <button
              onClick={handleClearFrontend}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-gray-600 hover:bg-gray-50 transition-colors text-left"
            >
              <Trash2 className="w-3.5 h-3.5 text-gray-400" />
              <div>
                <div className="leading-tight">清除前端缓存</div>
                <div className="text-[10px] text-gray-400">清除检索状态和会话记忆</div>
              </div>
            </button>
            <button
              onClick={handleClearHistory}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-gray-600 hover:bg-gray-50 transition-colors text-left"
            >
              <Trash2 className="w-3.5 h-3.5 text-gray-400" />
              <div>
                <div className="leading-tight">清除前端 + 历史</div>
                <div className="text-[10px] text-gray-400">额外清除 Agent 对话记录</div>
              </div>
            </button>
            <button
              onClick={() => { setToolMenuOpen(false); setConfirmOpen(true); }}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 text-xs text-red-500 hover:bg-red-50 transition-colors text-left"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
              <div>
                <div className="leading-tight">清除所有数据</div>
                <div className="text-[10px] text-red-400">文献·PDF·索引·对话</div>
              </div>
            </button>
          </div>
        )}
      </div>

      {/* 成功提示 */}
      {successMsg && (
        <div className="px-3 pb-2 animate-fade-in">
          <div className="flex items-center gap-1.5 px-3 py-2 bg-emerald-50 text-emerald-700 rounded-lg text-[11px]">
            <CheckCircle2 className="w-3 h-3" />
            {successMsg}
          </div>
        </div>
      )}

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

      {/* 二次确认对话框 */}
      <ClearAllDialog
        open={confirmOpen}
        clearing={clearing}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={handleClearAll}
      />
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
