import { useEffect, useState } from 'react'
import type { MailServer, MailServerInput } from '../../types/user'
import {
  ApiError,
  createMailServer,
  deleteMailServer,
  fetchMailServers,
  patchMailServer,
  testMailServer,
} from '../../lib/api'
import { Alert, Badge, Button, Field, Input, Modal, Select, useConfirm } from '../ui'
import { AdminRow, AdminSection } from './AdminSection'

const KINDS = [
  { value: 'gmail', label: 'Gmail' },
  { value: 'exchange', label: 'Exchange / Microsoft 365' },
  { value: 'smtp', label: 'Другой SMTP' },
] as const

const empty: MailServerInput = { title: '', kind: 'gmail', fromEmail: '', isDefault: true }

const STATUS: Record<MailServer['status'], { tone: 'good' | 'bad' | 'neutral'; label: string }> = {
  ok: { tone: 'good', label: 'проверен' },
  error: { tone: 'bad', label: 'ошибка' },
  new: { tone: 'neutral', label: 'не проверен' },
}

/** Почтовые серверы рассылки — раздел администратора.

    Пароль ящика вводится здесь и больше никогда не показывается: наружу
    сервер отдаётся без него, как и DSN датасета. Для Gmail и Exchange хост
    с портом подставляются сами — администратору незачем их помнить.

    Форма живёт в модалке, а строка сервера показывает состояние: куда шлёт,
    проверен ли и что ответил сервер в последний раз. */
export function MailServersPanel({ onCount }: { onCount?: (count: number) => void }) {
  const [servers, setServers] = useState<MailServer[] | null>(null)
  const [form, setForm] = useState<MailServerInput | null>(null)
  // правка существующего сервера: та же форма, но пароль меняется только
  // если его ввели заново — хранится он на сервере и наружу не выдаётся
  const [editing, setEditing] = useState<MailServer | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testTo, setTestTo] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { confirm, dialog } = useConfirm()

  const load = async () => {
    try {
      const data = await fetchMailServers()
      setServers(data.servers)
      onCount?.(data.servers.length)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось загрузить серверы')
      setServers([])
    }
  }

  useEffect(() => {
    // грузим один раз: список меняется только действиями на этой же странице
    void load()
  }, [])

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      await load()
      if (done) setNotice(done)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не получилось')
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (s: MailServer) => {
    setEditing(s)
    setForm({
      title: s.title,
      kind: s.kind,
      host: s.host,
      port: s.port,
      security: s.security,
      username: s.username ?? '',
      password: '',
      fromEmail: s.from_email,
      fromName: s.from_name ?? '',
      isDefault: s.is_default,
    })
    setNotice(null)
    setError(null)
  }

  const close = () => {
    setForm(null)
    setEditing(null)
  }

  return (
    <AdminSection
      title="Почтовые серверы"
      count={servers?.length}
      description="Ящик, из которого уходят отчёты по расписанию. Сотрудники видят только название сервера: адрес, логин и пароль остаются здесь. Для Gmail нужен пароль приложения, для Microsoft 365 — учётная запись с разрешённой SMTP-аутентификацией."
      actions={
        <Button variant="primary" onClick={() => setForm(empty)}>
          Добавить сервер
        </Button>
      }
    >
      {error && <Alert className="mb-3">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-3">
          {notice}
        </Alert>
      )}

      {servers && servers.length === 0 && (
        <p className="text-sm text-fg-muted">
          Серверов нет — рассылки отчётов уходить не будут, пока не заведён хотя бы один.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {(servers ?? []).map((s) => (
          <li key={s.id}>
            <AdminRow className="flex-col items-stretch gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <strong>{s.title}</strong>
                {s.is_default && <Badge tone="accent">по умолчанию</Badge>}
                <Badge tone={STATUS[s.status].tone}>{STATUS[s.status].label}</Badge>
                <span className="ml-auto flex flex-wrap items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setTesting(testing === s.id ? null : s.id)}
                  >
                    Проверить
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => startEdit(s)}>
                    Изменить
                  </Button>
                  {!s.is_default && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => run(() => patchMailServer(s.id, { isDefault: true }), 'Сервер стал основным')}
                    >
                      Сделать основным
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy}
                    onClick={() =>
                      confirm({
                        title: 'Удалить сервер?',
                        description: `«${s.title}» будет удалён. Рассылки, привязанные к нему, уйдут через сервер по умолчанию.`,
                        onConfirm: () => run(() => deleteMailServer(s.id), 'Сервер удалён'),
                      })
                    }
                  >
                    Удалить
                  </Button>
                </span>
              </div>

              <p className="text-xs text-fg-muted">
                {s.host}:{s.port} · {s.security === 'none' ? 'без шифрования' : s.security.toUpperCase()} ·
                отправитель {s.from_name ? `${s.from_name} <${s.from_email}>` : s.from_email}
                {s.username && ` · логин ${s.username}`}
              </p>
              {s.status === 'error' && s.error && <p className="text-xs text-bad">{s.error}</p>}

              {testing === s.id && (
                <div className="flex flex-wrap items-center gap-2 rounded-control bg-surface-sunken p-2">
                  <Input
                    className="w-auto min-w-56 flex-1 py-1.5"
                    type="email"
                    placeholder="адрес для проверочного письма"
                    aria-label={`Адрес для проверки сервера ${s.title}`}
                    value={testTo[s.id] ?? ''}
                    onChange={(e) => setTestTo({ ...testTo, [s.id]: e.target.value })}
                  />
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={busy || !(testTo[s.id] ?? '').trim()}
                    onClick={() =>
                      run(() => testMailServer(s.id, testTo[s.id]), 'Проверочное письмо отправлено')
                    }
                  >
                    Отправить письмо
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => setTesting(null)}>
                    Отмена
                  </Button>
                </div>
              )}
            </AdminRow>
          </li>
        ))}
      </ul>

      {form && (
        <ServerModal
          form={form}
          editing={editing}
          busy={busy}
          onChange={setForm}
          onClose={close}
          onSubmit={() =>
            run(async () => {
              if (editing) {
                // пустое поле пароля означает «оставить прежний»,
                // поэтому в запрос оно не попадает вовсе
                const { password, kind: _kind, ...rest } = form
                await patchMailServer(editing.id, password ? { ...rest, password } : rest)
              } else {
                await createMailServer(form)
              }
              close()
            }, editing ? 'Сервер изменён' : 'Сервер добавлен')
          }
        />
      )}
      {dialog}
    </AdminSection>
  )
}

function ServerModal({
  form,
  editing,
  busy,
  onChange,
  onClose,
  onSubmit,
}: {
  form: MailServerInput
  editing: MailServer | null
  busy: boolean
  onChange: (form: MailServerInput) => void
  onClose: () => void
  onSubmit: () => void
}) {
  const custom = form.kind === 'smtp'
  return (
    <Modal
      title={editing ? `Правка сервера «${editing.title}»` : 'Новый почтовый сервер'}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button
            variant="primary"
            disabled={busy || !form.title.trim() || !form.fromEmail.trim()}
            onClick={onSubmit}
          >
            {busy ? 'Сохраняем…' : editing ? 'Сохранить' : 'Добавить сервер'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Название" hint="Его увидят сотрудники в списке рассылок.">
          <Input
            value={form.title}
            placeholder="Почта отдела"
            autoFocus
            onChange={(e) => onChange({ ...form, title: e.target.value })}
          />
        </Field>
        <Field label="Тип">
          <Select
            value={form.kind}
            disabled={Boolean(editing)}
            onChange={(e) => onChange({ ...form, kind: e.target.value as MailServerInput['kind'] })}
          >
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>
        {custom && (
          <>
            <Field label="Сервер">
              <Input
                value={form.host ?? ''}
                placeholder="smtp.company.ru"
                onChange={(e) => onChange({ ...form, host: e.target.value })}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Порт">
                <Input
                  type="number"
                  value={form.port ?? 587}
                  onChange={(e) => onChange({ ...form, port: Number(e.target.value) })}
                />
              </Field>
              <Field label="Защита">
                <Select
                  value={form.security ?? 'starttls'}
                  onChange={(e) =>
                    onChange({ ...form, security: e.target.value as MailServerInput['security'] })
                  }
                >
                  <option value="starttls">STARTTLS</option>
                  <option value="ssl">SSL</option>
                  <option value="none">без шифрования</option>
                </Select>
              </Field>
            </div>
          </>
        )}
        <Field label="Логин">
          <Input
            value={form.username ?? ''}
            placeholder="reports@company.ru"
            onChange={(e) => onChange({ ...form, username: e.target.value })}
          />
        </Field>
        <Field label={editing ? 'Пароль (пусто — не менять)' : 'Пароль'}>
          <Input
            type="password"
            value={form.password ?? ''}
            autoComplete="new-password"
            placeholder={editing ? '••••••' : undefined}
            onChange={(e) => onChange({ ...form, password: e.target.value })}
          />
        </Field>
        <Field label="Отправитель">
          <Input
            value={form.fromEmail}
            placeholder="reports@company.ru"
            onChange={(e) => onChange({ ...form, fromEmail: e.target.value })}
          />
        </Field>
        <Field label="Имя отправителя">
          <Input
            value={form.fromName ?? ''}
            placeholder="Отчёты"
            onChange={(e) => onChange({ ...form, fromName: e.target.value })}
          />
        </Field>
      </div>
    </Modal>
  )
}
