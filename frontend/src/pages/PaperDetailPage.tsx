import { useState, useEffect } from 'react';
import {
  ArrowLeft, FileText, BookOpen, Loader2, ExternalLink,
  FolderOpen, Eye,
} from 'lucide-react';
import { api, type PaperDetail, type PaperText } from '../lib/api';

interface PaperDetailPageProps {
  paperId: number;
  onBack: () => void;
}

type ViewMode = 'text' | 'pdf';

export function PaperDetailPage({ paperId, onBack }: PaperDetailPageProps) {
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [textData, setTextData] = useState<PaperText | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('text');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');

    Promise.all([
      api.getPaper(paperId),
      api.getPaperText(paperId).catch(() => null),
    ])
      .then(([paperData, text]) => {
        if (cancelled) return;
        if (!paperData) {
          setError('文献不存在或加载失败');
          return;
        }
        setPaper(paperData);
        setTextData(text);
        // 如果没有文本但有 PDF，默认显示 PDF
        if (!text?.full_text && paperData.local_pdf_path) {
          setViewMode('pdf');
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [paperId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    );
  }

  if (error || !paper) {
    return (
      <div className="animate-fade-in">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-4">
          <ArrowLeft className="w-4 h-4" /> 返回文献库
        </button>
        <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {error || '文献加载失败'}
        </div>
      </div>
    );
  }

  const hasPdf = !!paper.local_pdf_path;
  const hasText = !!(textData?.full_text);

  return (
    <div className="animate-fade-in">
      {/* 顶栏 */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> 返回文献库
        </button>
        <div className="flex items-center gap-2">
          {/* 视图切换 */}
          {hasPdf && hasText && (
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              <button
                onClick={() => setViewMode('text')}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors ${
                  viewMode === 'text'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white text-gray-500 hover:bg-gray-50'
                }`}
              >
                <Eye className="w-3 h-3" />
                全文
              </button>
              <button
                onClick={() => setViewMode('pdf')}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors ${
                  viewMode === 'pdf'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white text-gray-500 hover:bg-gray-50'
                }`}
              >
                <FileText className="w-3 h-3" />
                PDF
              </button>
            </div>
          )}
          {paper.doi && (
            <a
              href={`https://doi.org/${paper.doi}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-xs text-gray-500 transition-colors"
            >
              DOI <ExternalLink className="w-3 h-3" />
            </a>
          )}
          {hasPdf && (
            <a
              href={`/papers/${paperId}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              新窗口打开 PDF
            </a>
          )}
        </div>
      </div>

      {/* 标题 */}
      <h1 className="text-xl font-semibold text-gray-900 leading-snug mb-3">
        {paper.title}
      </h1>

      {/* 元信息 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mb-4">
        {paper.year && <span>{paper.year}</span>}
        {paper.journal && <span className="italic">{paper.journal}</span>}
        {paper.doi && <span className="text-gray-400 font-mono">{paper.doi}</span>}
      </div>

      {/* 本地存储路径 */}
      {(paper.local_pdf_path || paper.local_text_path) && (
        <div className="rounded-lg bg-gray-50 border border-gray-200 p-3 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <FolderOpen className="w-3.5 h-3.5 text-gray-400" />
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              本地存储位置
            </span>
          </div>
          <div className="space-y-1 text-xs text-gray-500 font-mono">
            {paper.local_pdf_path && (
              <div>
                <span className="text-gray-400">PDF: </span>
                <span>{paper.local_pdf_path}</span>
              </div>
            )}
            {paper.local_text_path && (
              <div>
                <span className="text-gray-400">文本: </span>
                <span>{paper.local_text_path}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 全文 / PDF 查看器 */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        {viewMode === 'pdf' && hasPdf ? (
          <div className="h-[800px]">
            <iframe
              src={`/papers/${paperId}/pdf`}
              className="w-full h-full border-0"
              title="PDF Viewer"
            />
          </div>
        ) : (
          <div className="p-6">
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-gray-100">
              <BookOpen className="w-4 h-4 text-indigo-500" />
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                全文 {textData ? `(${textData.total_chunks} chunks)` : ''}
              </span>
            </div>

            {hasText ? (
              <div className="text-sm text-gray-700 leading-[1.85] whitespace-pre-wrap font-serif">
                {textData!.full_text}
              </div>
            ) : (
              <div className="text-sm text-gray-400 text-center py-8">
                <FileText className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                <p>该文献尚未解析全文</p>
                <p className="text-xs mt-1">
                  状态: {paper.status}
                  {hasPdf
                    ? '（PDF 已下载但未解析，请通过流水线处理）'
                    : '（请先下载 PDF）'}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
