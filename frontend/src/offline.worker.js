import { uid, parseUpload, indexSpans, rankVectors } from './offline-core.js'

let seed, vectors, db, state, busy = false, embedId = 0
const embeddings = new Map()
const ready = initialize()
async function initialize() {
  const response = await fetch('/offline/seed.json')
  if (!response.ok) throw Error('预置语料未能加载，请重新安装应用。')
  seed = await response.json()
  vectors = new Float32Array(await (await fetch('/offline/vectors.bin')).arrayBuffer())
  db = await new Promise((resolve, reject) => {
    const request = indexedDB.open('Bible_talking', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('library')
    request.onerror = () => reject(Error('无法打开本地存储。'))
    request.onsuccess = () => resolve(request.result)
  })
  state = await new Promise((resolve, reject) => {
    const request = db.transaction('library').objectStore('library').get('state')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  }) || { corpora: [], resources: [], archived: [], hidden: [] }
  for (const resource of state.resources) if (resource.job.status === 'processing') { resource.job.status = 'pending'; resource.job.processed = 0 }
  setTimeout(processJobs, 0)
}
// Attach rejection handling immediately; each API call still receives the initialization error.
ready.catch(() => {})
function save() {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('library', 'readwrite')
    tx.objectStore('library').put(state, 'state')
    tx.oncomplete = resolve
    tx.onerror = tx.onabort = () => reject(Error('本地存储写入失败，请检查手机剩余空间。'))
  })
}
function encode(text) {
  return new Promise((resolve, reject) => {
    const id = String(++embedId); embeddings.set(id, { resolve, reject })
    postMessage({ kind: 'encode', id, text })
  })
}
const corpora = () => [...seed.corpora, ...state.corpora]
function requireCorpus(id) {
  const found = corpora().find(c => c.corpus_id === id)
  if (!found || state.archived.includes(id)) throw Error('语料库不存在。')
  return found
}
function resources(id) {
  requireCorpus(id)
  return [...(id === 'corpus_cuv' ? seed.resources : []), ...state.resources.filter(r => r.corpus_id === id)].filter(r => !state.hidden.includes(r.resource_id))
}
function requireResource(corpusId, id) {
  const resource = resources(corpusId).find(r => r.resource_id === id)
  if (!resource) throw Error('资源不存在。')
  return resource
}
const fragments = resource => resource.fragments || seed.fragments.filter(f => f.resource_id === resource.resource_id)
function summary(corpus) {
  const list = resources(corpus.corpus_id)
  return { ...corpus, resource_count: list.length, fragment_count: list.reduce((n, r) => n + r.job.total, 0),
    indexed_resources: list.filter(r => r.indexed).length, pending_jobs: list.filter(r => ['pending', 'processing'].includes(r.job.status)).length,
    failed_jobs: list.filter(r => r.job.status === 'failed').length }
}
async function processJobs() {
  if (busy || !state) return
  busy = true
  try {
    for (;;) {
      const resource = state.resources.find(r => r.job.status === 'pending' && !state.archived.includes(r.corpus_id) && !state.hidden.includes(r.resource_id))
      if (!resource) break
      resource.job.status = 'processing'; resource.job.processed = 0; resource.job.error = null; resource.job.attempts++
      try {
        await save()
        const spans = [], rows = []
        for (let i = 0; i < resource.fragments.length; i++) {
          if (state.archived.includes(resource.corpus_id) || state.hidden.includes(resource.resource_id)) { resource.job.status = 'cancelled'; break }
          const fragment = resource.fragments[i], chars = Array.from(fragment.text)
          for (const [start, end] of indexSpans(fragment.text)) {
            rows.push(await encode(chars.slice(start, end).join(''))); spans.push([i, start, end])
          }
          resource.job.processed = i + 1
          if (i % 20 === 0) await save()
        }
        if (resource.job.status !== 'cancelled') {
          const packed = new Float32Array(rows.length * 512)
          rows.forEach((row, i) => packed.set(row, i * 512))
          resource.vectors = packed; resource.spans = spans; resource.indexed = true; resource.job.status = 'ready'
        }
        await save()
      } catch (e) {
        resource.job.status = 'failed'; resource.job.error = e.message
        await save().catch(() => {})
      }
    }
  } finally { busy = false }
}
async function search(body) {
  const query = String(body.query || '').trim(), topK = Math.max(1, Math.min(100, Number(body.top_k) || 50))
  if (!query || query.length > 2000) throw Error('请输入 2000 字以内的内容。')
  resources(body.corpus_id)
  const vector = await encode(query)
  // Re-read visibility after inference; deleting a corpus cancels its pending search.
  const list = resources(body.corpus_id), allowed = new Set(list.filter(r => r.indexed).map(r => r.resource_id))
  const hits = body.corpus_id === 'corpus_cuv' ? rankVectors(vector, vectors, seed.spans, seed.fragments, allowed, topK) : []
  for (const resource of list) if (resource.vectors && resource.indexed) hits.push(...rankVectors(vector, resource.vectors, resource.spans, resource.fragments, allowed, topK))
  hits.sort((a, b) => b.score - a.score)
  return { query, top_k: topK, indexing: list.some(r => ['pending', 'processing'].includes(r.job.status)), results: hits.slice(0, topK).map((hit, i) => {
    const fragment = hit.fragment, text = Array.from(fragment.text).slice(hit.start, hit.end).join('')
    return { rank: i + 1, fragment_id: fragment.fragment_id, resource_id: fragment.resource_id, version_id: fragment.version_id,
      text, full_text: fragment.text, is_excerpt: text !== fragment.text, citation: fragment.citation,
      title: list.find(r => r.resource_id === fragment.resource_id).title, copy_text: `“${text}”（${fragment.citation.label}）` }
  }) }
}
async function route(path, method, body) {
  const url = new URL(path, 'https://local'), parts = url.pathname.split('/').filter(Boolean)
  if (path === '/health') return { ok: true, offline: true }
  if (path === '/search' && method === 'POST') return search(body)
  if (path === '/corpora') {
    if (method === 'GET') return corpora().filter(c => !state.archived.includes(c.corpus_id)).map(summary)
    if (method === 'POST') {
      const name = String(body.name || '').trim(), description = String(body.description || '').trim()
      if (!name || name.length > 100 || description.length > 2000) throw Error('名称应在 100 字以内，描述应在 2000 字以内。')
      const corpus = { corpus_id: uid('corpus'), name, description, builtin: false }
      state.corpora.push(corpus); await save(); return corpus
    }
  }
  if (path === '/corpora/archived') return corpora().filter(c => state.archived.includes(c.corpus_id)).map(c => ({ corpus_id: c.corpus_id, name: c.name }))
  if (parts[0] !== 'corpora') throw Error('接口不存在。')
  const id = parts[1]
  if (parts[2] === 'restore' && method === 'POST') {
    if (!state.archived.includes(id)) throw Error('已删除的语料库不存在。')
    state.archived = state.archived.filter(value => value !== id)
    for (const r of state.resources) if (r.corpus_id === id && r.job.status === 'cancelled' && !state.hidden.includes(r.resource_id)) r.job.status = 'pending'
    await save(); processJobs(); return { restored: true }
  }
  requireCorpus(id)
  if (parts.length === 2 && method === 'DELETE') {
    state.archived.push(id)
    for (const r of state.resources) if (r.corpus_id === id && ['pending', 'processing'].includes(r.job.status)) r.job.status = 'cancelled'
    await save(); return { archived: true }
  }
  if (parts[2] === 'context') {
    const target = [...seed.fragments, ...state.resources.flatMap(r => r.fragments)].find(f => f.fragment_id === url.searchParams.get('fragment_id'))
    if (!target) throw Error('片段不存在。')
    const resource = requireResource(id, target.resource_id)
    return fragments(resource).filter(f => Math.abs(f.fragment_index - target.fragment_index) <= 1).map(f => ({ text: f.text, citation: f.citation, selected: f.fragment_id === target.fragment_id }))
  }
  if (parts[2] === 'preview' && method === 'POST') {
    const parsed = await parseUpload(body)
    return { count: parsed.fragments.length, preview: parsed.fragments.slice(0, 5) }
  }
  if (parts[2] !== 'resources') throw Error('接口不存在。')
  if (parts.length === 3 && method === 'GET') return resources(id).map(r => ({ resource_id: r.resource_id, title: r.title, indexed: r.indexed, job: { ...r.job } }))
  if (parts.length === 3 && method === 'POST') {
    const parsed = await parseUpload(body)
    const bytes = new TextEncoder().encode(JSON.stringify([body.name, parsed.text, parsed.fragments.map(f => f.citation)]))
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('')
    requireCorpus(id)
    let resource = state.resources.find(r => r.corpus_id === id && r.content_hash === hash)
    if (resource) {
      state.hidden = state.hidden.filter(v => v !== resource.resource_id)
      if (!resource.indexed && ['cancelled', 'failed'].includes(resource.job.status)) resource.job.status = 'pending'
      await save(); processJobs(); return { resource_id: resource.resource_id, duplicate: true }
    }
    const resourceId = uid('res'), versionId = `${resourceId}:${hash}`
    resource = { corpus_id: id, resource_id: resourceId, version_id: versionId, owner_user_id: 1, resource_kind: 'monologue',
      source_type: 'upload', source_ref_id: body.name, system_tags: ['imported_text'], content_hash: hash, title: body.name, text: parsed.text, indexed: false,
      fragments: parsed.fragments.map((f, i) => ({ ...f, fragment_id: `${versionId}:f${i}`, resource_id: resourceId, version_id: versionId, fragment_index: i })),
      job: { job_id: uid('idx'), total: parsed.fragments.length, processed: 0, attempts: 0, status: 'pending', error: null } }
    state.resources.push(resource); await save(); processJobs(); return { resource_id: resourceId, duplicate: false }
  }
  const resource = requireResource(id, parts[3])
  if (parts[4] === 'content') {
    const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0), list = fragments(resource)
    return { title: resource.title, total: list.length, offset, fragments: list.slice(offset, offset + 50) }
  }
  if (parts[4] === 'reindex' && method === 'POST') {
    if (resource.fragments && !['pending', 'processing'].includes(resource.job.status)) {
      resource.job.status = 'pending'; resource.job.error = null; await save(); processJobs()
    }
    return resource.job
  }
  if (method === 'DELETE') {
    state.hidden.push(resource.resource_id)
    if (['pending', 'processing'].includes(resource.job.status)) resource.job.status = 'cancelled'
    await save(); return { archived: true }
  }
  throw Error('接口不存在。')
}
self.onmessage = async ({ data }) => {
  if (data.kind === 'embedding') {
    const request = embeddings.get(data.id); if (!request) return
    embeddings.delete(data.id); data.error ? request.reject(Error(data.error)) : request.resolve(data.value); return
  }
  try { await ready; postMessage({ id: data.id, value: await route(data.path, data.method, data.body) }) }
  catch (e) { postMessage({ id: data.id, error: e.message || '本地操作失败，请重试。' }) }
}
