import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Group, User } from '../../types/user'
import { adminAccessTagDetails, adminSetAccessTags, adminTagCatalog, adminTagUsage, type AccessTagDetails, type TagCatalogItem, type TagUsage } from '../../lib/api'
import { useReports } from '../../lib/reports'
import { TagPicker } from '../TagPicker'
import { Alert, Badge, Button, Field, Input, Modal, Panel, Select, Skeleton } from '../ui'

/** Explain labels, show their usage, and edit direct permissions alongside inherited grants. */
export function AccessTagsPanel({ users, groups }: { users: User[]; groups: Group[] }) {
  const { reload } = useReports()
  const [catalog, setCatalog] = useState<TagCatalogItem[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [kind, setKind] = useState<'user' | 'group'>('user')
  const [id, setId] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [details, setDetails] = useState<AccessTagDetails | null>(null)
  const [loadedTarget, setLoadedTarget] = useState('')
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [usageTag, setUsageTag] = useState<string | null>(null)
  const [usage, setUsage] = useState<TagUsage | null>(null)
  const [usageError, setUsageError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    adminTagCatalog(controller.signal).then((next) => { if (!controller.signal.aborted) setCatalog(next) })
      .catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Не удалось прочитать каталог меток') })
      .finally(() => { if (!controller.signal.aborted) setCatalogLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    adminAccessTagDetails(kind, id, controller.signal).then((next) => {
      if (controller.signal.aborted) return
      setTags(next.tags); setDetails(next); setLoadedTarget(`${kind}:${id}`); setError(null)
    }).catch((err) => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Не удалось прочитать назначения') })
    return () => controller.abort()
  }, [kind, id])

  useEffect(() => {
    if (usageTag === null) return
    const controller = new AbortController()
    adminTagUsage(usageTag, controller.signal).then((next) => { if (!controller.signal.aborted) setUsage(next) })
      .catch((err) => { if (!controller.signal.aborted) setUsageError(err instanceof Error ? err.message : 'Не удалось прочитать применение метки') })
    return () => controller.abort()
  }, [usageTag])

  /** Clear stale assignment state whenever the user switches person or group. */
  const selectTarget = (nextKind: 'user' | 'group', nextId: string) => {
    setKind(nextKind); setId(nextId); setTags([]); setDetails(null); setLoadedTarget(''); setNotice(null)
  }

  /** Save direct grants while leaving inherited group permissions intact. */
  const save = async () => {
    if (!id || loadedTarget !== `${kind}:${id}`) return
    setBusy(true); setError(null); setNotice(null)
    try {
      await adminSetAccessTags(kind, id, tags)
      const [nextCatalog, nextDetails] = await Promise.all([adminTagCatalog(), adminAccessTagDetails(kind, id), reload()])
      setCatalog(nextCatalog); setDetails(nextDetails); setTags(nextDetails.tags)
      setNotice('Метки сохранены. Доступ по ним действует сразу.')
    } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось сохранить метки') }
    finally { setBusy(false) }
  }

  const selectedUsage = catalog.find((item) => item.tag === usageTag)
  const available = catalog.map((item) => item.tag)
  const canEdit = Boolean(id) && loadedTarget === `${kind}:${id}` && !busy
  return <div className="space-y-5">
    <Panel title="Как работают метки" description="Одна метка связывает тему отчёта и аудиторию, которой разрешён его просмотр.">
      <ol className="list-decimal space-y-2 pl-5 text-sm text-fg-muted">
        <li>Поставьте метку отчёту: <Link to="/reports" className="text-accent hover:underline">Отчёты</Link> → меню строки → «Изменить метки». Это может сделать автор или администратор.</li>
        <li>Здесь выберите пользователя или группу и назначьте ту же разрешённую метку.</li>
        <li>Пользователь увидит все отчёты с совпадающей меткой. Участники группы получают её разрешения автоматически.</li>
      </ol>
      <p className="mt-3 text-sm text-fg-muted">Несколько меток работают по «или»: достаточно одного совпадения. Прямые назначения отчёта и доступ автора действуют отдельно. Доступ к датасетам назначается во вкладке <Link to="/admin?tab=datasets" className="text-accent hover:underline">«Датасеты»</Link>.</p>
    </Panel>

    <Panel title="Разрешённые метки" description="Выберите метки из списка или создайте новую. Новая метка появится в общем каталоге после сохранения.">
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <Field label="Кому назначить"><Select aria-label="Тип получателя меток" value={kind} disabled={busy} onChange={(event) => selectTarget(event.target.value as 'user' | 'group', '')}>
          <option value="user">Пользователю</option><option value="group">Группе</option>
        </Select></Field>
        <Field label={kind === 'user' ? 'Пользователь' : 'Группа'}><Select aria-label={kind === 'user' ? 'Пользователь' : 'Группа'} value={id} disabled={busy} onChange={(event) => selectTarget(kind, event.target.value)}>
          <option value="">Выберите</option>
          {(kind === 'user' ? users : groups).map((item) => <option key={item.id} value={item.id}>{'username' in item ? item.username : item.name}</option>)}
        </Select></Field>
      </div>
      {id && loadedTarget !== `${kind}:${id}` && !error && <Skeleton className="mb-3 h-8 w-full" />}
      <TagPicker label={kind === 'user' ? 'Личные разрешённые метки' : 'Разрешённые метки группы'} values={tags} options={available} disabled={!canEdit}
        onToggle={(tag) => setTags((previous) => previous.includes(tag) ? previous.filter((item) => item !== tag) : [...previous, tag])} />
      {details && details.inheritedFrom.length > 0 && <div className="mt-4 rounded-control border border-line bg-surface-sunken p-3 text-sm">
        <strong>Также получены через группы</strong>
        {details.inheritedFrom.map((source) => <p key={source.groupId} className="mt-1 text-fg-muted">{source.groupName}: {source.tags.join(', ')}</p>)}
        <p className="mt-2 text-xs text-fg-muted">Снятие личной метки не отменяет разрешение группы. Измените метки группы или её состав.</p>
      </div>}
      {details && <p className="mt-3 text-sm text-fg-muted">Сейчас действует меток: {details.effectiveTags.length}. {details.effectiveTags.join(', ')}</p>}
      {error && <Alert className="mt-3">{error}</Alert>}
      {notice && <Alert tone="success" className="mt-3">{notice}</Alert>}
      <Button className="mt-3" disabled={!canEdit} onClick={() => void save()}>{busy ? 'Сохраняем…' : 'Сохранить метки'}</Button>
    </Panel>

    <Panel title="Доступные метки" count={catalog.length} description="Здесь собраны метки отчётов и разрешённые метки пользователей и групп, включая ещё не поставленные на отчёты.">
      <Input type="search" aria-label="Поиск метки в каталоге" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти метку" />
      {catalogLoading ? <Skeleton className="mt-3 h-20 w-full" /> : <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {catalog.filter((item) => item.tag.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru'))).map((item) => <Button key={item.tag} variant="ghost" className="h-auto flex-col items-start rounded-control border border-line p-3 text-left" onClick={() => {
          setUsage(null); setUsageError(null); setUsageTag(item.tag)
        }}>
          <strong>{item.tag}</strong><span className="text-xs font-normal text-fg-muted">Отчётов: {item.reportCount} · Пользователей: {item.userCount} · Групп: {item.groupCount}</span>
        </Button>)}
        {catalog.length === 0 && <p className="text-sm text-fg-muted">Меток пока нет. Создайте первую в назначении выше или в редакторе отчёта.</p>}
      </div>}
    </Panel>

    {usageTag !== null && <Modal title={`Метка «${usageTag}»`} onClose={() => setUsageTag(null)} size="lg">
      {usageError && <Alert>{usageError}</Alert>}
      {!usage ? <Skeleton className="h-20 w-full" /> : <div className="space-y-4 text-sm">
        <div><strong>Отчёты ({selectedUsage?.reportCount ?? usage.reports.length})</strong>
          <ul className="mt-2 space-y-1">{usage.reports.map((report) => <li key={report.slug}><Link className="text-accent hover:underline" to={`/reports/${report.slug}`} onClick={() => setUsageTag(null)}>{report.title}</Link>{report.archivedAt && <Badge className="ml-2">В архиве</Badge>}</li>)}</ul>
          {usage.reports.length === 0 && <p className="mt-1 text-fg-muted">Пока не назначена отчётам.</p>}
          <Link to={`/reports?tag=${encodeURIComponent(usageTag)}`} onClick={() => setUsageTag(null)} className="mt-2 inline-block text-accent hover:underline">Открыть активные отчёты с этой меткой →</Link>
        </div>
        <div><strong>Личные назначения ({selectedUsage?.userCount ?? usage.users.length})</strong><div className="mt-2 flex flex-wrap gap-2">{usage.users.map((person) => <Button key={person.id} size="sm" disabled={busy} onClick={() => { selectTarget('user', person.id); setUsageTag(null) }}>{person.username}</Button>)}</div></div>
        <div><strong>Назначения группам ({selectedUsage?.groupCount ?? usage.groups.length})</strong><div className="mt-2 flex flex-wrap gap-2">{usage.groups.map((group) => <Button key={group.id} size="sm" disabled={busy} onClick={() => { selectTarget('group', group.id); setUsageTag(null) }}>{group.name}</Button>)}</div></div>
        <p className="text-xs text-fg-muted">Для каждого вида показано до 100 назначений.</p>
      </div>}
    </Modal>}
  </div>
}
