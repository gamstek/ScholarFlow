import { useState, useMemo, useEffect } from 'react';
import {
  Search, Loader2, AlertCircle, Layers,
  BookOpen, Plus, ExternalLink, Sparkles, Tag, X,
} from 'lucide-react';
import { api, type SearchResult, type SearchHit } from '../lib/api';
import { PageHeader } from '../components/PageHeader';

// 数据源配置
const SOURCES = [
  { value: 'europe_pmc',       label: 'Europe PMC',      desc: '通用生物医学' },
  { value: 'semantic_scholar', label: 'Semantic Scholar', desc: '通用学术搜索' },
  { value: 'arxiv',            label: 'arXiv',           desc: '预印本' },
  { value: 'nature',           label: 'Nature',          desc: 'Nature 系列期刊' },
  { value: 'science',          label: 'Science',         desc: 'Science 系列期刊' },
  { value: 'cell',             label: 'Cell',            desc: 'Cell Press 期刊' },
] as const;

type SearchMode = 'keyword' | 'natural';

interface SearchPageProps {
  onSelectPaper?: (paperId: number) => void;
}

export function SearchPage({ onSelectPaper }: SearchPageProps) {
  const [mode, setMode] = useState<SearchMode>('natural');
  const [query, setQuery] = useState('');
  const [naturalQuery, setNaturalQuery] = useState('');
  const [sources, setSources] = useState<string[]>(['europe_pmc']);
  const [maxResults, setMaxResults] = useState(20);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState('');
  const [importingIds, setImportingIds] = useState<Set<number>>(new Set());
  const [importedIds, setImportedIds] = useState<Set<number>>(new Set());
  const [sortBy, setSortBy] = useState<string>('relevance');
  const [sortOrder, setSortOrder] = useState<string>('desc');
  const [searchProgress, setSearchProgress] = useState<{
    current: number; total: number;
    sources: Record<string, { done: boolean; count: number; error?: string }>;
  } | null>(null);
  const [detailHit, setDetailHit] = useState<SearchHit | null>(null);
  const [translating, setTranslating] = useState(false);
  const [translatedAbstract, setTranslatedAbstract] = useState<string | null>(null);

  // ---- localStorage 持久化：关闭网页后重新打开恢复检索结果 ----
  const STORAGE_KEY = 'scholarflow_search_state';

  // 恢复上次检索状态
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const state = JSON.parse(saved);
        if (state.mode) setMode(state.mode);
        if (state.query) setQuery(state.query);
        if (state.naturalQuery) setNaturalQuery(state.naturalQuery);
        if (state.sources?.length) setSources(state.sources);
        if (state.maxResults) setMaxResults(state.maxResults);
        if (state.sortBy) setSortBy(state.sortBy);
        if (state.sortOrder) setSortOrder(state.sortOrder);
        if (state.result) setResult(state.result);
      }
    } catch {
      // 解析失败则忽略
    }
  }, []);

  // 保存检索状态（result 变化时）
  useEffect(() => {
    if (!result) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        mode,
        query,
        naturalQuery,
        sources,
        maxResults,
        sortBy,
        sortOrder,
        result,
      }));
    } catch {
      // 存储满则忽略
    }
  }, [result, mode, query, naturalQuery, sources, maxResults, sortBy, sortOrder]);

  // 点击卡片 → 显示元数据模态框
  const handleCardClick = (hit: SearchHit) => {
    setDetailHit(hit);
    setTranslatedAbstract(null);

    // 检测是否英文摘要，是则自动翻译
    if (hit.abstract) {
      const hasCjk = /[\u4e00-\u9fff]/.test(hit.abstract);
      if (!hasCjk) {
        setTranslating(true);
        api.translate(hit.abstract)
          .then((res) => setTranslatedAbstract(res.translated))
          .catch(() => setTranslatedAbstract(null))
          .finally(() => setTranslating(false));
      }
    }
  };

  const toggleSource = (value: string) => {
    setSources((prev) =>
      prev.includes(value)
        ? prev.filter((s) => s !== value)
        : [...prev, value]
    );
  };

  const handleSearch = async () => {
    const hasInput = mode === 'natural' ? naturalQuery.trim() : query.trim();
    if (!hasInput || sources.length === 0) return;

    setLoading(true);
    setError('');
    setResult(null);
    // 初始化进度：所有源标记为等待中
    const initialSources: Record<string, { done: boolean; count: number }> = {};
    sources.forEach((s) => { initialSources[s] = { done: false, count: 0 }; });
    setSearchProgress({ current: 0, total: sources.length * maxResults, sources: initialSources });

    try {
      const params =
        mode === 'natural'
          ? { natural_query: naturalQuery, sources, max_results: maxResults, sort_by: sortBy, sort_order: sortOrder }
          : { query, sources, max_results: maxResults, sort_by: sortBy, sort_order: sortOrder };

      const data = await api.searchStream(params, (current, total, source, sourceCount) => {
        setSearchProgress((prev) => ({
          current,
          total,
          sources: {
            ...(prev?.sources ?? {}),
            [source]: { done: true, count: sourceCount },
          },
        }));
      });
      setResult(data);
      setSearchProgress(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSearchProgress(null);
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async (hit: SearchHit) => {
    if (importingIds.has(hit.doi as unknown as number)) return;

    // 用 title 做临时 key
    const key = hit.title;
    setImportingIds((prev) => new Set(prev).add(key as unknown as number));

    try {
      const importResult = await api.importPaper({
        title: hit.title,
        abstract: hit.abstract,
        authors: hit.authors,
        year: hit.year,
        journal: hit.journal,
        doi: hit.doi,
        pmid: hit.pmid,
        pmcid: hit.pmcid,
        source: hit.source,
        url: hit.url,
        pdf_url: hit.pdf_url,
        license: hit.license,
        is_open_access: hit.is_open_access,
        domain_score: hit.domain_score,
      });

      // 触发后台流水线
      await api.processPaper(importResult.paper_id);

      setImportedIds((prev) => new Set(prev).add(key as unknown as number));

      // 更新结果中的 in_library 状态
      if (result) {
        setResult({
          ...result,
          results: result.results.map((r) =>
            r.title === hit.title
              ? { ...r, in_library: true, paper_id: importResult.paper_id }
              : r
          ),
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(key as unknown as number);
        return next;
      });
    }
  };

  const selectedLabels = SOURCES
    .filter((s) => sources.includes(s.value))
    .map((s) => s.label);

  const hasInput = mode === 'natural' ? naturalQuery.trim() : query.trim();

  // 客户端排序
  const sortedResults = useMemo(() => {
    if (!result) return [];
    const list = [...result.results];
    const desc = sortOrder === 'desc';
    if (sortBy === 'year') {
      list.sort((a, b) => {
        const ay = a.year ?? 0; const by = b.year ?? 0;
        const aHas = a.year != null; const bHas = b.year != null;
        if (aHas !== bHas) return aHas ? -1 : 1;
        return desc ? by - ay : ay - by;
      });
    } else {
      list.sort((a, b) => desc ? b.domain_score - a.domain_score : a.domain_score - b.domain_score);
    }
    return list;
  }, [result, sortBy, sortOrder]);

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="文献检索"
        subtitle={
          sources.length === 0
            ? '请至少选择一个数据源'
            : `从 ${selectedLabels.join(' + ')} 搜索文献，自动去重排序`
        }
      />

      {/* 模式切换 */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setMode('natural')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border flex items-center gap-1.5 ${
            mode === 'natural'
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" />
          自然语言
        </button>
        <button
          onClick={() => setMode('keyword')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border flex items-center gap-1.5 ${
            mode === 'keyword'
              ? 'bg-indigo-600 text-white border-indigo-600'
              : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'
          }`}
        >
          <Tag className="w-3.5 h-3.5" />
          关键词
        </button>
      </div>

      {/* 数据源选择 */}
      <div className="flex flex-wrap gap-2 mb-4">
        {SOURCES.map((s) => {
          const active = sources.includes(s.value);
          return (
            <button
              key={s.value}
              onClick={() => toggleSource(s.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
                active
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
              }`}
            >
              {s.label}
              <span className={`ml-1.5 text-[10px] ${active ? 'text-indigo-200' : 'text-gray-400'}`}>
                {s.desc}
              </span>
            </button>
          );
        })}
      </div>

      {/* 搜索栏 */}
      <div className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={mode === 'natural' ? naturalQuery : query}
            onChange={(e) =>
              mode === 'natural'
                ? setNaturalQuery(e.target.value)
                : setQuery(e.target.value)
            }
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder={
              mode === 'natural'
                ? '用自然语言描述你想找的文献，如：我想找母乳低聚糖结构鉴定的文章'
                : '输入检索关键词，如 human milk oligosaccharides LC-MS/MS'
            }
            className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
          />
        </div>
        <select
          value={maxResults}
          onChange={(e) => setMaxResults(Number(e.target.value))}
          className="px-3 py-2.5 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-indigo-500"
        >
          {[10, 20, 50, 100].map((n) => (
            <option key={n} value={n}>{n} 篇/源</option>
          ))}
        </select>
        <button
          onClick={handleSearch}
          disabled={loading || !hasInput || sources.length === 0}
          className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium flex items-center gap-2 transition-colors"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? '检索中...' : '检索'}
        </button>
      </div>

      {/* 错误 */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm mb-4">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* 检索进度条（独立于结果块，检索开始即显示） */}
      {searchProgress && (
        <div className="mb-4 animate-fade-in p-4 rounded-xl border border-indigo-100 bg-indigo-50/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-indigo-700">
              检索进度：{searchProgress.current} / {searchProgress.total}
            </span>
            <span className="text-xs text-indigo-400">
              {Math.round((searchProgress.current / searchProgress.total) * 100)}%
            </span>
          </div>
          <div className="w-full h-2 bg-indigo-100 rounded-full overflow-hidden mb-3">
            <div
              className="h-full bg-indigo-500 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${(searchProgress.current / searchProgress.total) * 100}%` }}
            />
          </div>
          {/* 各数据源状态 */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(searchProgress.sources).map(([src, info]) => (
              <span
                key={src}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
                  info.done
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-amber-100 text-amber-700'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${info.done ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'}`} />
                {src}
                {info.done && <span className="text-emerald-500">({info.count}篇)</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 排序控件（检索完成后显示） */}
      {result && !loading && (
        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs text-gray-500">排序：</span>
          {[
            { value: 'relevance', label: '相关度' },
            { value: 'year', label: '发表时间' },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                if (sortBy === opt.value) {
                  setSortOrder((o) => (o === 'desc' ? 'asc' : 'desc'));
                } else {
                  setSortBy(opt.value);
                  setSortOrder('desc');
                }
              }}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors border ${
                sortBy === opt.value
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'
              }`}
            >
              {opt.label}
              {sortBy === opt.value && (
                <span className="ml-1">{sortOrder === 'desc' ? '↓' : '↑'}</span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* 结果 */}
      {result && (
        <div className="animate-fade-in">
          {/* LLM 提取的关键词 */}
          {result.keywords && result.keywords.length > 0 && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 mb-4">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles className="w-4 h-4 text-indigo-500" />
                <span className="text-xs font-medium text-indigo-700 uppercase tracking-wide">
                  LLM 提取的关键词
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {result.keywords.map((kw, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded-md bg-white text-indigo-600 text-xs border border-indigo-100"
                  >
                    {kw}
                  </span>
                ))}
                {result.domain && (
                  <span className="px-2 py-0.5 rounded-md bg-indigo-600 text-white text-xs">
                    {result.domain}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* 统计卡片 */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            <StatBox label="检索到" value={result.retrieved_count} color="text-gray-900" />
            <StatBox label="去重后" value={result.deduplicated_count} color="text-purple-600" icon={<Layers className="w-3.5 h-3.5" />} />
            <StatBox label="展示结果" value={result.results.length} color="text-indigo-600" />
          </div>

          {/* 错误信息 */}
          {result.errors.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="w-4 h-4 text-amber-500" />
                <span className="text-xs font-medium text-amber-700 uppercase tracking-wide">
                  错误信息
                </span>
              </div>
              <div className="space-y-1">
                {result.errors.map((err, i) => (
                  <div key={i} className="text-xs text-amber-600">{err}</div>
                ))}
              </div>
            </div>
          )}

          {/* 论文列表 */}
          {sortedResults.length > 0 && (
            <div className="space-y-3">
              {sortedResults.map((hit, i) => (
                <PaperCard
                  key={i}
                  hit={hit}
                  rank={i + 1}
                  importing={importingIds.has(hit.title as unknown as number)}
                  imported={importedIds.has(hit.title as unknown as number) || hit.in_library}
                  onImport={() => handleImport(hit)}
                  onView={() => hit.paper_id && onSelectPaper?.(hit.paper_id)}
                  onClick={() => handleCardClick(hit)}
                />
              ))}
            </div>
          )}

          {sortedResults.length === 0 && !loading && (
            <div className="text-center py-12 text-gray-400 text-sm">
              没有检索到相关文献。
            </div>
          )}
        </div>
      )}

      {/* 元数据模态框 */}
      {detailHit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
          onClick={() => { setDetailHit(null); setTranslatedAbstract(null); }}>
          <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between rounded-t-2xl">
              <h3 className="text-sm font-semibold text-gray-900 pr-4">文献详情</h3>
              <button onClick={() => { setDetailHit(null); setTranslatedAbstract(null); }}
                className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              <h4 className="text-base font-semibold text-gray-900 leading-snug">{detailHit.title}</h4>
              <div className="grid grid-cols-2 gap-3 text-xs">
                {detailHit.authors && detailHit.authors.length > 0 && (
                  <div className="col-span-2"><span className="text-gray-400">作者：</span><span className="text-gray-700">{detailHit.authors.join(', ')}</span></div>
                )}
                {detailHit.year && <div><span className="text-gray-400">年份：</span><span className="text-gray-700">{detailHit.year}</span></div>}
                {detailHit.journal && <div><span className="text-gray-400">期刊：</span><span className="text-gray-700 italic">{detailHit.journal}</span></div>}
                {detailHit.doi && <div><span className="text-gray-400">DOI：</span><a href={`https://doi.org/${detailHit.doi}`} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:text-blue-700 font-mono">{detailHit.doi}</a></div>}
                <div><span className="text-gray-400">来源：</span><span className="text-gray-700">{detailHit.source}</span></div>
                {detailHit.is_open_access === 1 && <div><span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-50 text-emerald-600 border border-emerald-100">开放获取</span></div>}
              </div>
              {detailHit.abstract && (
                <div>
                  <h5 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">摘要（原文）</h5>
                  <p className="text-sm text-gray-700 leading-relaxed">{detailHit.abstract}</p>
                </div>
              )}
              {detailHit.abstract && (
                <div>
                  <h5 className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">中文翻译{translating && <Loader2 className="w-3 h-3 animate-spin inline ml-2" />}</h5>
                  {translating ? <p className="text-sm text-gray-400 italic">翻译中...</p>
                  : translatedAbstract ? <p className="text-sm text-gray-700 leading-relaxed">{translatedAbstract}</p>
                  : <p className="text-sm text-gray-400 italic">已为中文，无需翻译</p>}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// 论文卡片
// ============================================================

function PaperCard({
  hit,
  rank,
  importing,
  imported,
  onImport,
  onView,
  onClick,
}: {
  hit: SearchHit;
  rank: number;
  importing: boolean;
  imported: boolean;
  onImport: () => void;
  onView: () => void;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="rounded-xl border border-gray-200 bg-white p-4 hover:shadow-sm hover:border-indigo-200 transition-all cursor-pointer">
      <div className="flex items-start gap-3">
        {/* 排名 */}
        <span className="shrink-0 text-xs font-mono text-gray-400 tabular-nums mt-0.5">
          {rank}.
        </span>

        <div className="flex-1 min-w-0">
          {/* 标题 */}
          <div className="flex items-start gap-2 mb-1">
            <h3 className="text-sm font-medium text-gray-900 leading-snug flex-1">
              {hit.title}
            </h3>
            {hit.is_open_access === 1 && (
              <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-emerald-50 text-emerald-600 border border-emerald-100">
                OA
              </span>
            )}
          </div>

          {/* 元信息 */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-500 mb-2">
            {hit.year && <span>{hit.year}</span>}
            {hit.journal && <span className="truncate max-w-[200px]">{hit.journal}</span>}
            {hit.source && <span className="text-gray-400">{hit.source}</span>}
            <span className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${hit.in_library ? 'bg-emerald-500' : 'bg-gray-300'}`} />
              {hit.in_library ? '已在库中' : '未入库'}
            </span>
          </div>

          {/* 摘要 */}
          {hit.abstract && (
            <p className="text-xs text-gray-500 line-clamp-2 mb-2">
              {hit.abstract}
            </p>
          )}

          {/* 底部操作栏 */}
          <div className="flex items-center gap-2 mt-2">
            {/* 评分 */}
            <span className="text-[11px] text-gray-400">
              评分: <span className="font-mono text-indigo-600">{hit.domain_score.toFixed(2)}</span>
            </span>

            {/* DOI 链接 */}
            {hit.doi && (
              <a
                href={`https://doi.org/${hit.doi}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-1 text-[11px] text-blue-500 hover:text-blue-700"
              >
                <ExternalLink className="w-3 h-3" />
                {hit.doi}
              </a>
            )}

            <div className="flex-1" />

            {/* 操作按钮 */}
            {imported ? (
              <button
                onClick={(e) => { e.stopPropagation(); onView(); }}
                disabled={!hit.paper_id}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-100 hover:bg-emerald-100 disabled:opacity-40 transition-colors"
              >
                <BookOpen className="w-3 h-3" />
                查看论文
              </button>
            ) : (
              <button
                onClick={(e) => { e.stopPropagation(); onImport(); }}
                disabled={importing}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors"
              >
                {importing ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Plus className="w-3 h-3" />
                )}
                {importing ? '入库中...' : '入库'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatBox({
  label,
  value,
  color,
  icon,
}: {
  label: string;
  value: number;
  color: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="p-3 rounded-xl border border-gray-200 bg-white">
      <div className={`text-2xl font-semibold tabular-nums ${color} flex items-center gap-1`}>
        {icon}
        {value}
      </div>
      <div className="text-[11px] text-gray-400 mt-0.5">{label}</div>
    </div>
  );
}
