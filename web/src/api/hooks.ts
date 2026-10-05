import { useQuery } from '@tanstack/react-query';
import { api } from './client';

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 60_000 });
}

export function useConfigs() {
  return useQuery({ queryKey: ['configs'], queryFn: api.configs, staleTime: 5_000 });
}

/** Names of one config kind (pipelines, agents, ...). */
export function useConfigNames(kind: string): string[] {
  const { data } = useConfigs();
  return (data?.[kind] ?? []).map((e) => e.name);
}
