import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** Единая колонка контента: ширина, поля, отбивки — одинаковые на всех страницах. */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <main className={cn('mx-auto w-full max-w-page px-4 pt-7 pb-16 sm:px-8 lg:pt-10', className)}>{children}</main>
}

/** Заголовок страницы с возможностью компактной шапки для рабочего режима. */
export function PageHeader({
  title,
  subtitle,
  actions,
  children,
  className,
  compact = false,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  compact?: boolean
}) {
  return (
    <header className={cn(compact ? 'mb-3' : 'mb-8', className)}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className={cn('font-semibold tracking-tight text-fg', compact ? 'text-xl sm:text-2xl' : 'text-3xl sm:text-4xl')}>{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {subtitle && <p className="mt-2 max-w-3xl text-sm text-fg-muted">{subtitle}</p>}
      {children}
    </header>
  )
}
