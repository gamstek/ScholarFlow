import { useQuery } from '@tanstack/react-query';

interface Paper {
  id: number;
  title: string;
  doi: string;
  year: number;
  status: string;
  domain_score: number;
}

interface PaperResponse {
  papers: Paper[];
}

interface Stat {
  status: string;
  count: number;
}

interface StatsResponse {
  papers_total: number;
  chunks_total: number;
  paper_status: Stat[];
}

/**
 * 文献库数据 hook。
 * 使用 TanStack Query 缓存 papers 和 stats。
 */
export function usePapers() {
  const papers = useQuery<PaperResponse>({
    queryKey: ['papers'],
    queryFn: () => fetch('/papers?limit=50').then((r) => r.json()),
    staleTime: 30_000,
  });

  const stats = useQuery<StatsResponse>({
    queryKey: ['stats'],
    queryFn: () => fetch('/stats').then((r) => r.json()),
    staleTime: 30_000,
  });

  return { papers, stats };
}
