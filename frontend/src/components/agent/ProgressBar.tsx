import { StatusDot } from '../common/StatusDot';
import { WORKFLOW_STAGES, type StageKey } from '../../types/workflow';

interface ProgressBarProps {
  currentStage: string;
  completedStages: string[];
}

/** 7 阶段进度条。当前阶段蓝色，已完成绿色，未开始灰色。 */
export function ProgressBar({ currentStage, completedStages }: ProgressBarProps) {
  return (
    <div className="flex flex-wrap gap-1.5 my-3 p-2.5 bg-slate-50 rounded-lg">
      {WORKFLOW_STAGES.map((stage, index) => {
        const key = stage.key as StageKey;
        let status: 'pending' | 'active' | 'completed' = 'pending';
        if (currentStage === key || currentStage === `node_${key}`) {
          status = 'active';
        } else if (completedStages.includes(key) || completedStages.includes(`node_${key}`)) {
          status = 'completed';
        }

        return (
          <div key={key} className="flex items-center">
            <StatusDot status={status} label={stage.label} />
            {index < WORKFLOW_STAGES.length - 1 && (
              <span className="text-slate-300 mx-0.5 text-[10px]">→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
