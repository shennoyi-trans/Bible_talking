// Run against local-preview/start.ps1 with a disposable DATA_DIR.
import assert from 'node:assert/strict'
import { chromium, expect } from '@playwright/test'

const base = 'http://127.0.0.1:5173/'
const browser = await chromium.launch({ headless: true, channel: 'msedge' })
const page = await browser.newPage({ viewport: { width: 1280, height: 960 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const headers = { 'X-Bible-Request': '1' }
let id
try {
  const response = await page.request.post(new URL('api/corpora', base).href,
    { headers, data: { name: '永久删除验证' } })
  assert.equal(response.status(), 201)
  id = (await response.json()).corpus_id
  const url = new URL(`api/corpora/${id}`, base).href
  const imported = await page.request.post(`${url}/resources`, { headers, multipart: {
    file: { name: '删除测试.txt', mimeType: 'text/plain', buffer: Buffer.from('待删除的原文。\n只用于验证永久删除。') },
  } })
  assert.equal(imported.status(), 202)
  const rid = (await imported.json()).resource_id
  await expect.poll(async () => (await (await page.request.get(`${url}/resources`)).json())[0]?.job.status,
    { timeout: 60000 }).toBe('ready')
  await page.goto(base)
  await page.getByRole('button', { name: '我的语料库', exact: true }).click()
  await page.getByRole('button', { name: /永久删除验证.*条原文/ }).click()
  const remove = page.getByRole('button', { name: '永久删除 删除测试.txt', exact: true })
  await remove.focus()
  await expect(remove).toBeFocused()
  assert.equal(await remove.getAttribute('title'), '永久删除 删除测试.txt')
  await remove.click()
  const dialog = page.getByRole('dialog', { name: '永久删除这份语料？' })
  await expect(dialog).toContainText('原文和检索数据，删除后无法恢复')
  await page.screenshot({ path: '../local-preview/hard-delete-resource-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '../local-preview/hard-delete-resource-mobile.png', fullPage: true })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal((await page.request.get(`${url}/resources/${rid}/content`)).status(), 200)
  await remove.click()
  await dialog.getByRole('button', { name: '永久删除', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(remove).not.toBeVisible()
  assert.deepEqual(await (await page.request.get(`${url}/resources`)).json(), [])
  assert.equal((await page.request.get(`${url}/resources/${rid}/content`)).status(), 404)
  await page.getByRole('button', { name: '永久删除验证的更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '删除语料库', exact: true }).click()
  const corpusDialog = page.getByRole('dialog', { name: '永久删除语料库？' })
  await expect(corpusDialog).toContainText('全部原文和检索数据，删除后无法恢复')
  await page.screenshot({ path: '../local-preview/hard-delete-corpus-mobile.png', fullPage: true })
  await corpusDialog.getByRole('button', { name: '永久删除', exact: true }).click()
  await expect(corpusDialog).not.toBeVisible()
  await expect(page.getByRole('button', { name: /永久删除验证.*条原文/ })).not.toBeVisible()
  assert(!(await (await page.request.get(new URL('api/corpora/archived', base).href)).json()).some(c => c.corpus_id === id))
  assert.equal((await page.request.post(`${url}/restore`, { headers })).status(), 410)
  await page.reload()
  await expect(page.getByRole('heading', { name: '选择语料库，试试另一种表达' })).toBeVisible()
  assert.deepEqual(errors, [])
  console.log('PASS hard-delete UI: desktop/mobile dialogs, cancel, keyboard focus, resource and corpus deletion, reload.')
} finally {
  if (id) await page.request.delete(new URL(`api/corpora/${id}`, base).href, { headers })
  await browser.close()
}
