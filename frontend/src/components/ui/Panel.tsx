import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Badge } from './Badge'

/** Каркас блока страницы: шапка со счётчиком и действиями, полоса инструментов
    (поиск, фильтры) и тело. Раньше каждый блок описывал свои отступы сам —
    и расходился с соседним на пару пикселей. Им собраны разделы админки и
    кабинета: блок со счётчиком и поиском нужен обеим. */
export function Panel({
  title,
  count,
  description,
  actions,
  toolbar,
  children,
  className,
}: {
  title: ReactNode
  count?: number
  description?: ReactNode
  actions?: ReactNode
  toolbar?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-card border border-line bg-surface shadow-card', className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            {title}
            {count !== undefined && <Badge>{count}</Badge>}
          </h2>
          {description && <p className="mt-1 max-w-prose text-sm text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {toolbar && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-sunken px-5 py-3">
          {toolbar}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

/** Строка списка внутри блока: пользователь, назначение, рассылка, сервер. */
export function PanelRow({
  className,
  children,
  selected = false,
  ...props
}: { selected?: boolean } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-3 rounded-control border px-3 py-2.5 text-sm transition-colors',
        selected ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
