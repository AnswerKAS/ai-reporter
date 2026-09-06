import { useEffect, useRef, useState } from 'react'
import { cn } from '../../lib/cn'

export interface RowAction {
  label: string
  onSelect: () => void
  /** Опасное действие — красным и в самом низу списка. */
  danger?: boolean
}

/**
 * Меню действий строки за кнопкой «…».
 *
 * Кнопки на строке видны по наведению — на мыши это правильно, места в узком
 * меню нет. Но наведения не бывает ни на тач-устройстве, ни с клавиатуры,
 * поэтому те же действия обязаны быть и здесь.
 *
 * Список позиционируется `fixed` по месту кнопки: меню слева прокручивается
 * (`overflow-y: auto`), и абсолютно позиционированный список в нём обрезается.
 */
export function RowMenu({ label, actions }: { label: string; actions: RowAction[] }) {
  const [at, setAt] = useState<{ top: number; right: number } | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!at) return
    const close = (event: Event) => {
      const target = event.target as Node
      if (menu.current?.contains(target) || button.current?.contains(target)) return
      setAt(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAt(null)
        button.current?.focus()
      }
    }
    // прокрутка уводит кнопку из-под меню — считать координаты заново дороже,
    // чем закрыть: меню открыто ровно на одно действие
    const onScroll = () => setAt(null)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [at])

  const open = () => {
    const rect = button.current?.getBoundingClientRect()
    if (!rect) return
    setAt({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) })
  }

  const ordered = [...actions].sort((a, b) => Number(a.danger ?? false) - Number(b.danger ?? false))

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={at !== null}
        title={label}
        onClick={() => (at ? setAt(null) : open())}
        className={cn(
          'cursor-pointer rounded-control px-1.5 py-1 text-xs text-fg-muted',
          'hover:bg-bg hover:text-fg',
          at && 'bg-bg text-fg',
        )}
      >
        <span aria-hidden="true">⋯</span>
      </button>

      {at && (
        <div
          ref={menu}
          role="menu"
          style={{ top: at.top, right: at.right }}
          className="fixed z-50 min-w-44 rounded-card border border-line bg-surface py-1 shadow-lg"
        >
          {ordered.map((action) => (
            <button
              key={action.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setAt(null)
                action.onSelect()
              }}
              className={cn(
                'block w-full cursor-pointer px-3 py-1.5 text-left text-sm transition-colors',
                action.danger ? 'text-bad hover:bg-bad-soft' : 'text-fg hover:bg-bg',
              )}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </>
  )
}
