import { useRef, useState } from 'react';
import type { Item } from '../api/client';
import { ActionForm } from './ItemActions';
import { MemberPicker } from './MemberPicker';
import { Dialog } from './ui/dialog';
import { Button } from './ui/button';

export function DetailEditor({ item, workspace, field, label }: { item: Item; workspace: string; field: 'assignee' | 'start_date' | 'due_date'; label: string }) {
  const [open, setOpen] = useState(false);
  const [member, setMember] = useState(item.assignee?.id ?? '');
  const date = useRef<HTMLInputElement>(null);
  return <Dialog trigger={`Edit ${label.toLowerCase()}`} title={`Edit ${label.toLowerCase()}`} open={open} onOpenChange={(next) => { setOpen(next); if (next) setMember(item.assignee?.id ?? ''); }} triggerVariant="ghost">
    <ActionForm item={item} workspace={workspace} path={'/items/' + item.key} method="PATCH" label={`Save ${label.toLowerCase()}`} body={(data) => ({ [field]: String(data.get(field) ?? '') || null })} onSuccess={() => setOpen(false)}>
      {field === 'assignee' ? <MemberPicker label="Assignee" name="assignee" workspace={workspace} value={member} selected={item.assignee} onChange={setMember} /> : <>
        <label className="workflow-field">{label}<input ref={date} className="sx-control" type="date" name={field} defaultValue={item[field] ?? ''} /></label>
        <Button type="button" variant="ghost" onClick={() => { if (date.current) { date.current.value = ''; date.current.dispatchEvent(new Event('input', { bubbles: true })); } }}>Clear date</Button>
      </>}
    </ActionForm>
  </Dialog>;
}
