import ReactMarkdown from 'react-markdown';
import { Bot } from 'lucide-react';

/** 回答卡片：Markdown 渲染。 */
export function AnswerCard({ answer }: { answer: string }) {
  if (!answer) return null;

  return (
    <div className="bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-200 rounded-xl p-4 my-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 bg-indigo-500 rounded-md flex items-center justify-center">
          <Bot className="w-4 h-4 text-white" strokeWidth={1.8} />
        </div>
        <h3 className="text-sm font-semibold text-indigo-800">智能体回答</h3>
      </div>
      <div className="prose prose-sm prose-slate max-w-none text-slate-700 leading-relaxed">
        <ReactMarkdown>{answer}</ReactMarkdown>
      </div>
    </div>
  );
}
