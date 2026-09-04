import { useState } from 'react'
import { Modal } from './Modal'
import { Button } from './Button'
import { Alert } from './Alert'

/**
 * Замена window.confirm для необратимых действий: называет объект,
 * показывает ошибку на месте (раньше был alert) и не даёт нажать дважды.
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Удалить',
  onConfirm,
  onClose,
}: {
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => Promise<void> | void
  onClose: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'не удалось выполнить действие')
      setBusy(false)
    }
  }

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="danger" disabled={busy} onClick={run}>
            {busy ? 'Удаляем…' : confirmLabel}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <p className="text-sm text-fg-muted">{description}</p>
      {error && <Alert className="mt-3">{error}</Alert>}
    </Modal>
  )
}
