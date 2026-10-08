import { Dialog as Primitive } from '@base-ui/react/dialog';
import type { ReactNode } from 'react';

// Base UI supplies dialog behavior; Sierx owns the component structure and style.
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
      <Primitive.Trigger
        className={`sx-btn button button-${triggerVariant}`}
        data-variant={triggerVariant === 'default' ? 'primary' : triggerVariant}
      >
        {trigger}
      </Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Backdrop className="dialog-backdrop" />
        <Primitive.Viewport className="dialog-viewport">
          <Primitive.Popup className="dialog">
            <div className="dialog-head">
              <Primitive.Title className="dialog-title">{title}</Primitive.Title>
              <Primitive.Close
                className="sx-btn button button-ghost button-sm dialog-close"
                data-variant="ghost"
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
