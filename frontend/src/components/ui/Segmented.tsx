import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface SegmentOption<T extends string> {
  value: T
  label: ReactNode
  count?: number
}

/** Переключатель на несколько положений: вкладки админки, фильтр по роли,
    режим панели доступа. Вместо селекта — потому что вариантов два-четыре и
    важно видеть их все сразу вместе со счётчиками. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  className,
}: {
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
  ariaLabel: string
  className?: string
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn('inline-flex flex-wrap gap-1 rounded-card border border-line bg-surface-sunken p-1', className)}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-control px-3.5 py-1.5 text-sm transition-colors',
              active ? 'bg-surface font-semibold text-fg shadow-card' : 'text-fg-muted hover:text-fg',
            )}
          >
            {option.label}
            {option.count !== undefined && (
              <span
                className={cn(
                  'rounded-full px-1.5 text-xs tabular-nums',
                  active ? 'bg-accent text-accent-fg' : 'bg-surface-sunken text-fg-muted',
                )}
              >
                {option.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
