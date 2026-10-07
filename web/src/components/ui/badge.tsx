import type { HTMLAttributes, ReactNode } from 'react';

type Variant = 'default' | 'secondary' | 'outline' | 'open' | 'active' | 'done' | 'cancelled';

export function Badge({
  variant = 'secondary',
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & {
  variant?: Variant;
  children: ReactNode;
}) {
  return (
    <span className={`badge badge-${variant} ${className}`.trim()} {...props}>
      {children}
    </span>
  );
}
