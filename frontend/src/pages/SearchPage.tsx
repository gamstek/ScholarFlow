import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import {
  Search, Loader2, AlertCircle, Layers,
  BookOpen, Plus, ExternalLink, Sparkles, Tag, X, User, CheckSquare, Square, Download,
} from 'lucide-react';
import { api, type SearchResult, type SearchHit } from '../lib/api';
import { PageHeader } from '../components/PageHeader';

// 数据源配置（聚合数据库 + 细分期刊源）
const SOURCES = [
  { value: 'europe_pmc',       label: 'Europe PMC',      desc: '生物医学',        journal: true },
  { value: 'pubmed',           label: 'PubMed',          desc: 'MEDLINE',          journal: true },
  { value: 'semantic_scholar', label: 'Semantic Scholar', desc: '通用学术',        journal: false },
  { value: 'openalex',         label: 'OpenAlex',        desc: '250M+ 作品',       journal: true },
  { value: 'arxiv',            label: 'arXiv',           desc: '预印本',           journal: false },
  { value: 'nature',           label: 'Nature',          desc: 'Nature 系列期刊',   journal: false },
  { value: 'science',          label: 'Science',         desc: 'Science 系列期刊',  journal: false },
  { value: 'cell',             label: 'Cell',            desc: 'Cell Press 期刊',  journal: false },
] as const;

// 哪些源支持期刊筛选
const JOURNAL_CAPABLE: Set<string> = new Set(
  SOURCES.filter((s) => s.journal).map((s) => s.value)
);

// 期刊预设（第二层筛选）
const JOURNAL_PRESETS = [
  { value: '', label: '不限期刊' },
  { value: 'Nature', label: 'Nature' },
  { value: 'Science', label: 'Science' },
  { value: 'Cell', label: 'Cell' },
  { value: 'PNAS', label: 'PNAS' },
  { value: 'The Lancet', label: 'The Lancet' },
  { value: 'NEJM', label: 'NEJM' },
  { value: 'JACS', label: 'JACS' },
  { value: 'Angewandte Chemie', label: 'Angew. Chem.' },
  { value: 'Nature Communications', label: 'Nat. Commun.' },
  { value: 'Science Advances', label: 'Sci. Adv.' },
  { value: 'eLife', label: 'eLife' },
  { value: 'PLOS ONE', label: 'PLOS ONE' },
  { value: 'Nucleic Acids Research', label: 'Nucleic Acids Res.' },
  { value: 'Journal of Biological Chemistry', label: 'J. Biol. Chem.' },
  { value: 'Food Chemistry', label: 'Food Chemistry' },
  { value: 'Journal of Agricultural and Food Chemistry', label: 'J. Agric. Food Chem.' },
];

// OpenAlex 预印本源 -- 当选中 OpenAlex 时显示多选
const OPENALEX_PREPRINT_SOURCES = [
  { value: 'S4306402567', label: 'bioRxiv' },
  { value: 'S3005729997', label: 'medRxiv' },
  { value: 'S4393918830', label: 'ChemRxiv' },
];

type SearchMode = 'keyword' | 'natural';

interface SearchPageProps {
  onSelectPaper?: (paperId: number) => void;
}

export function SearchPage({ onSelectPaper }: SearchPageProps) {
  const [mode, setMode] = useState<SearchMode>('natural');
  const [query, setQuery] = useState('');
  const [naturalQuery, setNaturalQuery] = useState('');
  const [sources, setSources] = useState<string[]>(['europe_pmc']);
  const [maxResults, setMaxResults] = useState(10);
  const [countMode, setCountMode] = useState<'per_source' | 'total'>('per_source');
  const [maxTotal, setMaxTotal] = useState(30);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState('');
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Set<string>>(new Set());
  const [selectedHitKeys, setSelectedHitKeys] = useState<Set<string>>(new Set());
  const [batchImporting, setBatchImporting] = useState(false);
  const [sortBy, setSortBy] = useState<string>('relevance');
  const [sortOrder, setSortOrder] = useState<string>('desc');
  const [author, setAuthor] = useState('');
  const [journal, setJournal] = useState('');
  const [language, setLanguage] = useState<string>('');  // ''=all, 'zh'=中文, 'en'=外文
  const [openalexSources, setOpenalexSources] = useState<string[]>([]);
  const [searchProgress, setSearchProgress] = useState<{
    current: number; total: number;
    sources: Record<string, { done: boolean; count: number; error?: string }>;
  } | null>(null);
  const [detailHit, setDetailHit] = useState<SearchHit | null>(null);
  const [translating, setTranslating] = useState(false);
  const [translatedAbstract, setTranslatedAbstract] = useState<string | null>(null);
  const [translationError, setTranslationError] = useState(false);
  const translateRequestIdRef = useRef(0);

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
        if (state.countMode) setCountMode(state.countMode);
        if (state.maxTotal) setMaxTotal(state.maxTotal);
        if (state.sortBy) setSortBy(state.sortBy);
        if (state.sortOrder) setSortOrder(state.sortOrder);
        if (state.author) setAuthor(state.author);
        if (state.journal) setJournal(state.journal);
        if (state.language) setLanguage(state.language);
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
        countMode,
        maxTotal,
        sortBy,
        sortOrder,
        author,
        journal,
        language,
        result,
      }));
    } catch {
      // 存储满则忽略
    }
  }, [result, mode, query, naturalQuery, sources, maxResults, countMode, maxTotal, sortBy, sortOrder, author, journal, language]);

  // 点击卡片 → 显示元数据模态框
  const handleCardClick = useCallback((hit: SearchHit) => {
    setDetailHit(hit);
    setTranslatedAbstract(null);
    setTranslationError(false);

    // 检测是否英文摘要，是则自动翻译
    if (hit.abstract) {
      const hasCjk = /[\u4e00-\u9fff]/.test(hit.abstract);
      if (!hasCjk) {
        setTranslating(true);

        // 递增请求 ID，用于消除快速切换卡片时的竞态条件
        translateRequestIdRef.current += 1;
        const requestId = translateRequestIdRef.current;

        api.translate(hit.abstract)
          .then((res) => {
            if (requestId === translateRequestIdRef.current) {
              setTranslatedAbstract(res.translated);
              setTranslationError(false);
            }
          })
          .catch(() => {
            if (requestId === translateRequestIdRef.current) {
              setTranslatedAbstract(null);
              setTranslationError(true);
            }
          })
          .finally(() => {
            if (requestId === translateRequestIdRef.current) {
              setTranslating(false);
            }
          });
      }
    }
  }, []);

  const toggleSource = (value: string) => {
    setSources((prev) => {
      const next = prev.includes(value)
        ? prev.filter((s) => s !== value)
        : [...prev, value];
      // 当选中的源不全部支持期刊筛选时，清空期刊
      if (!next.every((s) => JOURNAL_CAPABLE.has(s))) {
        setJournal('');
      }
      return next;
    });
  };

  // 仅当选中的全部源都支持期刊筛选时才显示期刊下拉
  const showJournalFilter = useMemo(
    () => sources.length > 0 && sources.every((s) => JOURNAL_CAPABLE.has(s)),
    [sources]
  );

  // 仅当选中 OpenAlex 时显示预印本多选
  const showOpenAlexFilter = useMemo(
    () => sources.includes('openalex'),
    [sources]
  );

  const handleSearch = async () => {
    const hasKeyword = mode === 'natural' ? naturalQuery.trim() : query.trim();
    if ((!hasKeyword && !author.trim()) || sources.length === 0) return;

    setLoading(true);
    setError('');
    setResult(null);
    // 初始化进度：所有源标记为等待中
    const initialSources: Record<string, { done: boolean; count: number }> = {};
    sources.forEach((s) => { initialSources[s] = { done: false, count: 0 }; });
    setSearchProgress({ current: 0, total: countMode === 'total' ? maxTotal : sources.length * maxResults, sources: initialSources });

    try {
      const params =
        mode === 'natural'
          ? { natural_query: naturalQuery, sources, max_results: countMode === 'per_source' ? maxResults : 50, author: author || undefined, journal: journal || undefined, preprint_sources: openalexSources.length > 0 ? openalexSources : undefined, language: language || undefined, max_total: countMode === 'total' ? maxTotal : undefined }
          : { query, sources, max_results: countMode === 'per_source' ? maxResults : 50, author: author || undefined, journal: journal || undefined, preprint_sources: openalexSources.length > 0 ? openalexSources : undefined, language: language || undefined, max_total: countMode === 'total' ? maxTotal : undefined };

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
    // 用 DOI 或标题作为唯一 key
    const key = hit.doi || hit.title;
    if (importingIds.has(key)) return;

    setImportingIds((prev) => new Set(prev).add(key));

    try {
      const importResult = await api.importPaper({
        title: hit.title,
        abstract: hit.abstract,
        authors: hit.authors,
        author_affiliations: hit.author_affiliations,
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

      // 入库成功后立即更新 UI 状态（不等流水线）
      setImportedIds((prev) => new Set(prev).add(key));
      if (result) {
        setResult({
          ...result,
          results: result.results.map((r) =>
            r.title === hit.title
              ? { ...r, in_library: true, paper_id: importResult.paper_id, library_status: 'metadata_only' }
              : r
          ),
        });
      }

      // 触发后台流水线（失败时仅警告，不改变入库状态）
      try {
        await api.processPaper(importResult.paper_id);
      } catch {
        setError('论文已入库，但流水线触发失败。请在文献库中手动点击「处理」。');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  // ---- 多选功能 ----
  const getHitKey = (hit: SearchHit) => hit.doi || hit.title;

  const toggleSelectHit = (hit: SearchHit) => {
    const key = getHitKey(hit);
    setSelectedHitKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (!result) return;
    const unimportedHits = sortedResults.filter(
      (h) => !importedIds.has(getHitKey(h)) && !h.in_library
    );
    if (unimportedHits.length === 0) return;

    const allSelected = unimportedHits.every((h) => selectedHitKeys.has(getHitKey(h)));
    if (allSelected) {
      setSelectedHitKeys(new Set());
    } else {
      setSelectedHitKeys(new Set(unimportedHits.map(getHitKey)));
    }
  };

  const handleBatchImport = async () => {
    if (!result || selectedHitKeys.size === 0) return;
    setBatchImporting(true);
    setError('');

    const selectedHits = sortedResults.filter(
      (h) => selectedHitKeys.has(getHitKey(h))
    );
    const toImport = selectedHits.filter(
      (h) => !importedIds.has(getHitKey(h)) && !h.in_library
    );

    try {
      const batchResult = await api.importPapersBatch(
        toImport.map((h) => ({
          title: h.title,
          abstract: h.abstract,
          authors: h.authors,
          author_affiliations: h.author_affiliations,
          year: h.year,
          journal: h.journal,
          doi: h.doi,
          pmid: h.pmid,
          pmcid: h.pmcid,
          source: h.source,
          url: h.url,
          pdf_url: h.pdf_url,
          license: h.license,
          is_open_access: h.is_open_access,
          domain_score: h.domain_score,
        }))
      );

      // 更新 UI 状态
      const newImportedKeys = new Set(importedIds);
      const updatedResults = [...result.results];
      for (const r of batchResult.results) {
        if (r.success && r.title) {
          const hit = sortedResults.find((h) => h.title === r.title);
          if (hit) {
            newImportedKeys.add(getHitKey(hit));
            const idx = updatedResults.findIndex((u) => u.title === r.title);
            if (idx >= 0) {
              updatedResults[idx] = {
                ...updatedResults[idx],
                in_library: true,
                paper_id: r.paper_id ?? null,
                library_status: 'metadata_only',
              };
            }
          }
        }
      }
      setImportedIds(newImportedKeys);
      setSelectedHitKeys(new Set());
      setResult({ ...result, results: updatedResults });

      // 触发批量流水线
      const successIds = batchResult.results
        .filter((r) => r.success && r.paper_id != null)
        .map((r) => r.paper_id!);
      if (successIds.length > 0) {
        try {
          await api.processPapersBatch(successIds);
        } catch {
          setError(`${successIds.length} 篇论文已入库，但部分流水线触发失败。请在文献库中手动处理。`);
        }
      }

      if (batchResult.failed_count > 0) {
        setError(`${batchResult.success_count} 篇入库成功，${batchResult.failed_count} 篇失败`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBatchImporting(false);
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
      <div className="flex gap-2 mb-3">
        <div className="relative flex-1">
          <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="按作者筛选（可选），如 Geoffrey Hinton"
            className="w-full pl-10 pr-8 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
          />
          {author && (
            <button
              onClick={() => setAuthor('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title="清除作者筛选"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 文献语言 */}
      <div className="flex gap-2 mb-3 items-center">
        <span className="text-xs text-gray-400 font-medium mr-1">语言</span>
        {[
          { value: '', label: '中外文献' },
          { value: 'zh', label: '中文文献' },
          { value: 'en', label: '外文文献' },
        ].map((opt) => (
          <button
            key={opt.value}
            onClick={() => setLanguage(opt.value)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
              language === opt.value
                ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300 hover:text-indigo-600'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* 期刊筛选（第二层）— 仅在所有选中源都支持期刊筛选时显示 */}
      {showJournalFilter && (
      <div className="flex gap-2 mb-3">
        <select
          value={JOURNAL_PRESETS.some((j) => j.value === journal) ? journal : ''}
          onChange={(e) => setJournal(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
        >
          {JOURNAL_PRESETS.map((j) => (
            <option key={j.value} value={j.value}>{j.label}</option>
          ))}
        </select>
        <input
          value={journal}
          onChange={(e) => setJournal(e.target.value)}
          placeholder="或输入自定义期刊名..."
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 transition-colors"
        />
        {journal && (
          <button
            onClick={() => setJournal('')}
            className="px-2 py-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
            title="清除期刊筛选"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
      )}

      {/* OpenAlex 预印本多选 — 仅在选中 OpenAlex 时显示 */}
      {showOpenAlexFilter && (
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-xs text-gray-500 font-medium">预印本源:</span>
        {OPENALEX_PREPRINT_SOURCES.map((ps) => {
          const active = openalexSources.includes(ps.value);
          return (
            <button
              key={ps.value}
              onClick={() => setOpenalexSources((prev) =>
                prev.includes(ps.value) ? prev.filter((v) => v !== ps.value) : [...prev, ps.value]
              )}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all border ${
                active
                  ? 'bg-emerald-600 text-white border-emerald-600'
                  : 'bg-white text-gray-500 border-gray-200 hover:border-emerald-300'
              }`}
            >
              {ps.label}
            </button>
          );
        })}
        {openalexSources.length > 0 && (
          <button
            onClick={() => setOpenalexSources([])}
            className="text-xs text-gray-400 hover:text-gray-600 ml-1"
          >
            清除
          </button>
        )}
      </div>
      )}

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
        <div className="flex items-center gap-2">
          {/* 每源 / 总计 切换 */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            <button
              onClick={() => setCountMode('per_source')}
              className={`px-2.5 py-2 text-xs font-medium transition-colors ${
                countMode === 'per_source' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'
              }`}
            >
              每源
            </button>
            <button
              onClick={() => setCountMode('total')}
              className={`px-2.5 py-2 text-xs font-medium transition-colors ${
                countMode === 'total' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'
              }`}
            >
              总计
            </button>
          </div>
          {/* 篇数选择 */}
          {countMode === 'per_source' ? (
            <select
              value={maxResults}
              onChange={(e) => setMaxResults(Number(e.target.value))}
              className="px-2 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-indigo-500"
            >
              {[5, 10, 20, 50, 100].map((n) => (
                <option key={n} value={n}>{n} 篇/源</option>
              ))}
            </select>
          ) : (
            <select
              value={maxTotal}
              onChange={(e) => setMaxTotal(Number(e.target.value))}
              className="px-2 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-indigo-500"
            >
              {[10, 20, 30, 50, 100, 200].map((n) => (
                <option key={n} value={n}>共 {n} 篇</option>
              ))}
            </select>
          )}
        </div>
        <button
          onClick={handleSearch}
          disabled={loading || (!query.trim() && !naturalQuery.trim() && !author.trim()) || sources.length === 0}
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

      {/* 批量操作栏 */}
      {result && !loading && sortedResults.filter((h) => !h.in_library && !importedIds.has(getHitKey(h))).length > 0 && (
        <div className="flex items-center gap-3 mb-4 p-3 rounded-xl border border-indigo-100 bg-indigo-50/50">
          <button
            onClick={toggleSelectAll}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors bg-white text-gray-600 border-gray-200 hover:border-indigo-300"
          >
            {selectedHitKeys.size > 0 &&
              (() => {
                const selectable = sortedResults.filter((h) => !h.in_library && !importedIds.has(getHitKey(h)));
                return selectable.length > 0 && selectable.every((h) => selectedHitKeys.has(getHitKey(h)));
              })() ? (
              <CheckSquare className="w-3.5 h-3.5 text-indigo-500" />
            ) : (
              <Square className="w-3.5 h-3.5" />
            )}
            全选
          </button>
          <span className="text-xs text-gray-400">
            已选 <span className="font-medium text-indigo-600">{selectedHitKeys.size}</span> 篇
          </span>
          <div className="flex-1" />
          <button
            onClick={handleBatchImport}
            disabled={selectedHitKeys.size === 0 || batchImporting}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {batchImporting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            {batchImporting ? '入库中...' : `一键入库 (${selectedHitKeys.size})`}
          </button>
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
                  importing={importingIds.has(hit.doi || hit.title)}
                  imported={importedIds.has(hit.doi || hit.title) || hit.in_library}
                  selected={selectedHitKeys.has(getHitKey(hit))}
                  onToggleSelect={() => toggleSelectHit(hit)}
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
          onClick={() => { setDetailHit(null); setTranslatedAbstract(null); setTranslationError(false); setTranslating(false); }}>
          <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between rounded-t-2xl">
              <h3 className="text-sm font-semibold text-gray-900 pr-4">文献详情</h3>
              <button onClick={() => { setDetailHit(null); setTranslatedAbstract(null); setTranslationError(false); setTranslating(false); }}
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
                  : translationError ? <p className="text-sm text-red-500 italic">翻译失败，请稍后重试</p>
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
  selected,
  onToggleSelect,
  onImport,
  onView,
  onClick,
}: {
  hit: SearchHit;
  rank: number;
  importing: boolean;
  imported: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onImport: () => void;
  onView: () => void;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className="rounded-xl border border-gray-200 bg-white p-4 hover:shadow-sm hover:border-indigo-200 transition-all cursor-pointer">
      <div className="flex items-start gap-3">
        {/* 多选框 */}
        {!imported && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
            className="shrink-0 mt-0.5 text-gray-400 hover:text-indigo-500 transition-colors"
            title={selected ? '取消选择' : '选择'}
          >
            {selected ? (
              <CheckSquare className="w-4 h-4 text-indigo-500" />
            ) : (
              <Square className="w-4 h-4" />
            )}
          </button>
        )}

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
            {hit.tags && hit.tags.length > 0 && hit.tags.map((tag) => (
              <span key={tag} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                tag === '综述' ? 'bg-blue-50 text-blue-600 border border-blue-100' :
                tag === '经典' ? 'bg-amber-50 text-amber-600 border border-amber-100' :
                'bg-emerald-50 text-emerald-600 border border-emerald-100'
              }`}>
                {tag}
              </span>
            ))}
            <span className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${hit.in_library ? 'bg-emerald-500' : 'bg-gray-300'}`} />
              {hit.in_library
                ? (hit.library_status === 'indexed' ? '已索引'
                  : hit.library_status === 'chunked' ? '已切块'
                  : hit.library_status === 'parsed' ? '已解析'
                  : hit.library_status === 'pdf_downloaded' ? '已下载PDF'
                  : '已入库')
                : '未入库'}
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
