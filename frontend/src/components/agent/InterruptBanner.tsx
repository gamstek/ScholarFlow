import type { StagePlan } from '../../types/workflow';

interface InterruptBannerProps {
  plan: StagePlan[];
  onApprove: () => void;
  onReject: () => void;
}

/** interrupt 确认横幅：等待用户确认计划。 */
export function InterruptBanner({ plan, onApprove, onReject }: InterruptBannerProps) {
  return (
    <div className="bg-amber-50 border border-amber-300 rounded-lg p-4 my-4">
      <p className="font-semibold text-amber-800 mb-2">
        已规划以下 {plan.length} 个步骤，是否执行？
      </p>
      <ul className="text-sm text-amber-700 mb-3 space-y-1">
        {plan.map((p, i) => (
          <li key={i}>
            {i + 1}. {p.stage} ({p.tool_name})
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          className="bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          确认执行
        </button>
        <button
          onClick={onReject}
          className="bg-gray-200 hover:bg-gray-300 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  );
}
