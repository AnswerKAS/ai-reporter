import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../../lib/api'
import { ApiError, chatReport, parsePhrase } from '../../lib/api'
import type { ComputedField, ReportDefinition, ReportField } from '../../types/semantic'
import { Alert, Button, Input, Modal, Textarea } from '../ui'
import { cn } from '../../lib/cn'

/**
 * Диалог о будущем отчёте.
 *
 * Отличие от прежнего «Собрать по описанию» не в модели, а в том, что
 * разговор продолжается: несогласие автора — не конец разбора, а следующая
 * реплика, и собеседник правит уже собранную раскладку, а не пересобирает её
 * с нуля. Поэтому текущее определение уходит вместе с перепиской.
 *
 * Переписка живёт в модалке, а предложение — на странице: разговаривают в
 * одном месте, смотрят в другом. Как только раскладка предложена, модалка
 * закрывается сама — иначе предпросмотр, ради которого всё и затевалось,
 * остаётся за ней. Компонент со страницы не снимается, поэтому переписка
 * переживает закрытие и «доработать» открывает её же, а не пустой лист.
 */
export function ReportChat({
  fields,
  computed,
  datasets,
  definition,
  isAdmin,
  saving,
  title,
  onTitle,
  onProposal,
  onRevert,
  onSave,
  onVocabulary,
}: {
  fields: ReportField[]
  computed: ComputedField[]
  datasets: string[]
  definition: ReportDefinition
  isAdmin: boolean
  saving: boolean
  title: string
  onTitle: (value: string) => void
  /** Применить предложение к раскладке; вызывающий запоминает прежнюю. */
  onProposal: (definition: ReportDefinition, title?: string | null) => void
  onRevert: () => void
  onSave: () => void
  /** Показать словарь отчёта: словами можно назвать только то, что в нём есть. */
  onVocabulary: () => void
}) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  /** Есть ли что подтверждать: предложение пришло и его ещё не откатили. */
  const [proposed, setProposed] = useState(false)
  /** Последняя реплика человека — её разбирает запасной путь без модели. */
  const [lastSaid, setLastSaid] = useState('')
  const tail = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (open) tail.current?.scrollIntoView({ block: 'nearest' })
  }, [messages, busy, open])

  const send = async () => {
    const text = draft.trim()
    if (!text || busy) return
    // реплика встаёт в переписку сразу: ответ идёт секунды, и всё это время
    // человек должен видеть, что его услышали
    const next: ChatMessage[] = [...messages, { role: 'user', text }]
    setMessages(next)
    setLastSaid(text)
    setDraft('')
    setError(null)
    setBusy(true)
    try {
      const answer = await chatReport(next, { fields, computed, datasets, definition })
      setMessages([...next, { role: 'assistant', text: answer.reply }])
      setModel(answer.model ?? null)
      if (answer.definition) {
        onProposal(answer.definition, answer.title)
        setProposed(true)
        // смотреть раскладку надо на странице, а не поверх неё
        setOpen(false)
      }
    } catch (err) {
      // реплику из переписки не убираем: она часть разговора, и повторять её
      // человеку заново незачем — можно просто отправить ещё раз
      setError(err instanceof ApiError ? err.message : 'не удалось получить ответ')
    } finally {
      setBusy(false)
    }
  }

  /** Запасной путь: словарь без модели.

      Диалога он не ведёт — просто разбирает последнюю реплику по названиям
      словаря. Нужен там, где ключа провайдера нет вовсе: без этой кнопки
      установка без модели осталась бы вообще без разбора описаний. */
  const parseWithoutModel = async () => {
    if (!lastSaid || busy) return
    setBusy(true)
    setError(null)
    try {
      const parsed = await parsePhrase(lastSaid, { fields, computed, datasets })
      onProposal(parsed.definition, null)
      setProposed(true)
      setModel(null)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: 'Разобрал по словарю, без модели — посмотрите раскладку ниже.' },
      ])
      setOpen(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось разобрать описание')
    } finally {
      setBusy(false)
    }
  }

  const revert = () => {
    onRevert()
    setProposed(false)
    setMessages((prev) => [...prev, { role: 'assistant', text: 'Вернул прежнюю раскладку.' }])
  }

  return (
    <>
      <section className="mt-3 flex flex-wrap items-center gap-2.5 rounded-card border border-line bg-surface px-3.5 py-3">
        <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">
          Отчёт по описанию
        </span>
        <Button variant="primary" onClick={() => setOpen(true)}>
          {messages.length ? 'Доработать в диалоге' : 'Опишите отчёт словами'}
        </Button>
        <span className="text-xs text-fg-muted">
          {model
            ? `собеседник — ${model}; выбирает только из вашего словаря`
            : 'скажете обычными словами, что нужно, — соберу и покажу; не то соберу — поправите'}
        </span>
        {/* словами можно назвать только то, что есть в словаре, — и он
            должен быть под рукой, а не угадываться по тексту ошибки */}
        <button
          type="button"
          aria-label="Показать словарь отчёта"
          title="Какие показатели и разрезы можно назвать"
          onClick={onVocabulary}
          className="flex size-5 cursor-pointer items-center justify-center rounded-full border border-line text-xs font-semibold text-fg-muted transition-colors hover:border-accent hover:text-accent"
        >
          ?
        </button>
      </section>

      {proposed && (
        <div className="mt-3 flex flex-col gap-2 rounded-card border border-accent bg-accent-soft p-3.5">
          <span className="text-sm">
            Раскладка ниже — предложение собеседника, предпросмотр показывает её на настоящих
            данных. Если всё так, сохраните отчёт; если нет — вернитесь в диалог и скажите,
            что поправить.
          </span>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Название отчёта
              <Input
                className="min-w-64"
                value={title}
                onChange={(e) => onTitle(e.target.value)}
                placeholder="Продажи по городам"
              />
            </label>
            {isAdmin ? (
              <Button variant="primary" onClick={onSave} disabled={saving || !title.trim()}>
                {saving ? 'Сохранение…' : 'Сохранить отчёт'}
              </Button>
            ) : (
              // право сохранять не двигается: говорим об этом до нажатия, а не
              // ошибкой после
              <span className="pb-1.5 text-xs text-fg-muted">
                Раскладка осталась в конструкторе — сохранить отчёт может администратор.
              </span>
            )}
            <Button onClick={() => setOpen(true)}>Доработать в диалоге</Button>
            <Button variant="ghost" onClick={revert}>
              Вернуть как было
            </Button>
          </div>
        </div>
      )}

      {open && (
        <Modal title="Отчёт по описанию" size="lg" onClose={() => setOpen(false)}>
          <div className="flex flex-col gap-2.5">
            {messages.length === 0 ? (
              <p className="max-w-prose text-sm text-fg-muted">
                Опишите обычными словами, что хотите видеть. Соберу отчёт целиком — итоги,
                динамику, разбивки и фильтры, — покажу предпросмотр, а дальше поправим по
                вашим замечаниям.
              </p>
            ) : (
              <div className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto rounded-control border border-line bg-bg p-2.5">
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={cn(
                      'max-w-[85%] rounded-card px-3 py-2 text-sm whitespace-pre-wrap',
                      m.role === 'user'
                        ? 'self-end bg-accent text-accent-fg'
                        : 'self-start border border-line bg-surface',
                    )}
                  >
                    {m.text}
                  </div>
                ))}
                {busy && (
                  <div className="self-start rounded-card border border-line bg-surface px-3 py-2 text-sm text-fg-muted">
                    Собираю отчёт, это занимает несколько секунд…
                  </div>
                )}
                <div ref={tail} />
              </div>
            )}

            <Textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter отправляет, Shift+Enter — перенос строки: диалог
                // набирают короткими репликами, тянуться к кнопке на каждую —
                // лишнее
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send()
                }
              }}
              rows={3}
              disabled={busy}
              placeholder={
                messages.length
                  ? 'что поправить? например «добавь разбивку по каналам» или «убери таблицу»'
                  : 'отчёт по продажам в разрезе городов'
              }
            />

            {error && (
              <Alert>
                {error}
                {lastSaid && (
                  <button
                    type="button"
                    className="ml-2 cursor-pointer underline"
                    onClick={() => void parseWithoutModel()}
                    disabled={busy}
                  >
                    разобрать по словарю без модели
                  </button>
                )}
              </Alert>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => void send()} disabled={busy || !draft.trim()}>
                {busy ? 'Собираю…' : messages.length ? 'Отправить' : 'Собрать отчёт'}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
                Закрыть
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
