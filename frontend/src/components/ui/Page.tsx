import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** Единая колонка контента: ширина, поля, отбивки — одинаковые на всех страницах. */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <main className={cn('mx-auto w-full max-w-page px-4 pt-8 pb-16 sm:px-6', className)}>{children}</main>
}

export function PageHeader({
  title,
  subtitle,
  actions,
  children,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <header className="mb-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="text-3xl font-bold tracking-tight text-fg">{title}</h1>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {subtitle && <p className="mt-1.5 text-sm text-fg-muted">{subtitle}</p>}
      {children}
    </header>
  )
}
