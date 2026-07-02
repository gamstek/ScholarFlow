// 工作流阶段定义
export const WORKFLOW_STAGES = [
  { key: 'crawl', label: '采集', icon: 'Search' },
  { key: 'download', label: '下载', icon: 'Download' },
  { key: 'parse', label: '解析', icon: 'FileText' },
  { key: 'chunk', label: '切块', icon: 'Scissors' },
  { key: 'index', label: '索引', icon: 'Database' },
  { key: 'rag_search', label: '检索', icon: 'Brain' },
  { key: 'qa', label: '回答', icon: 'MessageSquare' },
] as const;

export type StageKey = (typeof WORKFLOW_STAGES)[number]['key'];

// 单阶段规划信息
export interface StagePlan {
  stage: StageKey;
  tool_name: string;
  params: Record<string, unknown>;
}

// 来源（分已收录/新发现）
export interface Source {
  source_id: string;
  paper_id: number;
  paper_title: string;
  year?: number;
  doi?: string;
  score?: number;
  domain_score?: number;
  category: '已收录' | '新发现';
}

// 工作流状态
export type WorkflowStatus =
  | 'idle'
  | 'running'
  | 'interrupted'
  | 'done'
  | 'error';

export interface WorkflowState {
  status: WorkflowStatus;
  threadId: string;
  currentStage: string;
  completedStages: string[];
  plan: StagePlan[];
  answer: string;
  sources: Source[];
  error: string | null;
}

// 工作流 action
export type WorkflowAction =
  | { type: 'START_RUN'; threadId: string }
  | { type: 'STAGE_COMPLETE'; stage: string }
  | { type: 'INTERRUPT'; plan: StagePlan[] }
  | { type: 'ANSWER'; answer: string; sources: Source[] }
  | { type: 'ERROR'; error: string }
  | { type: 'DONE' }
  | { type: 'RESET' };

// 初始状态
export const initialWorkflowState: WorkflowState = {
  status: 'idle',
  threadId: '',
  currentStage: '',
  completedStages: [],
  plan: [],
  answer: '',
  sources: [],
  error: null,
};
