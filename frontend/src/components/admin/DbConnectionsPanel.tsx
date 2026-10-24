import { useEffect, useState } from 'react'
import type { DbConnection } from '../../types/dataset'
import { fetchDbConnections, testDbConnection } from '../../lib/api'
import { Alert, Badge, Button, Panel, PanelRow } from '../ui'

export function DbConnectionsPanel() {
  const [items, setItems] = useState<DbConnection[]>([])
  const [error, setError] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [checked, setChecked] = useState<string | null>(null)
  useEffect(() => { void fetchDbConnections().then(setItems).catch((err) => setError(String(err))) }, [])
  const test = async (key: string) => {
    setTesting(key); setError(null); setChecked(null)
    try { await testDbConnection(key); setChecked(key) }
    catch (err) { setError(err instanceof Error ? err.message : 'проверка не удалась') }
    finally { setTesting(null) }
  }
  return <Panel title="Подключения к базам" description="Адреса и учётные данные задаются в DB_CONNECTIONS файла backend/.env. После правки перезапустите приложение.">
    {error && <Alert className="mb-3">{error}</Alert>}
    <div className="space-y-2">{items.map((item) => <PanelRow key={item.key}>
      <strong className="min-w-32">{item.title}</strong>
      <Badge>{item.source}</Badge>
      <span className="flex-1 text-xs text-fg-muted">{item.address}</span>
      {checked === item.key && <Badge tone="good">Доступно</Badge>}
      <Button disabled={testing !== null} onClick={() => void test(item.key)}>{testing === item.key ? 'Проверяю…' : 'Проверить'}</Button>
    </PanelRow>)}</div>
  </Panel>
}
