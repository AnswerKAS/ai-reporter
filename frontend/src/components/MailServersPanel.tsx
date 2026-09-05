import { useEffect, useState } from 'react'
import type { MailServer, MailServerInput } from '../types/user'
import {
  ApiError,
  createMailServer,
  deleteMailServer,
  fetchMailServers,
  patchMailServer,
  testMailServer,
} from '../lib/api'
import { Alert, Badge, Button, Field, Input, Select, useConfirm } from './ui'

const KINDS = [
  { value: 'gmail', label: 'Gmail' },
  { value: 'exchange', label: 'Exchange / Microsoft 365' },
  { value: 'smtp', label: 'Другой SMTP' },
] as const

const empty: MailServerInput = { title: '', kind: 'gmail', fromEmail: '', isDefault: true }

/** Почтовые серверы рассылки — раздел администратора.

    Пароль ящика вводится здесь и больше никогда не показывается: наружу
    сервер отдаётся без него, как и DSN датасета. Для Gmail и Exchange хост
    с портом подставляются сами — администратору незачем их помнить. */
export function MailServersPanel() {
  const [servers, setServers] = useState<MailServer[] | null>(null)
  const [form, setForm] = useState<MailServerInput>(empty)
  // правка существующего сервера: та же форма, но пароль меняется только
  // если его ввели заново — хранится он на сервере и наружу не выдаётся
  const [editing, setEditing] = useState<MailServer | null>(null)
  const [testTo, setTestTo] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { confirm, dialog } = useConfirm()

  const load = async () => {
    try {
      const data = await fetchMailServers()
      setServers(data.servers)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось загрузить серверы')
      setServers([])
    }
  }

  useEffect(() => {
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

  const custom = form.kind === 'smtp'

  return (
    <section className="mb-7">
      <h2 className="mb-2 text-lg font-semibold tracking-tight">Почтовые серверы</h2>
      <p className="mb-3 max-w-prose text-sm text-fg-muted">
        Ящик, из которого уходят отчёты по расписанию. Сотрудники видят только название сервера:
        адрес, логин и пароль остаются здесь. Для Gmail нужен пароль приложения, для Microsoft 365 —
        учётная запись с разрешённой SMTP-аутентификацией.
      </p>

      {error && <Alert className="mb-3">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-3">
          {notice}
        </Alert>
      )}

      {servers && servers.length > 0 && (
        <ul className="mb-4 flex flex-col gap-2">
          {servers.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 rounded-control border border-line px-3 py-2 text-sm">
              <span className="font-semibold">{s.title}</span>
              <span className="text-fg-muted">
                {s.host}:{s.port} · {s.from_email}
              </span>
              {s.is_default && <Badge>по умолчанию</Badge>}
              {s.status === 'ok' && <Badge tone="good">проверен</Badge>}
              {s.status === 'error' && <Badge tone="bad">{s.error}</Badge>}
              <span className="ml-auto flex flex-wrap items-center gap-1">
                <Input
                  fit
                  className="py-1.5"
                  placeholder="адрес для проверки"
                  value={testTo[s.id] ?? ''}
                  onChange={(e) => setTestTo({ ...testTo, [s.id]: e.target.value })}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || !(testTo[s.id] ?? '').trim()}
                  onClick={() => run(() => testMailServer(s.id, testTo[s.id]), 'Проверочное письмо отправлено')}
                >
                  Проверить
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
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
                  }}
                >
                  Изменить
                </Button>
                {!s.is_default && (
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => run(() => patchMailServer(s.id, { isDefault: true }))}>
                    Сделать основным
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
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
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-3 rounded-card border border-line bg-surface p-3.5">
        <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">
          {editing ? `Правка сервера «${editing.title}»` : 'Новый сервер'}
        </span>
        <div className="flex flex-wrap items-end gap-3">
        <Field label="Название">
          <Input fit value={form.title} placeholder="Почта отдела"
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Тип">
          <Select fit value={form.kind} disabled={Boolean(editing)}
            onChange={(e) => setForm({ ...form, kind: e.target.value as MailServerInput['kind'] })}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </Select>
        </Field>
        {custom && (
          <>
            <Field label="Сервер">
              <Input fit value={form.host ?? ''} placeholder="smtp.company.ru"
                onChange={(e) => setForm({ ...form, host: e.target.value })} />
            </Field>
            <Field label="Порт">
              <Input fit type="number" value={form.port ?? 587}
                onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
            </Field>
            <Field label="Защита">
              <Select fit value={form.security ?? 'starttls'}
                onChange={(e) => setForm({ ...form, security: e.target.value as MailServerInput['security'] })}>
                <option value="starttls">STARTTLS</option>
                <option value="ssl">SSL</option>
                <option value="none">без шифрования</option>
              </Select>
            </Field>
          </>
        )}
        <Field label="Логин">
          <Input fit value={form.username ?? ''} placeholder="reports@company.ru"
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </Field>
        <Field label={editing ? 'Пароль (пусто — не менять)' : 'Пароль'}>
          <Input fit type="password" value={form.password ?? ''} autoComplete="new-password"
            placeholder={editing ? '••••••' : undefined}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        <Field label="Отправитель">
          <Input fit value={form.fromEmail} placeholder="reports@company.ru"
            onChange={(e) => setForm({ ...form, fromEmail: e.target.value })} />
        </Field>
        <Field label="Имя отправителя">
          <Input fit value={form.fromName ?? ''} placeholder="Отчёты"
            onChange={(e) => setForm({ ...form, fromName: e.target.value })} />
        </Field>
        <Button
          variant="primary"
          disabled={busy || !form.title.trim() || !form.fromEmail.trim()}
          onClick={() =>
            run(async () => {
              if (editing) {
                // пустое поле пароля означает «оставить прежний»,
                // поэтому в запрос оно не попадает вовсе
                const { password, kind: _kind, ...rest } = form
                await patchMailServer(editing.id, password ? { ...rest, password } : rest)
                setEditing(null)
              } else {
                await createMailServer(form)
              }
              setForm(empty)
            }, editing ? 'Сервер изменён' : 'Сервер добавлен')
          }
        >
          {busy ? 'Сохраняем…' : editing ? 'Сохранить' : 'Добавить сервер'}
        </Button>
        {editing && (
          <Button variant="ghost" disabled={busy}
            onClick={() => { setEditing(null); setForm(empty) }}>
            Отмена
          </Button>
        )}
        </div>
      </div>
      {dialog}
    </section>
  )
}
