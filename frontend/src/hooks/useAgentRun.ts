import { useReducer, useCallback } from 'react';
import { workflowReducer } from '../state/workflowReducer';
import {
  type WorkflowState,
  type WorkflowAction,
  initialWorkflowState,
} from '../types/workflow';

/**
 * Agent 任务 hook。
 * 封装 /agent/run 和 /agent/resume 的 SSE 流式调用。
 */
export function useAgentRun() {
  const [state, dispatch] = useReducer(
    workflowReducer,
    initialWorkflowState
  );

  const run = useCallback(async (intent: string, question: string) => {
    dispatch({ type: 'RESET' });

    await streamSSE('/agent/run', {
      user_intent: intent,
      user_question: question,
    }, dispatch);
  }, []);

  const resume = useCallback(async (threadId: string, approved: boolean) => {
    dispatch({ type: 'START_RUN', threadId });

    await streamSSE('/agent/resume', {
      thread_id: threadId,
      approved,
    }, dispatch);
  }, []);

  const reset = useCallback(() => dispatch({ type: 'RESET' }), []);

  return { state, run, resume, reset };
}

async function streamSSE(
  url: string,
  body: Record<string, unknown>,
  dispatch: React.Dispatch<WorkflowAction>
) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (!res.body) throw new Error('No response body');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ') && eventType) {
          try {
            const data = JSON.parse(line.slice(6));
            handleSSEEvent(eventType, data, dispatch);
          } catch {
            // ignore malformed lines
          }
          eventType = '';
        }
      }
    }
  } catch (err) {
    dispatch({ type: 'ERROR', error: String(err) });
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function handleSSEEvent(
  eventType: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any,
  dispatch: React.Dispatch<WorkflowAction>
) {
  switch (eventType) {
    case 'thread':
      dispatch({ type: 'START_RUN', threadId: data.thread_id || '' });
      break;

    case 'node_complete':
      dispatch({ type: 'STAGE_COMPLETE', stage: data.stage || data.node || '' });
      break;

    case 'interrupt':
      dispatch({ type: 'INTERRUPT', plan: data.plan || [] });
      break;

    case 'answer':
      dispatch({
        type: 'ANSWER',
        answer: data.answer || '',
        sources: data.sources || [],
      });
      break;

    case 'error':
      dispatch({ type: 'ERROR', error: data.error || '未知错误' });
      break;

    case 'done':
      dispatch({ type: 'DONE' });
      break;
  }
}
