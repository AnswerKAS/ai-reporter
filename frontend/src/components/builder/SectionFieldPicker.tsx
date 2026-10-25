import { useMemo, useState } from 'react'
import { Button, Input, Modal } from '../ui'

export interface SectionFieldChoice {
  key: string
  title: string
  dataset: string
  hint: string
  unavailable?: string
}

/** Показывает доступные поля для одного блока отчёта с поиском по названию и датасету. */
export function SectionFieldPicker({
  kind,
  blockNumber,
  choices,
  onPick,
  onChangeData,
  onClose,
}: {
  kind: 'metric' | 'dimension'
  blockNumber: number
  choices: SectionFieldChoice[]
  onPick: (key: string) => void
  onChangeData: () => void
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const name = kind === 'metric' ? 'показатель' : 'разрез'
  const matching = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru')
    return needle ? choices.filter((choice) =>
      [choice.title, choice.dataset, choice.hint].some((value) => value.toLocaleLowerCase('ru').includes(needle)),
    ) : choices
  }, [choices, search])
  const groups = useMemo(() => [...new Set(matching.map((choice) => choice.dataset))], [matching])

  return (
    <Modal title={`Добавить ${name} · блок ${blockNumber}`} size="lg" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-fg-muted">
          {kind === 'metric'
            ? 'Показатель определяет, какое число будет рассчитано в этом блоке.'
            : 'Разрез определяет, по чему разбить данные этого блока.'}
        </p>
        <Input type="search" aria-label={`Поиск: ${name}`} placeholder="Найти поле или датасет"
          value={search} onChange={(event) => setSearch(event.target.value)} />
        {matching.length === 0 ? (
          <p className="text-sm text-fg-muted">
            {search.trim() ? 'По этому запросу полей нет. Попробуйте другое название.'
              : `Все доступные ${kind === 'metric' ? 'показатели' : 'разрезы'} уже добавлены в этот блок. Чтобы появились другие, измените набор данных отчёта.`}
          </p>
        ) : (
          <div className="space-y-4">
            {groups.map((dataset) => (
              <section key={dataset}>
                <h3 className="mb-2 text-xs font-semibold text-fg-muted">{dataset}</h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {matching.filter((choice) => choice.dataset === dataset).map((choice) => (
                    <Button key={choice.key} className="min-w-0 flex-col items-start gap-0.5 py-2 text-left"
                      data-field-choice={choice.key}
                      disabled={Boolean(choice.unavailable)}
                      title={choice.unavailable || choice.hint}
                      onClick={() => { onPick(choice.key); onClose() }}>
                      <span className="max-w-full truncate font-medium">{choice.title}</span>
                      <span className="max-w-full truncate text-xs text-fg-muted">
                        {choice.unavailable || choice.hint}
                      </span>
                    </Button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
        <Button size="sm" onClick={onChangeData}>Нужно другое поле? Изменить данные</Button>
      </div>
    </Modal>
  )
}
