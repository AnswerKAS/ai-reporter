import assert from 'node:assert/strict'
import test from 'node:test'
import { watchDatasetAccess } from '../src/lib/dataset-access-refresh.ts'

/** An open empty chat sees a dataset granted while its tab was inactive. */
test('refreshes dataset access when an existing chat regains focus', () => {
  const tab = new EventTarget()
  const page = new EventTarget()
  page.visibilityState = 'visible'
  let granted = false
  let available = false
  const stop = watchDatasetAccess(() => { available = granted }, tab, page)

  assert.equal(available, false)
  granted = true
  tab.dispatchEvent(new Event('focus'))
  assert.equal(available, true)

  granted = false
  page.visibilityState = 'hidden'
  page.dispatchEvent(new Event('visibilitychange'))
  assert.equal(available, true)
  page.visibilityState = 'visible'
  page.dispatchEvent(new Event('visibilitychange'))
  assert.equal(available, false)

  stop()
  granted = true
  tab.dispatchEvent(new Event('focus'))
  assert.equal(available, false)
})
