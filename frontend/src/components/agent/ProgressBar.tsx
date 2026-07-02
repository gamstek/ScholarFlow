import { StatusDot } from '../common/StatusDot';
import { WORKFLOW_STAGES, type StageKey } from '../../types/workflow';

interface ProgressBarProps {
  currentStage: string;
  completedStages: string[];
}

/** 7 阶段进度条。当前阶段蓝色，已完成绿色，未开始灰色。 */
export function ProgressBar({ currentStage, completedStages }: ProgressBarProps) {
  return (
    <div className="flex flex-wrap gap-2 my-4">
      {WORKFLOW_STAGES.map((stage) => {
        const key = stage.key as StageKey;
        let status: 'pending' | 'active' | 'completed' = 'pending';
        if (currentStage === key || currentStage === `node_${key}`) {
          status = 'active';
        } else if (completedStages.includes(key) || completedStages.includes(`node_${key}`)) {
          status = 'completed';
        }

        return <StatusDot key={key} status={status} label={stage.label} />;
      })}
    </div>
  );
}
