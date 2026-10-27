import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'vite'

/** Safari connection failures must explain sending versus receiving a chat answer. */
test('explains network failures in both agent streams', async () => {
  const server = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  const previousFetch = globalThis.fetch
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null, removeItem() {} } })
  try {
    const api = await server.ssrLoadModule('/src/lib/api.ts')
    const senders = [
      (onEvent) => api.streamWorkspaceAnswer(['schools'], 'Анализ', 'chat', onEvent),
      (onEvent) => api.streamReportChat([{ role: 'user', text: 'Отчёт' }], {}, onEvent),
    ]
    for (const send of senders) {
      globalThis.fetch = async () => { throw new TypeError('Load failed') }
      await assert.rejects(send(() => {}), /Не удалось отправить/u)
      globalThis.fetch = async () => new Response(new ReadableStream({
        start(controller) { controller.error(new TypeError('Load failed')) },
      }))
      await assert.rejects(send(() => {}), /получения ответа.*Проверить историю/u)
      globalThis.fetch = async () => new Response('')
      await assert.rejects(send(() => {}), /без итогового ответа/u)
      globalThis.fetch = async () => new Response('<html>Gateway timeout</html>', { status: 504 })
      await assert.rejects(send(() => {}), /не дождался.*Проверить историю/u)
      globalThis.fetch = async () => new Response('not JSON\n')
      await assert.rejects(send(() => {}), /неподходящем формате/u)
      globalThis.fetch = async () => new Response(JSON.stringify({ type: 'done' }))
      await assert.rejects(send(() => {}), /неподходящем формате/u)
    }
    globalThis.fetch = async () => new Response([
      JSON.stringify({ type: 'heartbeat', conversationId: 'saved-chat' }),
      JSON.stringify({ type: 'status', text: 'Считаю показатели…' }),
    ].join('\n'))
    await assert.rejects(senders[0](() => {}), /Последний этап: Считаю показатели/u)
    const serverFailure = new Error('Источник не успел выполнить расчёт.')
    globalThis.fetch = async () => new Response(JSON.stringify({ type: 'error', message: serverFailure.message }))
    await assert.rejects(senders[0](() => { throw serverFailure }), (failure) => failure === serverFailure)
    globalThis.fetch = async () => new Response(JSON.stringify({ type: 'done', result: { answer: 'Готово' } }))
    const events = []
    await senders[0]((event) => events.push(event))
    assert.equal(events[0].result.answer, 'Готово')
  } finally {
    globalThis.fetch = previousFetch
    if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage)
    else delete globalThis.localStorage
    await server.close()
  }
})
