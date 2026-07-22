import { useState } from 'react';
import { AlertTriangle, X, Loader2 } from 'lucide-react';

interface ClearAllDialogProps {
  open: boolean;
  clearing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ClearAllDialog({ open, clearing, onCancel, onConfirm }: ClearAllDialogProps) {
  const [inputValue, setInputValue] = useState('');
  const match = inputValue === '确认删除';

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 animate-fade-in"
      onClick={onCancel}>
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full mx-4"
        onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <h3 className="text-sm font-semibold text-gray-900">确认清除所有数据</h3>
          </div>
          <button onClick={onCancel}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-gray-600">
            此操作不可恢复，将永久删除：
          </p>
          <ul className="text-sm text-gray-500 space-y-1.5 list-disc list-inside">
            <li>所有入库文献记录</li>
            <li>所有下载的 PDF 文件</li>
            <li>FAISS 向量检索索引</li>
            <li>所有 Agent 对话历史</li>
          </ul>
          <p className="text-xs text-gray-400">
            请输入「确认删除」以继续：
          </p>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="确认删除"
            autoFocus
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent"
          />
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2.5 px-5 py-4 border-t border-gray-100">
          <button
            onClick={onCancel}
            disabled={clearing}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={() => { if (match) onConfirm(); }}
            disabled={!match || clearing}
            className="px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {clearing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            确认清除
          </button>
        </div>
      </div>
    </div>
  );
}
