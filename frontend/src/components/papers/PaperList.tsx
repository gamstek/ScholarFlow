import { usePapers } from '../../hooks/usePapers';
import { FileText, Database, CheckCircle2, Clock } from 'lucide-react';

/** 文献库列表面板。 */
export function PaperList() {
  const { papers, stats } = usePapers();

  const paperList = papers.data?.papers || [];
  const statData = stats.data;

  return (
    <div className="space-y-3">
      {/* 统计摘要 */}
      {statData && (
        <div className="grid grid-cols-2 gap-2">
          <MiniStat
            label="文献总数"
            value={statData.papers_total}
            icon={Database}
            color="text-indigo-600 bg-indigo-50"
          />
          <MiniStat
            label="文本块"
            value={statData.chunks_total}
            icon={FileText}
            color="text-blue-600 bg-blue-50"
          />
          <MiniStat
            label="已索引"
            value={
              statData.paper_status?.find(
                (s: { status: string }) => s.status === 'indexed'
              )?.count || 0
            }
            icon={CheckCircle2}
            color="text-emerald-600 bg-emerald-50"
          />
          <MiniStat
            label="待处理"
            value={
              statData.paper_status?.find(
                (s: { status: string }) => s.status === 'metadata_only'
              )?.count || 0
            }
            icon={Clock}
            color="text-amber-600 bg-amber-50"
          />
        </div>
      )}

      {/* 文献列表 */}
      <div className="border border-slate-200 rounded-xl overflow-hidden">
        {paperList.length === 0 ? (
          <div className="text-center py-10">
            <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-slate-400 text-sm">暂无文献</p>
            <p className="text-slate-300 text-xs mt-1">请在检索发现页采集文献</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left p-2.5 font-medium text-slate-500 text-xs">ID</th>
                <th className="text-left p-2.5 font-medium text-slate-500 text-xs">标题</th>
                <th className="text-left p-2.5 font-medium text-slate-500 text-xs">年份</th>
                <th className="text-left p-2.5 font-medium text-slate-500 text-xs">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {paperList.map((paper: { id: number; title: string; year: number; status: string; domain_score: number }) => (
                <tr key={paper.id} className="hover:bg-slate-50 transition-colors">
                  <td className="p-2.5 text-slate-400 text-xs tabular-nums">
                    {paper.id}
                  </td>
                  <td className="p-2.5 text-slate-700 max-w-xs truncate text-xs">
                    {paper.title}
                  </td>
                  <td className="p-2.5 text-slate-400 text-xs tabular-nums">
                    {paper.year}
                  </td>
                  <td className="p-2.5">
                    <StatusBadge status={paper.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/** 迷你统计卡片。 */
function MiniStat({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: number;
  icon: typeof FileText;
  color: string;
}) {
  return (
    <div className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-50 border border-slate-100">
      <div className={`w-7 h-7 rounded-md flex items-center justify-center ${color}`}>
        <Icon className="w-4 h-4" strokeWidth={1.8} />
      </div>
      <div>
        <div className="text-sm font-bold text-slate-700 leading-tight">{value || 0}</div>
        <div className="text-[10px] text-slate-400 leading-tight">{label}</div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    indexed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    chunked: 'bg-blue-50 text-blue-700 border-blue-200',
    parsed: 'bg-indigo-50 text-indigo-700 border-indigo-200',
    pdf_downloaded: 'bg-amber-50 text-amber-700 border-amber-200',
    metadata_only: 'bg-slate-50 text-slate-600 border-slate-200',
  };

  return (
    <span
      className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${colors[status] || 'bg-slate-50 text-slate-600 border-slate-200'}`}
    >
      {status}
    </span>
  );
}
