import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

/** Единая колонка контента: ширина, поля, отбивки — одинаковые на всех страницах. */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <main className={cn('mx-auto w-full max-w-page px-4 pt-7 pb-16 sm:px-8 lg:pt-10', className)}>{children}</main>
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
    <header className="mb-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold tracking-tight text-fg sm:text-4xl">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {subtitle && <p className="mt-2 max-w-3xl text-sm text-fg-muted">{subtitle}</p>}
      {children}
    </header>
  )
}
