import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import 'fake-indexeddb/auto'
import { parseUpload, indexSpans, rankVectors } from './src/offline-core.js'

const fixtures = JSON.parse(await readFile(new URL('../build/android-embedding-fixtures.json', import.meta.url), 'utf8'))
const fixtureMap = new Map(fixtures.map(f => [f.text, f.vector]))
const parsed = await parseUpload(new File(['# 标题\n  😀给我水喝。\n再见。'], 'note.md'))
for (const f of parsed.fragments) assert.equal(Array.from(parsed.text).slice(f.start_offset, f.end_offset).join(''), f.text)
assert.equal(parsed.fragments[0].citation.label, 'note.md · 标题 · 第 2 段')
assert.deepEqual(indexSpans('他说：“可以给我水喝吗？”然后离开。'), [[0, 18], [4, 12]])
await assert.rejects(parseUpload(new File([new Uint8Array([255])], 'bad.txt')), /UTF-8/)
await assert.rejects(parseUpload(new File(['[]'], 'bad.json')), /非空/)
await assert.rejects(parseUpload(new File(['# heading'], 'empty.md')), /正文/)

const waiting = new Map(); let sequence = 0
globalThis.self = globalThis
globalThis.fetch = async path => {
  assert.match(path, /^\/offline\/(seed.json|vectors.bin)$/)
  const content = await readFile(new URL('../build/android-assets/web' + path, import.meta.url))
  return new Response(content)
}
globalThis.postMessage = message => {
  if (message.kind === 'encode') {
    const vector = fixtureMap.get(message.text)
    setImmediate(() => self.onmessage({ data: { kind: 'embedding', id: message.id, value: vector, error: vector ? null : 'Missing test fixture: ' + message.text } }))
    return
  }
  const request = waiting.get(message.id); waiting.delete(message.id)
  message.error ? request.reject(Error(message.error)) : request.resolve(message.value)
}
await import('./src/offline.worker.js')
function api(path, method = 'GET', body = null) {
  const id = ++sequence
  return new Promise((resolve, reject) => { waiting.set(id, { resolve, reject }); self.onmessage({ data: { id, path, method, body } }) })
}
const bible = (await api('/corpora'))[0]
assert.equal(bible.fragment_count, 31100)
assert.equal(bible.indexed_resources, 66)
let result = await api('/search', 'POST', { corpus_id: bible.corpus_id, query: fixtures[0].text, top_k: 50 })
assert.equal(result.results.length, 50)
assert.match(result.results[0].text, /水/)
assert.match(result.results[0].citation.label, /约翰福音 4:7/)
assert.deepEqual(result.results.map(r => r.rank), Array.from({ length: 50 }, (_, i) => i + 1))
assert(result.results.every(r => !('score' in r)))
const hit = result.results[0]
const context = await api(`/corpora/corpus_cuv/context?fragment_id=${encodeURIComponent(hit.fragment_id)}`)
assert(context.some(f => f.selected && f.text.includes(hit.text)))
const book = await api(`/corpora/corpus_cuv/resources/${hit.resource_id}/content?offset=50`)
assert.equal(book.offset, 50); assert.equal(book.fragments.length, 50)
const custom = await api('/corpora', 'POST', { name: '本地测试' })
const upload = new File([fixtures[0].text + '\n' + fixtures[1].text], 'sample.txt')
assert.equal((await api(`/corpora/${custom.corpus_id}/preview`, 'POST', upload)).count, 2)
const imported = await api(`/corpora/${custom.corpus_id}/resources`, 'POST', upload)
assert.equal((await api(`/corpora/${custom.corpus_id}/resources`, 'POST', upload)).duplicate, true)
const deadline = Date.now() + 10000
while ((await api(`/corpora/${custom.corpus_id}/resources`))[0].job.status !== 'ready') {
  if (Date.now() > deadline) throw Error('Index job timed out')
  await new Promise(resolve => setTimeout(resolve, 10))
}
result = await api('/search', 'POST', { corpus_id: custom.corpus_id, query: fixtures[0].text, top_k: 50 })
assert.equal(result.results.length, 2)
assert.equal(result.results[0].text, fixtures[0].text)
await api(`/corpora/${custom.corpus_id}`, 'DELETE')
await assert.rejects(api('/search', 'POST', { corpus_id: custom.corpus_id, query: fixtures[0].text }), /不存在/)
assert((await api('/corpora/archived')).some(c => c.corpus_id === custom.corpus_id))
await api(`/corpora/${custom.corpus_id}/restore`, 'POST')
assert.equal((await api('/search', 'POST', { corpus_id: custom.corpus_id, query: fixtures[1].text })).results[0].text, fixtures[1].text)
await api(`/corpora/${custom.corpus_id}/resources/${imported.resource_id}`, 'DELETE')
assert.equal((await api('/search', 'POST', { corpus_id: custom.corpus_id, query: fixtures[0].text })).results.length, 0)
await api(`/corpora/corpus_cuv/resources/${hit.resource_id}`, 'DELETE')
assert.equal((await api('/corpora'))[0].resource_count, 65)
console.log('PASS offline parser, Unicode offsets, 50-result Bible search, citation, context, pagination, custom import, duplicate, indexing, archive, restore and resource removal.')
