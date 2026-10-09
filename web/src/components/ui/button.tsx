import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'default' | 'outline' | 'secondary' | 'ghost' | 'destructive';
type Size = 'default' | 'sm' | 'icon';

export function Button({
  variant = 'outline',
  size = 'default',
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
}) {
  return (
    <button
      // Keep decorative theme pseudo-elements out of text button names.
      aria-label={typeof children === 'string' ? children : undefined}
      className={`sx-btn button button-${variant} button-${size} ${className}`.trim()}
      data-variant={variant === 'default' ? 'primary' : variant}
      {...props}
    >
      {children}
    </button>
  );
}
