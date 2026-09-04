import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export type BadgeTone = 'neutral' | 'good' | 'bad' | 'warn' | 'accent'

const TONES: Record<BadgeTone, string> = {
  neutral: 'border-line bg-bg text-fg-muted',
  good: 'border-good/30 bg-good-soft text-good',
  bad: 'border-bad/30 bg-bad-soft text-bad',
  warn: 'border-warn/30 bg-warn-soft text-warn',
  accent: 'border-accent-soft bg-accent-soft text-accent',
}

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
}

export function Badge({ tone = 'neutral', className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold',
        TONES[tone],
        className,
      )}
      {...props}
    />
  )
}
