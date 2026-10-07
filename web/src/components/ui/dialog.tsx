import { Dialog as Primitive } from '@base-ui/react/dialog';
import type { ReactNode } from 'react';

// Local shadcn-style composition over Base UI: semantics, focus trapping and
// focus restoration belong to the primitive; appearance belongs to our tokens.
export function Dialog({
  trigger,
  title,
  children,
  triggerVariant = 'outline',
}: {
  trigger: string;
  title: string;
  children: ReactNode;
  triggerVariant?: 'default' | 'outline' | 'secondary' | 'ghost' | 'destructive';
}) {
  return (
    <Primitive.Root>
      <Primitive.Trigger className={`button button-${triggerVariant}`}>
        {trigger}
      </Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Backdrop className="dialog-backdrop" />
        <Primitive.Viewport className="dialog-viewport">
          <Primitive.Popup className="dialog">
            <div className="dialog-head">
              <Primitive.Title className="dialog-title">{title}</Primitive.Title>
              <Primitive.Close
                className="button button-ghost button-sm dialog-close"
                aria-label="Close dialog"
              >
                Close
              </Primitive.Close>
            </div>
            <div className="dialog-content">{children}</div>
          </Primitive.Popup>
        </Primitive.Viewport>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
