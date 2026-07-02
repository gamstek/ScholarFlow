import { usePapers } from '../../hooks/usePapers';

/** 文献库列表面板。 */
export function PaperList() {
  const { papers, stats } = usePapers();

  const paperList = papers.data?.papers || [];
  const statData = stats.data;

  return (
    <div className="space-y-4">
      {/* 统计摘要 */}
      {statData && (
        <div className="grid grid-cols-4 gap-3">
          <StatBox label="文献总数" value={statData.papers_total} />
          <StatBox label="Chunks" value={statData.chunks_total} />
          <StatBox
            label="已索引"
            value={
              statData.paper_status?.find(
                (s: { status: string }) => s.status === 'indexed'
              )?.count || 0
            }
          />
          <StatBox
            label="待处理"
            value={
              statData.paper_status?.find(
                (s: { status: string }) => s.status === 'metadata_only'
              )?.count || 0
            }
          />
        </div>
      )}

      {/* 文献列表 */}
      <div className="border border-gray-200 rounded-lg">
        {paperList.length === 0 ? (
          <p className="text-gray-400 text-center py-8 text-sm">暂无文献</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left p-3 font-medium text-gray-600">ID</th>
                <th className="text-left p-3 font-medium text-gray-600">
                  标题
                </th>
                <th className="text-left p-3 font-medium text-gray-600">
                  年份
                </th>
                <th className="text-left p-3 font-medium text-gray-600">
                  状态
                </th>
                <th className="text-left p-3 font-medium text-gray-600">
                  评分
                </th>
              </tr>
            </thead>
            <tbody>
              {paperList.map((paper: { id: number; title: string; year: number; status: string; domain_score: number }) => (
                <tr key={paper.id} className="border-b hover:bg-gray-50">
                  <td className="p-3 text-gray-500">{paper.id}</td>
                  <td className="p-3 text-gray-800 max-w-md truncate">
                    {paper.title}
                  </td>
                  <td className="p-3 text-gray-500">{paper.year}</td>
                  <td className="p-3">
                    <StatusBadge status={paper.status} />
                  </td>
                  <td className="p-3 text-gray-500">
                    {paper.domain_score?.toFixed(2)}
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

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <div className="text-2xl font-bold text-gray-800">{value || 0}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    indexed: 'bg-emerald-100 text-emerald-700',
    chunked: 'bg-blue-100 text-blue-700',
    parsed: 'bg-indigo-100 text-indigo-700',
    pdf_downloaded: 'bg-amber-100 text-amber-700',
    metadata_only: 'bg-gray-100 text-gray-600',
  };

  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}
    >
      {status}
    </span>
  );
}
