import { useCallback, useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/cn'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Единственная модалка приложения: Esc, фокус-трап, возврат фокуса на
 * инициатора, блокировка прокрутки фона, закрытие по клику на подложку.
 * Раньше это было двумя независимыми реализациями (конструктор и график),
 * каждая без трапа и без возврата фокуса.
 *
 * Рисуется порталом в body: sticky-сайдбар и sticky-шапка создают свои
 * контексты наложения, и модалка, отрисованная внутри них, уходила под
 * контент страницы — никакой z-index внутри чужого контекста не помогает.
 */
export function Modal({
  title,
  onClose,
  children,
  footer,
  size = 'md',
  align = 'center',
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** `xl` — для окон с таблицами: превью датасета в `lg` живёт в колодце
      шириной с половину экрана и прокручивается вбок на каждой колонке. */
  size?: 'md' | 'lg' | 'xl'
  align?: 'center' | 'top'
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (!nodes || nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || active === dialogRef.current)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    },
    [onClose],
  )

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'

    const target = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE) ?? dialogRef.current
    target?.focus()

    return () => {
      document.body.style.overflow = overflow
      opener?.focus?.()
    }
  }, [])

  return createPortal(
    <div
      className={cn(
        'fixed inset-0 z-50 flex justify-center overflow-y-auto bg-overlay p-4',
        align === 'top' ? 'items-start pt-[6vh]' : 'items-center',
      )}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={cn(
          'flex w-full flex-col gap-3 rounded-card border border-line bg-surface p-5 shadow-modal',
          size === 'xl' ? 'max-h-[92vh] max-w-6xl' : 'max-h-[85vh]',
          size === 'lg' ? 'max-w-3xl' : size === 'md' ? 'max-w-xl' : '',
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-base font-semibold text-fg">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="-mr-1 cursor-pointer rounded-control px-2 text-xl leading-none text-fg-muted hover:bg-surface-sunken hover:text-fg"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
        {/* -mr-3/pr-3: полоса прокрутки и кольцо фокуса живут в отступе диалога,
            а не поверх правого столбца формы. На macOS полоса рисуется
            накладкой — без этого зазора она перекрывает край поля, а кольцо
            фокуса у крайнего справа контрола обрезается краем прокрутки. */}
        <div className="-mr-3 min-h-0 flex-1 overflow-y-auto pr-3">{children}</div>
        {/* полоса над кнопками: тело прокручивается, и без неё длинная форма
            обрывалась посреди поля — это читалось как обрезанная вёрстка, а
            не как «дальше есть ещё» */}
        {footer && (
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">{footer}</div>
        )}
      </div>
    </div>,
    document.body,
  )
}
