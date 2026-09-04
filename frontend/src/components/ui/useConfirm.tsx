import { useCallback, useState, type ReactNode } from 'react'
import { ConfirmDialog } from './ConfirmDialog'

interface ConfirmRequest {
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => Promise<void> | void
}

/**
 * Замена window.confirm там, где подтверждений на странице несколько.
 * Возвращает функцию запроса и сам диалог — его надо отрисовать один раз.
 */
export function useConfirm(): { confirm: (req: ConfirmRequest) => void; dialog: ReactNode } {
  const [request, setRequest] = useState<ConfirmRequest | null>(null)
  const confirm = useCallback((req: ConfirmRequest) => setRequest(req), [])

  const dialog = request ? (
    <ConfirmDialog
      title={request.title}
      description={request.description}
      confirmLabel={request.confirmLabel}
      onConfirm={request.onConfirm}
      onClose={() => setRequest(null)}
    />
  ) : null

  return { confirm, dialog }
}
