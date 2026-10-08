import type { HTMLAttributes, ReactNode } from 'react';

type Variant = 'default' | 'secondary' | 'outline' | 'open' | 'active' | 'done' | 'cancelled';
const glyphs: Partial<Record<Variant, string>> = {
  open: '○',
  active: '◑',
  done: '●',
  cancelled: '⊘',
};

export function Badge({
  variant = 'secondary',
  className = '',
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & {
  variant?: Variant;
  children: ReactNode;
}) {
  const glyph = glyphs[variant];
  return (
    <span
      className={`${glyph ? 'sx-status' : 'sx-label'} badge badge-${variant} ${className}`.trim()}
      data-cat={glyph ? variant : undefined}
      {...props}
    >
      {glyph && <span className="sx-glyph" aria-hidden="true">{glyph}</span>}
      {children}
    </span>
  );
}
