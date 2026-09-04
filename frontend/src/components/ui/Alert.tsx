import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export type AlertTone = 'error' | 'success' | 'warn' | 'info'

const TONES: Record<AlertTone, string> = {
  error: 'border-bad/30 bg-bad-soft text-bad',
  success: 'border-good/30 bg-good-soft text-good',
  warn: 'border-warn/30 bg-warn-soft text-warn',
  info: 'border-line bg-surface-sunken text-fg-muted',
}

export function Alert({
  tone = 'error',
  children,
  className,
}: {
  tone?: AlertTone
  children: ReactNode
  className?: string
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-control border px-3 py-2 text-sm', TONES[tone], className)}
    >
      {children}
    </div>
  )
}
