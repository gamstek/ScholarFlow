import { ExternalLink } from 'lucide-react';
import type { Source } from '../lib/api';

/**
 * 引用来源卡片 — 用于 AskPage 和 ReviewPage。
 */
export function SourceCard({ source }: { source: Source }) {
  const doiUrl = source.doi ? `https://doi.org/${source.doi}` : null;

  return (
    <div className="flex gap-3 p-3 rounded-lg border border-gray-200 bg-white hover:border-indigo-300 hover:shadow-sm transition-all duration-150">
      {/* 编号 */}
      <div className="shrink-0 w-7 h-7 rounded-md bg-indigo-50 text-indigo-600 text-xs font-semibold flex items-center justify-center">
        {source.source_id}
      </div>

      {/* 内容 */}
      <div className="flex-1 min-w-0">
        <div className="text-sm text-gray-800 leading-snug line-clamp-2">
          {source.paper_title || 'N/A'}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-[11px] text-gray-400">
          {source.year && <span>{source.year}</span>}
          {source.journal && (
            <span className="italic truncate max-w-[200px]">{source.journal}</span>
          )}
          {source.section_title && (
            <span className="text-gray-300">§ {source.section_title}</span>
          )}
          {doiUrl && (
            <a
              href={doiUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-0.5 text-indigo-500 hover:text-indigo-600"
            >
              DOI <ExternalLink className="w-2.5 h-2.5" />
            </a>
          )}
        </div>
      </div>

      {/* 评分 */}
      <div className="shrink-0 text-right">
        <div className="text-[10px] text-gray-400 leading-tight">相似度</div>
        <div className="text-xs font-medium text-gray-600 tabular-nums">
          {source.score.toFixed(2)}
        </div>
      </div>
    </div>
  );
}
