import { cn } from '../../lib/cn'

/** Кружок с первой буквой имени — взгляд цепляется за него в длинном списке. */
export function Avatar({ name, tone = 'neutral' }: { name: string; tone?: 'neutral' | 'accent' }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold',
        tone === 'accent' ? 'bg-accent-soft text-accent' : 'bg-surface-sunken text-fg-muted',
      )}
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
}
