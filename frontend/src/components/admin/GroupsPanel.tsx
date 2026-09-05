import { useState } from 'react'
import type { Group, User } from '../../types/user'
import {
  adminAddMember,
  adminCreateGroup,
  adminDeleteGroup,
  adminRemoveMember,
} from '../../lib/api'
import { Badge, Button, EmptyState, Field, Input, Modal, Select, useConfirm } from '../ui'
import { AdminSection } from './AdminSection'

/** Группы: состав правится прямо в карточке — участника видно чипом, и там же
    крестик, чтобы его убрать (раньше состав был строкой через запятую, а
    исключить человека из группы было нельзя вовсе). */
export function GroupsPanel({
  groups,
  users,
  groupReports,
  onChanged,
  onFail,
}: {
  groups: Group[]
  users: User[]
  /** slug'и отчётов, назначенных группе; null — назначения ещё грузятся. */
  groupReports: Record<string, string[]> | null
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const { confirm, dialog } = useConfirm()

  const shown = groups.filter((g) => g.name.toLowerCase().includes(query.trim().toLowerCase()))

  return (
    <AdminSection
      title="Группы"
      count={groups.length}
      description="Группа — способ выдать один отчёт сразу отделу: доступ назначается группе, а состав меняется здесь."
      actions={
        <Button variant="primary" onClick={() => setCreating(true)}>
          Создать группу
        </Button>
      }
      toolbar={
        <Input
          className="w-auto min-w-56 flex-1 py-1.5"
          type="search"
          placeholder="Поиск по названию"
          aria-label="Поиск группы"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      }
    >
      {shown.length === 0 ? (
        <EmptyState
          title={groups.length === 0 ? 'Групп пока нет' : 'Ничего не нашлось'}
          description={
            groups.length === 0
              ? 'Заведите группу — и назначайте отчёты сразу отделу, а не каждому сотруднику отдельно.'
              : 'Измените запрос.'
          }
        />
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3">
          {shown.map((g) => {
            const memberIds = new Set(g.members.map((m) => m.id))
            const candidates = users.filter((u) => !memberIds.has(u.id))
            const reports = groupReports?.[g.id] ?? []
            return (
              <li
                key={g.id}
                className="flex flex-col gap-3 rounded-control border border-line p-3.5"
              >
                <header className="flex flex-wrap items-center gap-2">
                  <strong className="text-sm">{g.name}</strong>
                  <Badge>{g.members.length} чел.</Badge>
                  <Badge tone={reports.length > 0 ? 'accent' : 'neutral'}>
                    {groupReports ? `отчётов: ${reports.length}` : 'отчёты: считаем…'}
                  </Badge>
                  <Button
                    variant="danger"
                    size="sm"
                    className="ml-auto"
                    onClick={() =>
                      confirm({
                        title: 'Удалить группу?',
                        description: `«${g.name}» будет удалена вместе с назначенными на неё отчётами (${reports.length}). Сами пользователи останутся, но доступ через эту группу потеряют.`,
                        onConfirm: async () => {
                          await adminDeleteGroup(g.id)
                          await onChanged()
                        },
                      })
                    }
                  >
                    Удалить
                  </Button>
                </header>

                {g.members.length === 0 ? (
                  <p className="text-xs text-fg-muted">Пока никого — добавьте участников ниже.</p>
                ) : (
                  <ul className="flex flex-wrap gap-1.5">
                    {g.members.map((m) => (
                      <li key={m.id}>
                        <span className="inline-flex items-center gap-1 rounded-full border border-line bg-bg py-0.5 pr-1 pl-2.5 text-xs">
                          {m.username}
                          <button
                            type="button"
                            aria-label={`Убрать ${m.username} из группы ${g.name}`}
                            title="Убрать из группы"
                            className="cursor-pointer rounded-full px-1 text-sm leading-none text-fg-muted hover:bg-bad-soft hover:text-bad"
                            onClick={async () => {
                              try {
                                await adminRemoveMember(g.id, m.id)
                                await onChanged()
                              } catch (err) {
                                onFail(err)
                              }
                            }}
                          >
                            <span aria-hidden="true">×</span>
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                <Select
                  className="py-1.5 text-xs"
                  aria-label={`Добавить участника в группу ${g.name}`}
                  value=""
                  disabled={candidates.length === 0}
                  onChange={async (e) => {
                    if (!e.target.value) return
                    try {
                      await adminAddMember(g.id, e.target.value)
                      await onChanged()
                    } catch (err) {
                      onFail(err)
                    }
                  }}
                >
                  <option value="">
                    {candidates.length === 0 ? 'все пользователи уже в группе' : '+ добавить участника…'}
                  </option>
                  {candidates.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username}
                    </option>
                  ))}
                </Select>
              </li>
            )
          })}
        </ul>
      )}

      {creating && (
        <CreateGroupModal
          onClose={() => setCreating(false)}
          onCreated={async () => {
            await onChanged()
            setCreating(false)
          }}
          onFail={onFail}
        />
      )}
      {dialog}
    </AdminSection>
  )
}

function CreateGroupModal({
  onClose,
  onCreated,
  onFail,
}: {
  onClose: () => void
  onCreated: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await adminCreateGroup(name.trim())
      await onCreated()
    } catch (err) {
      onFail(err)
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Новая группа"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !name.trim()} onClick={submit}>
            {busy ? 'Создаём…' : 'Создать'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <Field label="Название" hint="Обычно это отдел: «Продажи», «Логистика», «Дирекция».">
        <Input
          value={name}
          autoFocus
          placeholder="Продажи"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && name.trim()) void submit()
          }}
        />
      </Field>
    </Modal>
  )
}
