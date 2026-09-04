import { cn } from '../../lib/cn'

/** Плейсхолдер загрузки. Пульсация выключается через prefers-reduced-motion
    (глобальное правило в styles/theme.css). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-control bg-surface-sunken', className)} />
}

/** Сетка карточек — под списки отчётов и датасетов. */
export function SkeletonCards({ count = 6 }: { count?: number }) {
  return (
    <div role="status" aria-label="Загрузка" className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-card border border-line bg-surface p-5">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="mt-3 h-4 w-full" />
          <Skeleton className="mt-2 h-4 w-4/5" />
          <Skeleton className="mt-4 h-3 w-1/3" />
        </div>
      ))}
    </div>
  )
}

/** Строки — под таблицы, списки админки и модель данных. */
export function SkeletonRows({ count = 5 }: { count?: number }) {
  return (
    <div role="status" aria-label="Загрузка" className="flex flex-col gap-2.5">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}
