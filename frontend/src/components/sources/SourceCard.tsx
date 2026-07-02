import type { Source } from '../../types/workflow';

interface SourceCardProps {
  source: Source;
}

/** 来源卡片。绿色左边框 = 已收录，蓝色左边框 = 新发现。 */
export function SourceCard({ source }: SourceCardProps) {
  const isExisting = source.category === '已收录';

  return (
    <div
      className={`border-l-4 rounded-lg p-3 text-sm ${
        isExisting
          ? 'border-emerald-500 bg-emerald-50'
          : 'border-blue-500 bg-blue-50'
      }`}
    >
      <div className="flex items-start justify-between">
        <h4 className="font-semibold text-gray-800 text-sm leading-snug flex-1">
          [{source.source_id}] {source.paper_title || 'N/A'}
        </h4>
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ml-2 shrink-0 ${
            isExisting
              ? 'bg-emerald-200 text-emerald-800'
              : 'bg-blue-200 text-blue-800'
          }`}
        >
          {source.category}
        </span>
      </div>
      <div className="text-gray-500 mt-1 text-xs space-x-3">
        {source.year && <span>年份: {source.year}</span>}
        {source.doi && <span>DOI: {source.doi}</span>}
        {source.score !== undefined && (
          <span>评分: {source.score.toFixed(2)}</span>
        )}
        {source.domain_score !== undefined && (
          <span>领域评分: {source.domain_score.toFixed(2)}</span>
        )}
      </div>
    </div>
  );
}
