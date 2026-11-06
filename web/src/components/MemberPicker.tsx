import { useId, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { request, type Member, type Page } from '../api/client';
import { Button } from './ui/button';

export function MemberPicker({ workspace, label, name, value, selected, onChange, emptyLabel = 'Unassigned' }: {
  workspace: string; label: string; name?: string; value: string; selected?: Member | null;
  onChange: (value: string) => void; emptyLabel?: string;
}) {
  const id = useId();
  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState(selected);
  const members = useInfiniteQuery({
    queryKey: [workspace, 'members', search], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => request<Page<Member>>(`/members?${new URLSearchParams({ limit: '100', ...(search ? { q: search } : {}), ...(pageParam ? { cursor: pageParam } : {}) })}`, { signal }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const rows = members.data?.pages.flatMap((page) => page.data) ?? [];
  const options = [...new Map([...rows, ...(chosen ? [chosen] : [])].map((member) => [member.id, member])).values()];
  return <div className="workflow-field">
    <label htmlFor={id}>{label}</label>
    <input className="sx-control" type="search" aria-label={`${label} search`} placeholder="Search workspace members" value={search} onChange={(event) => setSearch(event.target.value)} />
    <select id={id} className="sx-control" name={name} value={value} onChange={(event) => {
      const next = event.target.value;
      setChosen(options.find((member) => member.id === next)); onChange(next);
    }}>
      <option value="">{emptyLabel}</option>
      {value && !options.some((member) => member.id === value) && <option value={value}>Current member</option>}
      {options.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}
    </select>
    {members.error && <p role="alert">{members.error.message}</p>}
    {members.hasNextPage && <Button variant="ghost" type="button" disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>Load more members</Button>}
  </div>;
}
