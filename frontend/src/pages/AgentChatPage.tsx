import { useState, useRef, useEffect, useCallback } from 'react';
import { Bot, User, Send, Loader2, AlertCircle, Wrench, Plus, MessageSquare, Trash2, ChevronLeft } from 'lucide-react';
import { api, type AgentChatResult, type AgentSession } from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: AgentChatResult['tool_calls'];
}

const SUGGESTIONS = [
  '帮我找关于 CRISPR 基因编辑在农作物改良方面的论文',
  '对本地文献库提问：HMO 的结构鉴定方法有哪些？',
  '帮我写一篇关于食品代谢组学的文献综述',
];

export function AgentChatPage() {
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const SESSION_STORAGE_KEY = 'scholarflow_agent_session';

  // 恢复上次会话
  useEffect(() => {
    const savedId = localStorage.getItem(SESSION_STORAGE_KEY);
    if (savedId) {
      setCurrentSessionId(savedId);
      api.agentGetSession(savedId).then((data) => {
        const msgs: Message[] = data.messages.map((m) => ({
          role: m.role === 'human' ? 'user' : 'assistant',
          content: m.content,
          toolCalls: m.tool_calls,
        }));
        setMessages(msgs);
      }).catch(() => {
        localStorage.removeItem(SESSION_STORAGE_KEY);
      });
    }
  }, []);

  // 保存当前会话 ID
  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem(SESSION_STORAGE_KEY, currentSessionId);
    }
  }, [currentSessionId]);

  // 加载会话列表
  const loadSessions = useCallback(async () => {
    try {
      const data = await api.agentListSessions();
      setSessions(data.sessions);
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  // 切换会话
  const handleSelectSession = async (sessionId: string) => {
    if (loading) return;
    setCurrentSessionId(sessionId);
    setError('');
    try {
      const data = await api.agentGetSession(sessionId);
      const msgs: Message[] = data.messages.map((m) => ({
        role: m.role === 'human' ? 'user' : 'assistant',
        content: m.content,
        toolCalls: m.tool_calls,
      }));
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  };

  // 新建会话
  const handleNewSession = () => {
    if (loading) return;
    setCurrentSessionId(null);
    setMessages([]);
    setError('');
  };

  // 删除会话
  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    if (loading) return;
    try {
      await api.agentDeleteSession(sessionId);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      loadSessions();
    } catch {
      // 静默
    }
  };

  const handleSend = async (text?: string) => {
    const message = (text || input).trim();
    if (!message || loading) return;

    setInput('');
    setError('');
    setMessages((prev) => [...prev, { role: 'user', content: message }]);
    setLoading(true);

    try {
      const result = await api.agentChat(message, currentSessionId || undefined);

      // 如果是新会话，更新 currentSessionId
      if (!currentSessionId) {
        setCurrentSessionId(result.session_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: result.answer,
          toolCalls: result.tool_calls,
        },
      ]);

      // 刷新会话列表（更新标题和消息数）
      loadSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `抱歉，处理时出错了：${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in flex h-full">
      {/* 会话列表侧边栏 */}
      {sidebarOpen && (
        <div className="w-56 shrink-0 border-r border-gray-200 flex flex-col bg-white">
          <div className="p-3 border-b border-gray-100">
            <button
              onClick={handleNewSession}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              新建对话
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {sessions.length === 0 ? (
              <p className="text-center text-xs text-gray-400 py-8">暂无历史对话</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.session_id}
                  onClick={() => handleSelectSession(s.session_id)}
                  className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${
                    currentSessionId === s.session_id
                      ? 'bg-indigo-50 text-indigo-700'
                      : 'hover:bg-gray-50 text-gray-600'
                  }`}
                >
                  <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-50" />
                  <span className="flex-1 truncate text-xs">{s.title}</span>
                  <button
                    onClick={(e) => handleDeleteSession(e, s.session_id)}
                    className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-opacity"
                    title="删除对话"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* 主对话区 */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶部栏 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
            title={sidebarOpen ? '收起会话列表' : '展开会话列表'}
          >
            <ChevronLeft className={`w-4 h-4 transition-transform ${!sidebarOpen ? 'rotate-180' : ''}`} />
          </button>
          <div className="flex-1 min-w-0">
            <h2 className="text-sm font-semibold text-gray-800 truncate">
              {currentSessionId ? '对话' : '新对话'}
            </h2>
            <p className="text-xs text-gray-400">
              Agent 会记住当前对话的上下文
            </p>
          </div>
        </div>

        {/* 消息区 */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto space-y-4 p-4 min-h-0"
        >
          {messages.length === 0 && (
            <div className="text-center py-12">
              <Bot className="w-12 h-12 mx-auto text-gray-300 mb-3" />
              <p className="text-sm text-gray-400 mb-4">
                我是 ScholarFlow Agent，可以帮你检索论文、查看全文、回答问题和写综述。
              </p>
              <div className="flex flex-col gap-2 max-w-md mx-auto">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => handleSend(s)}
                    className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs text-gray-600 hover:border-indigo-300 hover:text-indigo-600 transition-colors text-left"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} />
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              Agent 思考中...
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div className="flex gap-2 border-t border-gray-200 p-4">
          <div className="relative flex-1">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="输入消息，如：帮我找关于肿瘤免疫的论文"
              className="w-full px-4 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
            />
          </div>
          <button
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
            className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium flex items-center gap-2 transition-colors"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
          isUser
            ? 'bg-gray-100 text-gray-500'
            : 'bg-indigo-600 text-white'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      <div className={`flex-1 max-w-[80%] ${isUser ? 'text-right' : ''}`}>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2 space-y-1">
            {message.toolCalls.map((tc, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-50 border border-gray-100 text-[10px] text-gray-500"
              >
                <Wrench className="w-3 h-3 shrink-0 text-indigo-400" />
                <span className="font-medium text-indigo-600">{tc.tool}</span>
                <span className="truncate max-w-[300px] text-gray-400">
                  {typeof tc.input === 'object' ? JSON.stringify(tc.input) : String(tc.input)}
                </span>
              </div>
            ))}
          </div>
        )}

        <div
          className={`inline-block px-3 py-2 rounded-lg text-sm ${
            isUser
              ? 'bg-indigo-600 text-white'
              : 'bg-white border border-gray-200 text-gray-800'
          }`}
        >
          <div className="whitespace-pre-wrap text-left">{message.content}</div>
        </div>
      </div>
    </div>
  );
}
