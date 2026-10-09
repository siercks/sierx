import { useState } from 'react';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { request, type Me, type Page, type Project } from '../api/client';
import { Button } from './ui/button';

export function ProjectNavigation({ workspace, me, projectPage, selected, onNavigate, onManage }: {
  workspace: string; me: Me; projectPage: Page<Project>; selected: Project | null;
  onNavigate: (key: string) => void; onManage: () => void;
}) {
  const [search, setSearch] = useState('');
  const queryClient = useQueryClient();
  const pages = useInfiniteQuery({
    queryKey: [workspace, 'projects', search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<{ data: Project[]; next_cursor: string | null }>(`/projects?${new URLSearchParams({ limit: '100', ...(search ? { search } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    initialData: search ? undefined : { pages: [projectPage], pageParams: [null] },
    enabled: !!search,
  });
  const options = [...new Map([...(pages.data?.pages.flatMap((page) => page.data) ?? projectPage.data), ...(selected ? [selected] : [])].filter((p) => !p.archived_at).map((p) => [p.key_prefix, p])).values()];
  return <nav className="project-navigation" aria-label="Project navigation">
    <label className="preference-field"><span>Project</span><select className="sx-control" value={selected?.key_prefix ?? ''} onChange={(event) => { setSearch(''); const next = options.find((item) => item.key_prefix === event.target.value); if (next) queryClient.setQueryData([workspace, 'project', next.key_prefix], next); onNavigate(event.target.value); }}>
      <option value="">Workspace overview</option>
      {options.map((project) => <option key={project.key_prefix} value={project.key_prefix}>{project.name} ({project.key_prefix})</option>)}
    </select></label>
    <label className="sr-only" htmlFor="project-search">Find a project</label>
    <input id="project-search" className="sx-control" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a project" />
    {pages.hasNextPage && <Button variant="ghost" size="sm" onClick={() => void pages.fetchNextPage()}>More</Button>}
    {me.role === 'admin' && <Button variant="outline" size="sm" onClick={onManage}>Manage projects</Button>}
  </nav>;
}
