import { useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type { DatasetLink, LinkInput } from '../../types/semantic'
import { createLink, deleteLink } from '../../lib/api'
import { Badge, Button, EmptyState, Field, Modal, Panel, PanelRow, Select, useConfirm } from '../ui'

const KINDS: Record<DatasetLink['kind'], string> = {
  inner: 'только совпавшие строки',
  left: 'все строки слева',
}

/** Связи датасетов: правило соединения, которое конструктор применяет сам,
    когда в секцию попадают показатели из разных датасетов. */
export function LinksPanel({
  links,
  datasets,
  busy,
  run,
}: {
  links: DatasetLink[]
  datasets: Dataset[]
  busy: boolean
  run: (action: () => Promise<unknown>, done?: string) => Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const { confirm, dialog } = useConfirm()
  const titleOf = (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug

  return (
    <Panel
      title="Связи между датасетами"
      count={links.length}
      description="Связь — правило соединения: по какому полю слева и справа строки считаются одной сущностью. Оба датасета должны жить на одном источнике и одном сервере: джойн выполняет сам источник."
      actions={
        <Button variant="primary" disabled={datasets.length < 2} onClick={() => setAdding(true)}>
          Новая связь
        </Button>
      }
    >
      {links.length === 0 ? (
        <EmptyState
          title="Связей нет"
          description="Показатели из разных датасетов пока нельзя показать в одной секции."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {links.map((link) => (
            <li key={link.id}>
              <PanelRow>
                <span className="flex flex-wrap items-center gap-2">
                  <strong>{titleOf(link.leftSlug)}</strong>
                  <code className="text-xs">{link.leftField}</code>
                  <span className="text-base text-accent" aria-hidden="true">
                    ⋈
                  </span>
                  <code className="text-xs">{link.rightField}</code>
                  <strong>{titleOf(link.rightSlug)}</strong>
                  <Badge>{KINDS[link.kind]}</Badge>
                  {link.title && <span className="text-fg-muted">{link.title}</span>}
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  className="ml-auto"
                  disabled={busy}
                  onClick={() =>
                    confirm({
                      title: 'Удалить связь?',
                      description: `Связь ${titleOf(link.leftSlug)} ⋈ ${titleOf(link.rightSlug)} будет удалена. Отчёты, соединяющие эти датасеты, перестанут собираться.`,
                      onConfirm: () => run(() => deleteLink(link.id), 'Связь удалена'),
                    })
                  }
                >
                  Удалить
                </Button>
              </PanelRow>
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <LinkModal
          datasets={datasets}
          busy={busy}
          onClose={() => setAdding(false)}
          onSubmit={(input) =>
            run(async () => {
              await createLink(input)
              setAdding(false)
            }, 'Связь создана')
          }
        />
      )}
      {dialog}
    </Panel>
  )
}

function LinkModal({
  datasets,
  busy,
  onClose,
  onSubmit,
}: {
  datasets: Dataset[]
  busy: boolean
  onClose: () => void
  onSubmit: (input: LinkInput) => void
}) {
  const [leftSlug, setLeftSlug] = useState(datasets[0]?.slug ?? '')
  const [rightSlug, setRightSlug] = useState(datasets[1]?.slug ?? '')
  const [leftField, setLeftField] = useState('')
  const [rightField, setRightField] = useState('')
  const [kind, setKind] = useState<DatasetLink['kind']>('inner')

  const fieldsOf = (slug: string) => datasets.find((d) => d.slug === slug)?.fields ?? []
  const leftFields = fieldsOf(leftSlug)
  const rightFields = fieldsOf(rightSlug)
  const left = leftField || leftFields[0]?.name || ''
  const right = rightField || rightFields[0]?.name || ''

  return (
    <Modal
      title="Новая связь"
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button
            variant="primary"
            disabled={busy || leftSlug === rightSlug || !left || !right}
            onClick={() => onSubmit({ leftSlug, rightSlug, leftField: left, rightField: right, kind })}
          >
            {busy ? 'Проверяем…' : 'Создать связь'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Слева">
            <Select
              value={leftSlug}
              onChange={(e) => {
                setLeftSlug(e.target.value)
                setLeftField('')
              }}
            >
              {datasets.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Поле слева">
            <Select value={left} onChange={(e) => setLeftField(e.target.value)}>
              {leftFields.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} · {f.type}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Справа">
            <Select
              value={rightSlug}
              onChange={(e) => {
                setRightSlug(e.target.value)
                setRightField('')
              }}
            >
              {datasets.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Поле справа">
            <Select value={right} onChange={(e) => setRightField(e.target.value)}>
              {rightFields.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} · {f.type}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Вид">
          <Select value={kind} onChange={(e) => setKind(e.target.value as DatasetLink['kind'])}>
            <option value="inner">{KINDS.inner}</option>
            <option value="left">{KINDS.left}</option>
          </Select>
        </Field>
        <p className="text-xs text-fg-muted">
          Связь принимается, только если оба датасета живут на одном источнике: джойн выполняет
          сам источник. И если по ключу справа окажется несколько строк на одну строку слева,
          конструктор откажется строить такую секцию — суммы бы раздулись.
        </p>
      </div>
    </Modal>
  )
}
