import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'

/** Dataset grant edits and label suggestions must use their authorized server endpoints. */
test('dataset grants and tag catalogs preserve scope and structured values', async () => {
  const server = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  const previousFetch = globalThis.fetch
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } })
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return new Response(JSON.stringify({ userIds: ['u1'], groupIds: ['g1'], tags: ['Финансы / Юг'] }))
  }
  try {
    const api = await server.ssrLoadModule('/src/lib/api.ts')
    assert.deepEqual(await api.adminDatasetAccess('sales'), { userIds: ['u1'], groupIds: ['g1'], tags: ['Финансы / Юг'] })
    await api.adminSetDatasetAccess('sales', { userIds: ['u1'], groupIds: ['g1'] })
    assert.equal(calls[1].url, '/api/admin/datasets/sales/access')
    assert.equal(calls[1].options.method, 'PUT')
    assert.deepEqual(JSON.parse(calls[1].options.body), { userIds: ['u1'], groupIds: ['g1'] })
    assert.deepEqual(await api.fetchAvailableReportTags(), ['Финансы / Юг'])
    assert.equal(calls[2].url, '/api/report-tags')
    await api.adminTagCatalog()
    assert.equal(calls[3].url, '/api/admin/tags')
    await api.adminTagUsage('Финансы / Юг')
    assert.equal(new URL(calls[4].url, 'http://localhost').searchParams.get('tag'), 'Финансы / Юг')
    await api.adminAccessTagDetails('user', 'u1')
    assert.equal(calls[5].url, '/api/admin/access-tags/user/u1?effective=true')
  } finally {
    globalThis.fetch = previousFetch
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage)
    else delete globalThis.localStorage
    await server.close()
  }
})
