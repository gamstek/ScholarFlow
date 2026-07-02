import type { WorkflowState, WorkflowAction } from '../types/workflow';

export function workflowReducer(
  state: WorkflowState,
  action: WorkflowAction
): WorkflowState {
  switch (action.type) {
    case 'START_RUN':
      return {
        ...state,
        status: 'running',
        threadId: action.threadId,
        currentStage: 'planning',
        completedStages: [],
        plan: [],
        answer: '',
        sources: [],
        error: null,
      };

    case 'STAGE_COMPLETE': {
      const stage = action.stage.replace('node_', '');
      const completed = state.completedStages.includes(stage)
        ? state.completedStages
        : [...state.completedStages, stage];
      return {
        ...state,
        currentStage: stage,
        completedStages: completed,
      };
    }

    case 'INTERRUPT':
      return {
        ...state,
        status: 'interrupted',
        plan: action.plan,
        currentStage: 'interrupted',
      };

    case 'ANSWER':
      return {
        ...state,
        answer: action.answer,
        sources: action.sources,
        currentStage: 'qa',
        completedStages: [...state.completedStages, 'qa'],
      };

    case 'ERROR':
      return {
        ...state,
        status: 'error',
        error: action.error,
      };

    case 'DONE':
      return {
        ...state,
        status: 'done',
        completedStages: [...state.completedStages, 'report'],
      };

    case 'RESET':
      return {
        status: 'idle',
        threadId: '',
        currentStage: '',
        completedStages: [],
        plan: [],
        answer: '',
        sources: [],
        error: null,
      };

    default:
      return state;
  }
}
