import { Dialog as Primitive } from '@base-ui/react/dialog';
import type { ReactNode } from 'react';

// Local shadcn-style composition over Base UI: semantics, focus trapping and
// focus restoration belong to the primitive; appearance belongs to our tokens.
export function Dialog({
  trigger,
  title,
  children,
}: {
  trigger: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <Primitive.Root>
      <Primitive.Trigger>{trigger}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Backdrop className="dialog-backdrop" />
        <Primitive.Viewport className="dialog-viewport">
          <Primitive.Popup className="dialog">
            <Primitive.Title>{title}</Primitive.Title>
            {children}
            <Primitive.Close>Close</Primitive.Close>
          </Primitive.Popup>
        </Primitive.Viewport>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
