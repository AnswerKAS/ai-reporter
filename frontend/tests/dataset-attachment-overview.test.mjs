import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** An attached dataset offers separate controls for viewing its contents and removing it. */
test('renders a clickable dataset name beside its remove action', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { DatasetQuestionPanel } = await server.ssrLoadModule('/src/components/DatasetQuestionPanel.tsx')
    const dataset = {
      slug: 'pyrus_staff', title: 'Pyrus · Сотрудники поддержки', description: 'Сотрудники и команды',
      fields: [{ name: 'employee_id', type: 'integer' }], fieldSettings: {},
    }
    const html = renderToStaticMarkup(React.createElement(DatasetQuestionPanel, {
      datasets: [dataset], initialDatasetSlug: dataset.slug, requestedConversationId: null,
      onDatasetChange: () => {}, onConversationChange: () => {},
    }))
    assert.match(html, /aria-label="Показать содержимое датасета «Pyrus · Сотрудники поддержки»"/u)
    assert.match(html, /aria-label="Открепить Pyrus · Сотрудники поддержки"/u)
    assert.match(html, /<button[^>]*>@Pyrus · Сотрудники поддержки<\/button>/u)
  } finally {
    await server.close()
  }
})
