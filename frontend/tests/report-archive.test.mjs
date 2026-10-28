import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'

/** Archive pages must send the archive filter on both rows and facet requests. */
test('archive catalog requests preserve filters and pagination', async () => {
  const server = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  const previousFetch = globalThis.fetch
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } })
  const requested = []
  globalThis.fetch = async (url, options) => {
    requested.push({ url: String(url), options })
    return new Response(JSON.stringify({ reports: [], total: 0 }))
  }
  try {
    const api = await server.ssrLoadModule('/src/lib/api.ts')
    await api.searchReports({ archived: true, q: 'Продажи', limit: 30, offset: 30, favorite: true })
    const catalog = new URL(requested[0].url, 'http://localhost')
    assert.equal(catalog.searchParams.get('archived'), 'true')
    assert.equal(catalog.searchParams.get('q'), 'Продажи')
    assert.equal(catalog.searchParams.get('offset'), '30')
    assert.equal(catalog.searchParams.get('limit'), '30')
    assert.equal(catalog.searchParams.get('favorite'), 'true')
    await api.fetchReportFacets('Продажи', undefined, true)
    const facets = new URL(requested[1].url, 'http://localhost')
    assert.equal(facets.searchParams.get('archived'), 'true')
    assert.equal(facets.searchParams.get('q'), 'Продажи')
    await api.searchReports({})
    assert.equal(new URL(requested[2].url, 'http://localhost').searchParams.has('archived'), false)
    await api.restoreReport('sales-report')
    assert.equal(requested[3].url, '/api/reports/sales-report/restore')
    assert.equal(requested[3].options.method, 'POST')
    await api.fetchDatasetDeletionImpact('sales')
    assert.equal(requested[4].url, '/api/datasets/sales/deletion-impact')
  } finally {
    globalThis.fetch = previousFetch
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage)
    else delete globalThis.localStorage
    await server.close()
  }
})
