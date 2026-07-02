import type { StagePlan } from '../../types/workflow';
import { AlertCircle } from 'lucide-react';

interface InterruptBannerProps {
  plan: StagePlan[];
  onApprove: () => void;
  onReject: () => void;
}

/** interrupt 确认横幅：等待用户确认计划。 */
export function InterruptBanner({ plan, onApprove, onReject }: InterruptBannerProps) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 my-3">
      <div className="flex items-center gap-2 mb-2">
        <AlertCircle className="w-4 h-4 text-amber-600" strokeWidth={1.8} />
        <p className="font-semibold text-amber-800 text-sm">
          已规划以下 {plan.length} 个步骤，是否执行？
        </p>
      </div>
      <ul className="text-xs text-amber-700 mb-3 space-y-1 ml-6">
        {plan.map((p, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="w-4 h-4 rounded-full bg-amber-200 text-amber-700 text-[10px] font-bold flex items-center justify-center shrink-0">
              {i + 1}
            </span>
            {p.stage} <span className="text-amber-500">({p.tool_name})</span>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          className="bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-1.5 rounded-lg text-xs font-medium transition-colors shadow-sm"
        >
          确认执行
        </button>
        <button
          onClick={onReject}
          className="bg-white hover:bg-amber-100 text-amber-700 border border-amber-300 px-4 py-1.5 rounded-lg text-xs font-medium transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  );
}
