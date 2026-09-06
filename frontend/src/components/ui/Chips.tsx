import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

export interface ChipOption<T extends string> {
  value: T
  label: ReactNode
  /** Сколько записей даст выбор этого варианта поверх остальных фильтров. */
  count?: number
}

/**
 * Фильтр с множественным выбором: нажатые значения складываются по «или»,
 * пустой набор означает «все».
 *
 * Это не `Segmented` с несколькими нажатыми: у того одно значение и роль
 * `tab`, здесь — группа независимых переключателей (`aria-pressed`), и «ничего
 * не выбрано» — законное состояние, а не отсутствие ответа. Селекта с
 * `multiple` здесь нет намеренно: вариантов три-четыре, и важно видеть их все
 * вместе со счётчиками, не открывая список.
 *
 * Наружу отдаётся нажатое значение (`onToggle`), а не готовый набор: набор
 * пришлось бы считать от `values`, а этот проп на момент нажатия бывает
 * отстающим — например, когда его источник обновляется переходом роутера.
 * Два быстрых нажатия подряд в такой схеме теряют первое; владелец состояния
 * складывает набор сам, от своего актуального значения.
 *
 * Вариант, за которым не осталось ни одной записи, отключается — нажатие на
 * него дало бы гарантированно пустой список. Уже выбранный вариант не
 * отключается никогда, иначе его нечем было бы снять.
 */
export function Chips<T extends string>({
  values,
  options,
  onToggle,
  ariaLabel,
  className,
}: {
  values: T[]
  options: ChipOption<T>[]
  onToggle: (value: T) => void
  ariaLabel: string
  className?: string
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn('inline-flex flex-wrap gap-1 rounded-control border border-line bg-bg p-1', className)}
    >
      {options.map((option) => {
        const active = values.includes(option.value)
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            disabled={!active && option.count === 0}
            onClick={() => onToggle(option.value)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm transition-colors',
              'disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent',
              active
                ? 'cursor-pointer bg-accent-soft font-semibold text-accent'
                : 'cursor-pointer text-fg-muted hover:bg-surface-sunken hover:text-fg',
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
