// Run with local-preview/start.ps1 against a disposable DATA_DIR (never production).
import assert from 'node:assert/strict'
import { mkdir, readFile } from 'node:fs/promises'
import { chromium, expect } from '@playwright/test'
import { zipSync, strToU8 } from 'fflate'
import { unpackZip } from './src/zip-core.js'

const base = process.env.ZIP_TEST_URL || 'http://127.0.0.1:5173/'
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const corpusResponse = await page.request.post(new URL('api/corpora', base).href, { data: { name: 'ZIP 验证', description: '临时测试数据' }, headers: { 'X-Bible-Request': '1' } })
assert.equal(corpusResponse.status(), 201)
const { corpus_id: id } = await corpusResponse.json()
const archive = (name, files) => ({ name, mimeType: 'application/zip', buffer: Buffer.from(zipSync(Object.fromEntries(Object.entries(files).map(([path, text]) => [path, strToU8(text)])))) })
const tiny = archive('批量测试.zip', { '鲁迅/甲.jsonl': '{"text":"测试甲原文","citation":{"label":"甲 · 第1段"}}', '鲁迅/乙.txt': '测试乙原文', 'README.md': '# 说明', 'metadata/info.json': '{}' })
const region = page.getByRole('region', { name: 'ZIP 批量导入预览' })
const input = page.locator('input[type=file]')
try {
  await page.goto(base)
  await page.getByRole('button', { name: '我的语料库', exact: true }).click()
  await page.getByRole('button', { name: /ZIP 验证.*条原文/ }).last().click()
  await input.setInputFiles(tiny)
  await expect(region.getByRole('button', { name: '确认批量导入' })).toBeEnabled()
  await expect(region).toContainText('已选 2 / 4 个文件 · 2 条原文')
  await region.locator('summary').first().click()
  await expect(region).toContainText('测试甲原文')
  await mkdir(new URL('../local-preview/', import.meta.url), { recursive: true })
  await page.screenshot({ path: '../local-preview/zip-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '../local-preview/zip-mobile.png', fullPage: true })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))

  let uploads = 0
  const routePattern = `**/api/corpora/${id}/resources`
  await page.route(routePattern, async route => {
    if (route.request().method() !== 'POST') return route.continue()
    uploads++
    if (uploads === 2) return route.fulfill({ status: 503, json: { detail: '模拟临时失败' } })
    await route.continue()
  })
  await region.getByRole('button', { name: '确认批量导入' }).click()
  await expect(region.getByRole('button', { name: '重试未完成文件' })).toBeEnabled()
  await expect(region).toContainText('模拟临时失败')
  await region.getByRole('button', { name: '重试未完成文件' }).click()
  await expect(region.getByRole('button', { name: '导入完成' })).toBeDisabled()
  assert.equal(uploads, 3, 'retry must only upload failed files')
  await page.unroute(routePattern)
  const resources = await (await page.request.get(new URL(`api/corpora/${id}/resources`, base).href)).json()
  assert.deepEqual(resources.map(r => r.title).sort(), ['乙.txt', '甲.jsonl'].sort())
  await expect.poll(async () => {
    const items = await (await page.request.get(new URL(`api/corpora/${id}/resources`, base).href)).json()
    return items.map(item => item.job.status)
  }, { timeout: 90000 }).toEqual(['ready', 'ready'])
  await input.setInputFiles(tiny)
  await expect(region.getByRole('button', { name: '确认批量导入' })).toBeEnabled()
  await region.getByRole('button', { name: '确认批量导入' }).click()
  await expect(region.getByRole('button', { name: '导入完成' })).toBeDisabled()
  assert.equal(await region.getByText(/已在库中/).count(), 2)

  await input.setInputFiles(archive('错误格式.zip', { 'broken.jsonl': 'not json', 'valid.txt': '有效原文' }))
  await expect(region.getByRole('button', { name: '重新预览失败文件' })).toBeEnabled()
  await expect(region.getByRole('button', { name: '确认批量导入' })).toBeDisabled()
  await region.getByRole('checkbox', { name: /broken.jsonl/ }).uncheck()
  await expect(region.getByRole('button', { name: '确认批量导入' })).toBeEnabled()
  await input.setInputFiles({ name: '损坏.zip', mimeType: 'application/zip', buffer: Buffer.from('bad') })
  await expect(page.getByRole('alert').filter({ hasText: /损坏/ })).toBeVisible()

  // The actual deliverable must preview without importing its thousands of paragraphs.
  const corpusZip = new Uint8Array(await readFile(new URL('../release/luxun-corpus-20261022.zip', import.meta.url)))
  const expected = unpackZip(corpusZip).files.filter(f => f.selected)
  assert(expected.every(f => f.title.endsWith('.jsonl')))
  await input.setInputFiles({ name: 'luxun-corpus-20261022.zip', mimeType: 'application/zip', buffer: Buffer.from(corpusZip) })
  await expect(region.getByRole('button', { name: '确认批量导入' })).toBeEnabled({ timeout: 120000 })
  await expect(region).toContainText('42,998 条原文')
  assert.equal(await region.locator('input:checked').count(), expected.length)
  await page.screenshot({ path: '../local-preview/zip-luxun-mobile.png', fullPage: true })
  await page.setViewportSize({ width: 1280, height: 1000 })
  await page.screenshot({ path: '../local-preview/zip-luxun-desktop.png', fullPage: true })
  console.log(`ZIP UI passed: ${expected.length} Lu Xun files / 42,998 fragments; preview, selection, retries, duplicates, corrupt files, mobile layout.`)
  assert.deepEqual(errors, [])
} finally {
  await page.request.delete(new URL(`api/corpora/${id}`, base).href, { headers: { 'X-Bible-Request': '1' } })
  await browser.close()
}
