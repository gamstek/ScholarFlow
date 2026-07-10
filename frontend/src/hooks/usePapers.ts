import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, type PaperResponse, type StatsResponse } from '../lib/api';

/**
 * 文献库数据 hook。
 * 使用 TanStack Query 缓存 papers 和 stats。
 */
export function usePapers() {
  const queryClient = useQueryClient();

  const papers = useQuery<PaperResponse>({
    queryKey: ['papers'],
    queryFn: () => api.papers(50),
    staleTime: 30_000,
  });

  const stats = useQuery<StatsResponse>({
    queryKey: ['stats'],
    queryFn: () => api.stats(),
    staleTime: 30_000,
  });

  const deletePaper = useMutation({
    mutationFn: (paperId: number) => api.deletePaper(paperId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['papers'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  return { papers, stats, deletePaper };
}
