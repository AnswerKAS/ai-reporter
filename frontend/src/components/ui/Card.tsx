import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Карточка реагирует на наведение — для кликабельных элементов списка. */
  interactive?: boolean
}

export function Card({ interactive = false, className, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'rounded-card border border-line bg-surface p-5 shadow-card',
        interactive &&
          'transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-accent hover:shadow-pop',
        className,
      )}
      {...props}
    />
  )
}
