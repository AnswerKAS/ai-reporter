import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../../lib/api'
import { ApiError, fetchReportChatHistory, parsePhrase, streamReportChat } from '../../lib/api'
import type { ComputedField, ReportDefinition, ReportField } from '../../types/semantic'
import type { Dataset } from '../../types/dataset'
import { Alert, Button, Input, Modal, Textarea } from '../ui'
import { cn } from '../../lib/cn'
import { DatasetDataDialog } from './DatasetDataDialog'

/**
 * Диалог о будущем отчёте.
 *
 * Отличие от прежнего «Собрать по описанию» не в модели, а в том, что
 * разговор продолжается: несогласие автора — не конец разбора, а следующая
 * реплика, и собеседник правит уже собранную раскладку, а не пересобирает её
 * с нуля. Поэтому текущее определение уходит вместе с перепиской.
 *
 * Переписка показывается в модалке и сохраняется сервером, а предложение —
 * на странице. Как только раскладка предложена, модалка закрывается; при
 * повторном открытии или обновлении страницы реплики восстанавливаются.
 */
export function ReportChat({
  fields,
  computed,
  datasets,
  availableDatasets,
  definition,
  suggestedPrompt,
  saving,
  title,
  onTitle,
  onProposal,
  onRevert,
  onSave,
  onVocabulary,
  compact = false,
  target,
}: {
  fields: ReportField[]
  computed: ComputedField[]
  datasets: string[]
  availableDatasets: Dataset[]
  definition: ReportDefinition
  suggestedPrompt?: { id: number; text: string } | null
  saving: boolean
  title: string
  onTitle: (value: string) => void
  /** Применить предложение к раскладке; вызывающий запоминает прежнюю. */
  onProposal: (definition: ReportDefinition, title?: string | null) => void
  onRevert: () => void
  onSave: () => void
  /** Показать словарь отчёта: словами можно назвать только то, что в нём есть. */
  onVocabulary: () => void
  compact?: boolean
  target: string
}) {
  const [open, setOpen] = useState(false)
  const [dataOpen, setDataOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [parserMode, setParserMode] = useState(false)
  const [progress, setProgress] = useState('')
  const [streamedReply, setStreamedReply] = useState('')
  /** Есть ли что подтверждать: предложение пришло и его ещё не откатили. */
  const [proposed, setProposed] = useState(false)
  /** Последняя реплика человека — её разбирает запасной путь без модели. */
  const [lastSaid, setLastSaid] = useState('')
  const tail = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    void fetchReportChatHistory(target).then((saved) => {
      if (!active) return
      setConversationId(saved.conversationId)
      setMessages(saved.messages)
    }).catch(() => { /* Chat stays usable when history is unavailable. */ })
    return () => { active = false }
  }, [target])

  // Переход из ответа по датасету открывает тот же диалог с готовым вопросом.
  useEffect(() => {
    if (!suggestedPrompt) return
    setDraft(suggestedPrompt.text)
    setOpen(true)
  }, [suggestedPrompt])

  useEffect(() => {
    if (open) tail.current?.scrollIntoView({ block: 'nearest' })
  }, [messages, busy, open])

  /** Open the saved conversation without fetching preset report layouts. */
  const openDialog = () => {
    setOpen(true)
  }

  /** Send one turn and apply only the completed agent proposal. */
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
    setProgress('Изучаю запрос…')
    setStreamedReply('')
    setBusy(true)
    try {
      await streamReportChat(next, { fields, computed, datasets, definition,
        conversationId, target }, (event) => {
        if (event.type === 'status') setProgress(event.text ?? '')
        if (event.type === 'delta') setStreamedReply((value) => value + (event.text ?? ''))
        if (event.type === 'error') throw new Error(event.message ?? 'не удалось собрать отчёт')
        if (event.type === 'done' && event.result) {
          const answer = event.result
          setConversationId(event.conversationId ?? null)
          setMessages([...next, { role: 'assistant', text: answer.reply }])
          setModel(answer.model ?? null)
          setParserMode(answer.source === 'parser')
          if (answer.definition) {
            onProposal(answer.definition, answer.title)
            setProposed(true)
            setOpen(false)
          }
        }
      })
    } catch (err) {
      // реплику из переписки не убираем: она часть разговора, и повторять её
      // человеку заново незачем — можно просто отправить ещё раз
      setError(err instanceof ApiError ? err.message : 'не удалось получить ответ')
    } finally {
      setBusy(false)
      setProgress('')
      setStreamedReply('')
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
      setParserMode(true)
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
      <section className={cn('rounded-card border border-line bg-surface', compact ? 'mt-3 px-4 py-3' : 'mt-6 p-5 shadow-card sm:p-6')}>
        {!compact && <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">02 · Отчёт по данным</p>}
        <div className={cn('flex flex-wrap items-center justify-between gap-3', !compact && 'mt-2 items-start gap-4')}>
          <div className="max-w-2xl">
            <h2 className={cn('font-semibold tracking-tight', compact ? 'text-sm' : 'text-xl')}>{compact ? 'Доработать отчёт' : 'Соберите отчёт из выбранных данных'}</h2>
            {!compact && <p className="mt-2 text-sm text-fg-muted">
              {model
                ? `Опишите результат своими словами. Собеседник ${model} выбирает только доступные поля.`
                : parserMode
                  ? 'Разбор по словарю работает без модели: назовите показатель и разрез.'
                  : 'Опишите постоянный отчёт своими словами. Агент соберёт и проверит его карточки перед сохранением.'}
            </p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={openDialog}>
              {parserMode && messages.length
                ? 'Уточнить описание'
                : messages.length ? 'Доработать в диалоге' : 'Описать отчёт'}
            </Button>
            <Button onClick={() => setDataOpen(true)}>Посмотреть данные</Button>
            <button type="button" aria-label="Показать словарь отчёта"
              title="Какие показатели и разрезы можно назвать" onClick={onVocabulary}
              className="flex size-10 cursor-pointer items-center justify-center rounded-control border border-line text-sm font-semibold text-fg-muted hover:border-accent hover:text-accent">?</button>
          </div>
        </div>
      </section>

      {dataOpen && <DatasetDataDialog datasets={availableDatasets} selectedSlugs={datasets}
        onClose={() => setDataOpen(false)} />}

      {proposed && (
        <div className={cn('mt-3 flex gap-2 rounded-card border border-accent bg-accent-soft p-3.5', compact ? 'flex-wrap items-center justify-between' : 'flex-col')}>
          <span className="text-sm">{compact ? 'Предложенная раскладка готова к проверке.' :
            `Раскладка ниже собрана ${parserMode ? 'по словарю без модели' : 'собеседником'}. Предпросмотр показывает её на настоящих данных. Проверьте и сохраните отчёт или уточните описание.`}</span>
          <div className="flex flex-wrap items-end gap-2">
            {!compact && <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Название отчёта
              <Input
                className="min-w-64"
                value={title}
                onChange={(e) => onTitle(e.target.value)}
                placeholder="Продажи по городам"
              />
            </label>}
            {!compact && <Button variant="primary" onClick={onSave} disabled={saving || !title.trim()}>
              {saving ? 'Сохранение…' : 'Сохранить отчёт'}
            </Button>}
            <Button onClick={openDialog}>
              {parserMode ? 'Уточнить описание' : 'Доработать в диалоге'}
            </Button>
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
                Опишите, какой постоянный отчёт нужен. Агент соберёт карточки, графики,
                таблицы и фильтры, проверит их на данных и покажет раскладку ниже.
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
                    {streamedReply || progress || 'Собираю отчёт…'}
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
                parserMode
                  ? 'например «выручка по городам столбцами»'
                  : messages.length
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
