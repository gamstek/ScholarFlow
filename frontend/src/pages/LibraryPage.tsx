import { useState, useRef, useEffect, useCallback } from 'react';
import { usePapers } from '../hooks/usePapers';
import { api } from '../lib/api';
import { Database, FileText, CheckCircle2, Clock, RefreshCw, BookOpen, FolderOpen, Play, Loader2, AlertCircle, XCircle, Upload, Eye, Trash2, CheckSquare, Square } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { EmptyState } from '../components/EmptyState';
import type { Paper } from '../lib/api';

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  indexed:        { label: '已索引',   cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  chunked:        { label: '已切块',   cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  parsed:         { label: '已解析',   cls: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  pdf_downloaded: { label: '已下载',   cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  metadata_only:  { label: '仅元数据', cls: 'bg-gray-50 text-gray-600 border-gray-200' },
};

const STEP_LABELS: Record<string, string> = {
  downloading_pdf:  '下载 PDF',
  parsing_pdf:      '解析 PDF',
  building_chunks:  '切块',
  building_index:   '构建索引',
  done:             '完成',
  failed:           '失败',
};

const POLL_INTERVAL = 2000;       // 轮询间隔 2s
const MAX_POLL_ROUNDS = 60;       // 最大轮询次数（2 分钟）

interface LibraryPageProps {
  onSelectPaper: (paperId: number) => void;
}

export function LibraryPage({ onSelectPaper }: LibraryPageProps) {
  const { papers, stats, deletePaper } = usePapers();
  const [processingIds, setProcessingIds] = useState<Set<number>>(new Set());
  const [expandedErrors, setExpandedErrors] = useState<Set<number>>(new Set());
  const [expandedSource, setExpandedSource] = useState<Set<number>>(new Set());
  const [uploadingId, setUploadingId] = useState<number | null>(null);
  const [standaloneUploading, setStandaloneUploading] = useState(false);
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<number>>(new Set());
  const [batchProcessing, setBatchProcessing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const standaloneFileInputRef = useRef<HTMLInputElement>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef<number>(0);
  const papersRef = useRef(papers);
  papersRef.current = papers;  // 始终保持最新引用

  const paperList = papers.data?.papers || [];
  const statData = stats.data;
  const isFetching = papers.isFetching || stats.isFetching;

  const indexedCount = statData?.paper_status?.find((s) => s.status === 'indexed')?.count || 0;
  const pendingCount = statData?.paper_status?.find((s) => s.status === 'metadata_only')?.count || 0;

  // 全局单一轮询：检查 processingIds 中所有论文的状态
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return; // 已在轮询

    pollCountRef.current = 0;
    pollTimerRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      await papersRef.current.refetch();

      // 检查是否所有 processingIds 的论文都已完成或失败
      const currentPapers = papersRef.current.data?.papers || [];
      setProcessingIds((prev) => {
        if (prev.size === 0) return prev;

        const stillProcessing = new Set<number>();
        for (const id of prev) {
          const p = currentPapers.find((pp) => pp.id === id);
          if (p && p.pipeline_step && p.pipeline_step !== 'done' && p.pipeline_step !== 'failed') {
            stillProcessing.add(id);
          }
        }

        // 全部完成或超时则停止轮询
        if (stillProcessing.size === 0 || pollCountRef.current >= MAX_POLL_ROUNDS) {
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          return new Set<number>(); // 清空
        }
        return stillProcessing;
      });
    }, POLL_INTERVAL);
  }, []);  // 不再依赖 papers，通过 papersRef 读取最新值

  // 组件卸载时清理轮询
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  const handleProcess = async (paperId: number) => {
    setProcessingIds((prev) => new Set(prev).add(paperId));
    try {
      await api.processPaper(paperId);
      startPolling();
    } catch {
      setProcessingIds((prev) => {
        const next = new Set(prev);
        next.delete(paperId);
        return next;
      });
    }
  };

  const toggleError = (paperId: number) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) {
        next.delete(paperId);
      } else {
        next.add(paperId);
      }
      return next;
    });
  };

  const toggleSource = (paperId: number) => {
    setExpandedSource((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) {
        next.delete(paperId);
      } else {
        next.add(paperId);
      }
      return next;
    });
  };

  const handleDelete = async (paper: Paper) => {
    if (!confirm(`确定要删除文献「${paper.title.slice(0, 50)}${paper.title.length > 50 ? '...' : ''}」吗？\n\n此操作将同时删除本地 PDF 文件，不可恢复。`)) {
      return;
    }
    try {
      await deletePaper.mutateAsync(paper.id);
    } catch {
      // 错误由 react-query 处理
    }
  };

  const handleUploadClick = (paperId: number) => {
    setUploadingId(paperId);
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !uploadingId) return;

    try {
      await api.uploadPdf(uploadingId, file);
      setProcessingIds((prev) => new Set(prev).add(uploadingId));
      startPolling();
    } catch {
      // 错误由 refetch 后的状态显示
    } finally {
      setUploadingId(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleStandaloneUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setStandaloneUploading(true);
    try {
      const result = await api.uploadStandalonePdf(file);
      setProcessingIds((prev) => new Set(prev).add(result.paper_id));
      startPolling();
    } catch {
      // 错误由 refetch 后的状态显示
    } finally {
      setStandaloneUploading(false);
      if (standaloneFileInputRef.current) standaloneFileInputRef.current.value = '';
    }
  };

  // ---- 多选功能 ----
  const toggleSelectPaper = (paperId: number) => {
    setSelectedPaperIds((prev) => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId); else next.add(paperId);
      return next;
    });
  };

  const toggleSelectAllPapers = () => {
    const processablePapers = paperList.filter(
      (p) => p.status !== 'indexed' && !processingIds.has(p.id)
    );
    if (processablePapers.length === 0) return;

    const allSelected = processablePapers.every((p) => selectedPaperIds.has(p.id));
    if (allSelected) {
      setSelectedPaperIds(new Set());
    } else {
      setSelectedPaperIds(new Set(processablePapers.map((p) => p.id)));
    }
  };

  const handleBatchProcess = async () => {
    if (selectedPaperIds.size === 0) return;
    setBatchProcessing(true);

    try {
      // 过滤掉已索引或正在处理的
      const idsToProcess = [...selectedPaperIds].filter((id) => {
        const p = paperList.find((pp) => pp.id === id);
        return p && p.status !== 'indexed' && !processingIds.has(id);
      });

      if (idsToProcess.length === 0) {
        setSelectedPaperIds(new Set());
        return;
      }

      const batchResult = await api.processPapersBatch(idsToProcess);

      // 将触发成功的加入 processingIds 并启动轮询
      const triggeredIds = batchResult.results
        .filter((r) => r.success)
        .map((r) => r.paper_id);
      if (triggeredIds.length > 0) {
        setProcessingIds((prev) => {
          const next = new Set(prev);
          triggeredIds.forEach((id) => next.add(id));
          return next;
        });
        startPolling();
      }

      setSelectedPaperIds(new Set());

      if (batchResult.not_found > 0 || batchResult.triggered < batchResult.total) {
        // 部分失败，静默处理；状态会在 refetch 后通过 UI 体现
      }
    } catch {
      // 错误由 refetch 后的状态显示
    } finally {
      setBatchProcessing(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="文献库"
        subtitle="已入库的文献列表与处理状态"
        actions={
          <div className="flex items-center gap-2">
            {selectedPaperIds.size > 0 && (
              <button
                onClick={handleBatchProcess}
                disabled={batchProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-medium transition-colors"
              >
                {batchProcessing ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
                {batchProcessing ? '处理中...' : `一键处理 (${selectedPaperIds.size})`}
              </button>
            )}
            <button
              onClick={() => standaloneFileInputRef.current?.click()}
              disabled={standaloneUploading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-xs font-medium transition-colors"
            >
              {standaloneUploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              上传 PDF
            </button>
            <button
              onClick={() => papers.refetch()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-xs text-gray-600 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        }
      />

      {/* 统计卡片 */}
      {statData && (
        <div className="grid grid-cols-4 gap-3 mb-6">
          <StatCard icon={Database} label="文献总数" value={statData.papers_total} color="indigo" />
          <StatCard icon={FileText} label="文本块" value={statData.chunks_total} color="blue" />
          <StatCard icon={CheckCircle2} label="已索引" value={indexedCount} color="emerald" />
          <StatCard icon={Clock} label="待处理" value={pendingCount} color="amber" />
        </div>
      )}

      {/* 文献表格 */}
      {paperList.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="文献库为空"
          hint="请先使用「文献检索」搜索并入库文献"
        />
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
          <table className="w-full text-sm table-fixed">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-center px-3 py-2.5 font-medium text-gray-500 text-xs w-10">
                  <button
                    onClick={toggleSelectAllPapers}
                    className="text-gray-400 hover:text-indigo-500 transition-colors"
                    title="全选可处理文献"
                  >
                    {paperList.filter((p) => p.status !== 'indexed' && !processingIds.has(p.id)).length > 0 &&
                      paperList.filter((p) => p.status !== 'indexed' && !processingIds.has(p.id)).every((p) => selectedPaperIds.has(p.id)) ? (
                      <CheckSquare className="w-3.5 h-3.5 text-indigo-500" />
                    ) : (
                      <Square className="w-3.5 h-3.5" />
                    )}
                  </button>
                </th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs w-12">序号</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs">标题</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs w-16">年份</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs w-24">状态</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs w-20">本地路径</th>
                <th className="text-right px-4 py-2.5 font-medium text-gray-500 text-xs w-16">评分</th>
                <th className="text-center px-4 py-2.5 font-medium text-gray-500 text-xs w-36">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {paperList.map((paper, idx) => {
                const statusInfo = STATUS_CONFIG[paper.status] || STATUS_CONFIG.metadata_only;
                const hasPdf = !!paper.local_pdf_path;
                const isIndexed = paper.status === 'indexed';
                const isProcessing = processingIds.has(paper.id) || (paper.pipeline_step && paper.pipeline_step !== 'done' && paper.pipeline_step !== 'failed');
                const hasError = !!paper.pipeline_error;
                const stepLabel = paper.pipeline_step ? STEP_LABELS[paper.pipeline_step] || paper.pipeline_step : null;
                const isErrorExpanded = expandedErrors.has(paper.id);
                return (
                  <>
                    <tr key={paper.id} className="hover:bg-gray-50 transition-colors group">
                      <td className="text-center px-3 py-2.5">
                        {!isIndexed && !isProcessing && (
                          <button
                            onClick={() => toggleSelectPaper(paper.id)}
                            className="text-gray-400 hover:text-indigo-500 transition-colors"
                            title={selectedPaperIds.has(paper.id) ? '取消选择' : '选择'}
                          >
                            {selectedPaperIds.has(paper.id) ? (
                              <CheckSquare className="w-3.5 h-3.5 text-indigo-500" />
                            ) : (
                              <Square className="w-3.5 h-3.5" />
                            )}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-gray-400 text-xs tabular-nums">
                        {idx + 1}
                      </td>
                      <td className="px-4 py-2.5 max-w-md">
                        <button
                          onClick={() => onSelectPaper(paper.id)}
                          className="text-left w-full cursor-pointer"
                        >
                          <div className="truncate text-xs text-gray-800 group-hover:text-indigo-600 leading-relaxed transition-colors" title={paper.title}>
                            {paper.title}
                          </div>
                          {paper.journal && (
                            <div className="text-[10px] text-gray-400 italic mt-0.5 truncate">
                              {paper.journal}
                            </div>
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 text-xs tabular-nums">
                        {paper.year || '—'}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex flex-col gap-1">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${statusInfo.cls}`}>
                            {statusInfo.label}
                          </span>
                          {isProcessing && stepLabel && (
                            <span className="text-[10px] text-indigo-500 flex items-center gap-0.5">
                              <Loader2 className="w-2.5 h-2.5 animate-spin" />
                              {stepLabel}
                            </span>
                          )}
                          {hasError && !isProcessing && (
                            <span className="text-[10px] text-red-500 flex items-center gap-0.5">
                              <AlertCircle className="w-2.5 h-2.5" />
                              错误
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        {hasPdf ? (
                          <span className="flex items-center gap-1 text-[10px] text-gray-500">
                            <FolderOpen className="w-3 h-3 text-emerald-500 shrink-0" />
                            <span className="truncate max-w-[80px]" title={paper.local_pdf_path || ''}>
                              {paper.local_pdf_path?.split('/').pop()}
                            </span>
                          </span>
                        ) : (
                          <span className="text-[10px] text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right text-xs text-gray-500 tabular-nums">
                        {paper.domain_score?.toFixed(2) || '—'}
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        {isProcessing ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-500 mx-auto" />
                        ) : isIndexed ? (
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mx-auto" />
                        ) : (
                          <div className="flex items-center justify-center gap-1">
                            {!hasPdf && (
                              <button
                                onClick={() => handleUploadClick(paper.id)}
                                className="p-1 rounded-md text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
                                title="手动上传 PDF 文件"
                              >
                                <Upload className="w-3.5 h-3.5" />
                              </button>
                            )}
                            <button
                              onClick={() => handleProcess(paper.id)}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-indigo-50 hover:bg-indigo-100 text-indigo-600 text-[10px] font-medium transition-colors"
                              title="触发处理：下载PDF → 解析 → 切块 → 索引"
                            >
                              <Play className="w-3 h-3" />
                              {paper.status === 'metadata_only' ? '处理' : '重试'}
                            </button>
                            {hasError && (
                              <button
                                onClick={() => toggleError(paper.id)}
                                className="p-1 rounded-md text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                                title="查看错误详情"
                              >
                                <AlertCircle className="w-3 h-3" />
                              </button>
                            )}
                          </div>
                        )}
                        <div className="flex items-center justify-center gap-0.5 mt-1">
                          <button
                            onClick={() => toggleSource(paper.id)}
                            className="p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                            title="查看源数据"
                          >
                            <Eye className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => handleDelete(paper)}
                            className="p-1 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                            title="删除文献"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {hasError && isErrorExpanded && (
                      <tr className="bg-red-50/50">
                        <td colSpan={8} className="px-4 py-3">
                          <div className="flex items-start gap-2">
                            <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
                            <div className="flex-1 min-w-0">
                              <div className="text-[11px] font-medium text-red-700 mb-0.5">
                                处理错误 {stepLabel ? `（${stepLabel}）` : ''}
                              </div>
                              <div className="text-[11px] text-red-600 break-all">
                                {paper.pipeline_error}
                              </div>
                            </div>
                            <button
                              onClick={() => toggleError(paper.id)}
                              className="text-[10px] text-gray-400 hover:text-gray-600 shrink-0"
                            >
                              收起
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                    {expandedSource.has(paper.id) && (
                      <tr className="bg-gray-50/70">
                        <td colSpan={8} className="px-4 py-3">
                          <SourceDataView paper={paper} onClose={() => toggleSource(paper.id)} />
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 总数 */}
      {paperList.length > 0 && (
        <div className="text-xs text-gray-400 mt-3 text-right">
          共 {paperList.length} 条
        </div>
      )}

      {/* 隐藏的文件选择器 */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleFileSelected}
      />
      <input
        ref={standaloneFileInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleStandaloneUpload}
      />
    </div>
  );
}

function SourceDataView({ paper, onClose }: { paper: Paper; onClose: () => void }) {
  const authors = (() => {
    try {
      if (paper.authors_json) {
        const parsed = JSON.parse(paper.authors_json);
        if (Array.isArray(parsed)) return parsed.join(', ');
      }
    } catch { /* ignore */ }
    return null;
  })();

  const fields: [string, string | number | null | undefined][] = [
    ['数据库 ID', paper.id],
    ['DOI', paper.doi],
    ['PMID', paper.pmid],
    ['PMCID', paper.pmcid],
    ['作者', authors],
    ['期刊', paper.journal],
    ['年份', paper.year],
    ['来源', paper.source],
    ['URL', paper.url],
    ['PDF URL', paper.pdf_url],
    ['许可证', paper.license],
    ['开放获取', paper.is_open_access === 1 ? '是' : '否'],
    ['领域评分', paper.domain_score?.toFixed(4)],
    ['本地 PDF', paper.local_pdf_path],
    ['本地文本', paper.local_text_path],
    ['流水线步骤', paper.pipeline_step],
    ['创建时间', paper.created_at],
    ['更新时间', paper.updated_at],
  ];

  const visibleFields = fields.filter(([, value]) => value !== null && value !== undefined && value !== '');

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-600">源数据</span>
        <button
          onClick={onClose}
          className="text-[10px] text-gray-400 hover:text-gray-600"
        >
          收起
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1.5">
        {visibleFields.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <span className="text-[10px] text-gray-400 shrink-0">{label}:</span>
            <span className="text-[11px] text-gray-700 break-all" title={String(value)}>
              {String(value).length > 80 ? String(value).slice(0, 80) + '...' : String(value)}
            </span>
          </div>
        ))}
      </div>
      {paper.abstract && (
        <div className="mt-2 pt-2 border-t border-gray-200">
          <span className="text-[10px] text-gray-400">摘要:</span>
          <p className="text-[11px] text-gray-600 mt-0.5 leading-relaxed line-clamp-4">
            {paper.abstract}
          </p>
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: typeof Database;
  label: string;
  value: number;
  color: 'indigo' | 'blue' | 'emerald' | 'amber';
}) {
  const colors = {
    indigo:  'bg-indigo-50 text-indigo-600',
    blue:    'bg-blue-50 text-blue-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber:   'bg-amber-50 text-amber-600',
  };

  return (
    <div className="flex items-center gap-3 p-3.5 rounded-xl border border-gray-200 bg-white">
      <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${colors[color]}`}>
        <Icon className="w-4.5 h-4.5" strokeWidth={2} />
      </div>
      <div>
        <div className="text-lg font-semibold text-gray-900 leading-tight tabular-nums">
          {value || 0}
        </div>
        <div className="text-[11px] text-gray-400 leading-tight">{label}</div>
      </div>
    </div>
  );
}
