import type { Source } from '../../types/workflow';
import { BookMarked, Sparkles } from 'lucide-react';

interface SourceCardProps {
  source: Source;
}

/** 来源卡片。绿色左边框 = 已收录，蓝色左边框 = 新发现。 */
export function SourceCard({ source }: SourceCardProps) {
  const isExisting = source.category === '已收录';
  const Icon = isExisting ? BookMarked : Sparkles;

  return (
    <div
      className={`border-l-[3px] rounded-lg p-2.5 text-xs transition-shadow hover:shadow-sm ${
        isExisting
          ? 'border-emerald-500 bg-emerald-50/50'
          : 'border-blue-500 bg-blue-50/50'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-1.5 flex-1 min-w-0">
          <Icon
            className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
              isExisting ? 'text-emerald-600' : 'text-blue-600'
            }`}
            strokeWidth={1.8}
          />
          <h4 className="font-medium text-slate-700 text-xs leading-snug">
            [{source.source_id}] {source.paper_title || 'N/A'}
          </h4>
        </div>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ${
            isExisting
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-blue-100 text-blue-700'
          }`}
        >
          {source.category}
        </span>
      </div>
      <div className="text-slate-400 mt-1 text-[10px] flex flex-wrap gap-x-3 ml-5">
        {source.year && <span>年份: {source.year}</span>}
        {source.doi && <span>DOI: {source.doi}</span>}
        {source.score !== undefined && (
          <span>评分: {source.score.toFixed(2)}</span>
        )}
        {source.domain_score !== undefined && (
          <span>领域: {source.domain_score.toFixed(2)}</span>
        )}
      </div>
    </div>
  );
}
