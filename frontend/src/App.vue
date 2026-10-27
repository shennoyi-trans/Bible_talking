<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { isNative, nativeApi } from './native'
import { readZip, ZIP_LIMIT, FILE_LIMIT } from './zip-upload'
import { ArrowUpRight, ArrowRight, BookOpen, Check, ChevronDown, ChevronUp, Copy, FileText, Library, LoaderCircle, Plus, Search, Upload, X, RotateCw, ArrowLeft, Trash2, MoreHorizontal } from 'lucide-vue-next'

const page = ref('search'), corpora = ref([]), selected = ref('corpus_cuv'), query = ref(''), results = ref([])
const loading = ref(false), hasSearched = ref(false), searchedQuery = ref(''), error = ref(''), toast = ref('')
const topK = ref(50), indexing = ref(false), contexts = ref({}), expanded = ref({}), contextBusy = ref({})
const resources = ref([]), modal = ref(false), name = ref(''), description = ref(''), saving = ref(false)
const fileInput = ref(null), file = ref(null), preview = ref(null), uploading = ref(false), drag = ref(false)
const deletingResource = ref(false), pendingResourceDelete = ref(null), uploadCorpus = ref(''), previewToken = ref(0)
const zipEntries = ref(null), zipSkipped = ref([]), uploadProgress = ref(''), uploadError = ref('')
const chosenZipEntries = computed(() => (zipEntries.value || []).filter(entry => entry.selected))
const zipCount = computed(() => chosenZipEntries.value.reduce((count, entry) => count + (entry.preview?.count || 0), 0))
const zipCanImport = computed(() => chosenZipEntries.value.some(entry => entry.status !== 'done') && chosenZipEntries.value.every(entry => entry.preview && !entry.error))
const selectorOpen = ref(false), corpusMenu = ref(null), pendingCorpusDelete = ref(null), deletingCorpus = ref(false)
const archivedCorpora = ref([]), resourcesOpen = ref(true), reader = ref(null), readerBusy = ref(false)
const serverMode = ref(false)
const libraryLabel = computed(() => serverMode.value ? '共享语料库' : '我的语料库')
let readerRequest = 0
const corpus = computed(() => corpora.value.find(c => c.corpus_id === selected.value))
const examples = ['可以给我水喝吗？', '你要去哪里？', '别为明天的事担心', '有人出卖了我']
let timer, toastTimer, requestNumber = 0

async function api(path, options = {}) {
  if (isNative()) return nativeApi(path, options)
  // Relative to the document directory, so the same build supports / and /Bible_talking/.
  const response = await fetch(new URL('api' + path, document.baseURI), { ...options,
    headers: { ...options.headers, 'X-Bible-Request': '1' } })
  const value = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '请求未能完成，请稍后再试。')
  return value
}
function notify(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2400)
}
async function refresh() {
  try {
    corpora.value = await api('/corpora')
    if (!corpora.value.some(c => c.corpus_id === selected.value)) selected.value = corpora.value[0]?.corpus_id || ''
    if (page.value === 'library') {
      const id = selected.value
      const items = id ? await api(`/corpora/${id}/resources`) : []
      if (selected.value === id) resources.value = items
      archivedCorpora.value = await api('/corpora/archived')
    }
  } catch (e) { error.value = e.message }
}
function changeCorpus() {
  selectorOpen.value = false; resourcesOpen.value = true; resources.value = []; error.value = ''
  requestNumber++
  loading.value = false
  results.value = []; hasSearched.value = false; expanded.value = {}; contexts.value = {}
  file.value = null; preview.value = null; previewToken.value++
  zipEntries.value = null; zipSkipped.value = []; uploadError.value = ''; uploadProgress.value = ''
  if (fileInput.value) fileInput.value.value = ''
  refresh()
}
async function search(value) {
  if (typeof value === 'string') query.value = value
  if (!query.value.trim() || !selected.value) return
  const id = ++requestNumber
  loading.value = true; error.value = ''; hasSearched.value = true
  results.value = []; expanded.value = {}; contexts.value = {}; searchedQuery.value = query.value.trim()
  try {
    const data = await api('/search', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ corpus_id: selected.value, query: searchedQuery.value, top_k: topK.value }) })
    if (id !== requestNumber) return
    results.value = data.results; indexing.value = data.indexing
  } catch (e) { if (id === requestNumber) error.value = e.message }
  finally { if (id === requestNumber) loading.value = false }
}
async function copy(text) {
  try { if (isNative()) window.BibleTalkingNative.copy(text); else await navigator.clipboard.writeText(text); notify('已复制，去说点不一样的。') }
  catch { notify('复制未成功，请选中文字手动复制。') }
}
async function toggleContext(result) {
  const id = result.fragment_id
  expanded.value[id] = !expanded.value[id]
  if (!expanded.value[id] || contexts.value[id]) return
  contextBusy.value[id] = true
  try { contexts.value[id] = await api(`/corpora/${selected.value}/context?fragment_id=${encodeURIComponent(id)}`) }
  catch (e) { notify(e.message); expanded.value[id] = false }
  finally { contextBusy.value[id] = false }
}
async function createCorpus() {
  if (!name.value.trim()) return
  saving.value = true
  try {
    const created = await api('/corpora', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.value, description: description.value }) })
    selected.value = created.corpus_id; modal.value = false; name.value = ''; description.value = ''; page.value = 'library'
    changeCorpus(); notify('语料库已创建，可以添加你的文字了。')
  } catch (e) { notify(e.message) }
  finally { saving.value = false }
}
async function selectFile(candidate) {
  if (!candidate || uploading.value) return
  if (fileInput.value) fileInput.value.value = ''
  const isZip = candidate.name.toLowerCase().endsWith('.zip')
  if (candidate.size > (isZip ? ZIP_LIMIT : FILE_LIMIT)) { notify(isZip ? 'ZIP 文件不能超过 50 MB。' : '文件不能超过 10 MB。'); return }
  const token = ++previewToken.value
  file.value = candidate; preview.value = null; uploading.value = true; uploadCorpus.value = selected.value
  zipEntries.value = null; zipSkipped.value = []; uploadError.value = ''; uploadProgress.value = ''
  if (isZip) {
    uploadProgress.value = '正在解压 ZIP…'
    try {
      const archive = await readZip(candidate)
      if (token !== previewToken.value) return
      zipEntries.value = archive.files; zipSkipped.value = archive.skipped
      await previewZip(token)
    } catch (e) { if (token === previewToken.value) { uploadError.value = e.message; uploadProgress.value = '' } }
    finally { uploading.value = false }
    return
  }
  const form = new FormData(); form.append('file', candidate)
  try {
    const data = await api(`/corpora/${uploadCorpus.value}/preview`, { method: 'POST', body: form })
    if (token === previewToken.value) preview.value = data
  } catch (e) { if (token === previewToken.value) { uploadError.value = e.message; file.value = null } }
  finally { uploading.value = false }
}
async function previewZip(token = previewToken.value) {
  uploading.value = true; uploadError.value = ''
  const id = uploadCorpus.value
  const entries = chosenZipEntries.value.filter(entry => !entry.preview && entry.status !== 'done')
  try {
    for (let i = 0; i < entries.length; i++) {
      if (token !== previewToken.value) return
      const entry = entries[i]
      uploadProgress.value = `正在预览 ${i + 1}/${entries.length}：${entry.name}`
      const form = new FormData(); form.append('file', entry.file)
      try {
        entry.preview = await api(`/corpora/${id}/preview`, { method: 'POST', body: form })
        entry.error = ''
      } catch (e) { entry.error = e.message }
    }
  } finally {
    if (token === previewToken.value) { uploadProgress.value = ''; uploading.value = false }
  }
}
async function uploadZip() {
  if (!zipCanImport.value || uploading.value || uploadCorpus.value !== selected.value) return
  const token = previewToken.value, id = uploadCorpus.value
  const entries = chosenZipEntries.value.filter(entry => entry.status !== 'done')
  uploading.value = true; uploadError.value = ''
  let failures = 0
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i]
    if (token !== previewToken.value) break
    uploadProgress.value = `正在导入 ${i + 1}/${entries.length}：${entry.name}`
    const form = new FormData(); form.append('file', entry.file)
    try {
      const result = await api(`/corpora/${id}/resources`, { method: 'POST', body: form })
      entry.status = 'done'; entry.duplicate = result.duplicate; entry.importError = ''
    } catch (e) { entry.status = 'failed'; entry.importError = e.message; failures++ }
  }
  if (token === previewToken.value) {
    uploadProgress.value = ''
    uploadError.value = failures ? `${failures} 个文件导入失败，已成功的文件已保留。点击“重试未完成文件”即可继续。` : ''
    if (!failures) notify('所选文件已全部加入语料库。')
  }
  uploading.value = false
  await refresh()
}
async function upload() {
  if (!file.value || uploading.value || uploadCorpus.value !== selected.value) return
  uploading.value = true
  const form = new FormData(); form.append('file', file.value)
  try {
    const result = await api(`/corpora/${uploadCorpus.value}/resources`, { method: 'POST', body: form })
    notify(result.duplicate ? '这份语料已在库中，无需重复导入。' : '已加入语料库，正在准备检索。')
    file.value = null; preview.value = null; if (fileInput.value) fileInput.value.value = ''; await refresh()
  } catch (e) { notify(e.message) }
  finally { uploading.value = false }
}
async function reindex(resource) {
  try { await api(`/corpora/${selected.value}/resources/${resource.resource_id}/reindex`, { method: 'POST' }); notify('已开始重新准备语料。'); await refresh() }
  catch (e) { notify(e.message) }
}
async function deleteResource() {
  if (!pendingResourceDelete.value || deletingResource.value) return
  const id = pendingResourceDelete.value.resource_id
  deletingResource.value = true
  try {
    await api(`/corpora/${selected.value}/resources/${id}`, { method: 'DELETE' })
    pendingResourceDelete.value = null
    requestNumber++; loading.value = false; results.value = []; contexts.value = {}; expanded.value = {}; hasSearched.value = false
    if (reader.value?.resource_id === id) { reader.value = null; readerRequest++ }
    notify('语料已永久删除。'); await refresh()
  } catch (e) { notify(e.message) }
  finally { deletingResource.value = false }
}
function chooseCorpus(id) {
  if (uploading.value) { notify('请等待当前文件处理完成后再切换语料库。'); return }
  selectorOpen.value = false
  if (selected.value !== id) { selected.value = id; changeCorpus() }
}
function openCorpusMenu(event, item) {
  if (uploading.value) return
  const rect = event.currentTarget.getBoundingClientRect()
  corpusMenu.value = { item, x: Math.max(8, Math.min(event.clientX || rect.left, window.innerWidth - 190)),
    y: Math.max(8, Math.min(event.clientY || rect.bottom, window.innerHeight - 64)) }
}
function closeMenus(event) {
  if (!event.target.closest('.corpus-picker')) selectorOpen.value = false
  if (!event.target.closest('.corpus-context-menu')) corpusMenu.value = null
}
function escapeMenus(event) {
  if (event.key !== 'Escape') return
  selectorOpen.value = false; corpusMenu.value = null
  if (!deletingCorpus.value) pendingCorpusDelete.value = null
  reader.value = null; readerRequest++
}
async function deleteCorpus() {
  if (!pendingCorpusDelete.value || deletingCorpus.value) return
  const id = pendingCorpusDelete.value.corpus_id
  deletingCorpus.value = true
  try {
    await api(`/corpora/${id}`, { method: 'DELETE' })
    pendingCorpusDelete.value = null
    if (selected.value === id) { selected.value = ''; changeCorpus() }
    reader.value = null; readerRequest++
    await refresh(); notify('语料库已永久删除。')
  } catch (e) { notify(e.message) }
  finally { deletingCorpus.value = false }
}
async function openResource(resource, offset = 0) {
  const request = ++readerRequest
  const corpusId = reader.value?.resource_id === resource.resource_id ? reader.value.corpus_id : selected.value
  reader.value = { resource_id: resource.resource_id, corpus_id: corpusId, title: resource.title, offset, fragments: [], total: 0 }
  readerBusy.value = true
  try {
    const content = await api(`/corpora/${corpusId}/resources/${resource.resource_id}/content?offset=${offset}`)
    if (request === readerRequest) reader.value = { ...reader.value, ...content }
  } catch (e) { if (request === readerRequest) { reader.value = null; notify(e.message) } }
  finally { if (request === readerRequest) readerBusy.value = false }
}
function statusText(resource) {
  return ({ pending: '等待处理', processing: '正在准备', ready: '可检索', failed: '处理失败', cancelled: '已停止' })[resource.job?.status] || '等待处理'
}
function nativeBack() {
  if (reader.value) { reader.value = null; readerRequest++ }
  else if (modal.value) modal.value = false
  else if (pendingResourceDelete.value && !deletingResource.value) pendingResourceDelete.value = null
  else if (pendingCorpusDelete.value) pendingCorpusDelete.value = null
  else if (selectorOpen.value || corpusMenu.value) { selectorOpen.value = false; corpusMenu.value = null }
  else if (page.value === 'library') page.value = 'search'
  else window.BibleTalkingNative?.close()
}
onMounted(() => { if (!isNative()) api('/health').then(data => { serverMode.value = data.deployment === 'server' }).catch(() => {}); refresh(); timer = setInterval(refresh, 5000); document.addEventListener('pointerdown', closeMenus); document.addEventListener('keydown', escapeMenus); window.addEventListener('bible-back', nativeBack) })
onUnmounted(() => { clearInterval(timer); clearTimeout(toastTimer); document.removeEventListener('pointerdown', closeMenus); document.removeEventListener('keydown', escapeMenus); window.removeEventListener('bible-back', nativeBack) })
</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <button v-if="page === 'library'" class="secondary back-button" @click="page = 'search'"><ArrowLeft :size="16" />返回</button>
      <span v-else class="header-note">旧时的文字，今日的表达<span class="tiny-spark">✦</span></span>
      <button v-if="page === 'search'" class="secondary library-button" @click="page = 'library'; refresh()"><Library :size="16" />{{ libraryLabel }}</button>
    </header>

    <main>
      <template v-if="page === 'search'">
        <section class="intro">
          <h1 class="serif">{{ corpus ? `来试试像${corpus.name}一样说话` : '选择语料库，试试另一种表达' }}</h1>
        </section>

        <section class="search-panel" aria-label="语料检索">
          <div class="search-top">
            <div class="corpus-picker">
              <button class="corpus-select" aria-label="选择检索语料库" :aria-expanded="selectorOpen" aria-controls="corpus-options" @click="selectorOpen = !selectorOpen"><BookOpen :size="16" /><span>{{ corpus?.name || '选择语料库' }}</span><ChevronUp v-if="selectorOpen" :size="14" /><ChevronDown v-else :size="14" /></button>
              <div v-if="selectorOpen" id="corpus-options" class="corpus-options">
                <p>{{ corpora.length === 1 ? '当前只有一个语料库' : '选择要检索的语料库' }}</p>
                <div class="corpus-option-list"><button v-for="item in corpora" :key="item.corpus_id" :class="{ chosen: selected === item.corpus_id }" :aria-pressed="selected === item.corpus_id" @click="chooseCorpus(item.corpus_id)"><BookOpen :size="16" /><span>{{ item.name }}</span><Check v-if="selected === item.corpus_id" :size="16" /></button></div>
                <button class="add-corpus" @click="selectorOpen = false; page = 'library'; modal = true; refresh()"><Plus :size="16" />添加语料库</button>
              </div>
            </div>
          </div>
          <form @submit.prevent="search()">
            <label class="sr-only" for="query">你想说的话</label>
            <textarea id="query" v-model="query" maxlength="2000" rows="2" placeholder="此刻，你想说些什么？" @keydown.ctrl.enter.prevent="search()" @keydown.meta.enter.prevent="search()"></textarea>
            <div class="search-bottom"><button class="primary search-submit" type="submit" :disabled="loading || !query.trim() || !selected"><LoaderCircle v-if="loading" class="spin" :size="17" /><Search v-else :size="17" />{{ loading ? '查询中' : '查询' }}</button></div>
          </form>
        </section>
        <div class="suggestions"><span>不妨试试</span><button v-for="example in examples" :key="example" @click="search(example)">{{ example }}<ArrowUpRight :size="13" /></button></div>

        <div v-if="error" class="notice error" role="alert">{{ error }}<button @click="refresh">重试</button></div>
        <div v-if="corpus?.pending_jobs" class="notice"><LoaderCircle class="spin" :size="16" /><span>正在准备语料，已完成 {{ corpus.indexed_resources }} / {{ corpus.resource_count }} 份。完成的部分可以先检索。</span></div>

        <section v-if="hasSearched" class="results-section" aria-live="polite" aria-busy="loading">
          <div class="results-heading"><div><h2>{{ loading ? '正在寻找合适的句子…' : `找到 ${results.length} 条原文` }}</h2><p v-if="!loading && results.length">关于「{{ searchedQuery }}」<span v-if="indexing"> · 部分语料仍在准备</span></p></div><label class="result-limit">最多显示 <select v-model.number="topK" aria-label="最多显示条数" @change="search()"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label></div>
          <div v-if="loading" class="loading-state"><LoaderCircle class="spin" :size="30" /><p>翻一翻，找一句与你相近的话。</p></div>
          <div v-else-if="!results.length && !error" class="empty-state"><BookOpen :size="32" /><h3>{{ indexing ? '语料正在准备中' : '这里还没有可检索的原文' }}</h3><p>{{ indexing ? '第一批语料准备好后，再试一次。' : '添加一些文字，再来找找你的表达。' }}</p><button class="secondary" @click="indexing ? search() : (page = 'library')">{{ indexing ? '重新检索' : '添加语料' }}</button></div>
          <ol v-else class="result-list">
            <li v-for="result in results" :key="result.fragment_id" class="quote-card">
              <span class="rank">{{ String(result.rank).padStart(2, '0') }}</span>
              <div class="quote-body"><p class="quote-text">“{{ result.text }}”</p><div class="citation"><span class="citation-line"></span><span>{{ result.citation.label }}</span><span v-if="result.is_excerpt" class="excerpt-label">节选</span><span v-if="result.citation.edition" class="edition">{{ result.citation.edition }}</span></div>
                <div class="quote-actions"><button class="copy-primary" @click="copy(result.copy_text)"><Copy :size="14" />复制原文与出处</button><button @click="copy(result.text)">仅复制原文</button><button class="context-toggle" :aria-expanded="!!expanded[result.fragment_id]" @click="toggleContext(result)">{{ expanded[result.fragment_id] ? '收起上下文' : '查看上下文' }}<ChevronUp v-if="expanded[result.fragment_id]" :size="14" /><ChevronDown v-else :size="14" /></button></div>
                <div v-if="expanded[result.fragment_id]" class="context-panel"><span v-if="contextBusy[result.fragment_id]">正在打开上下文…</span><div v-for="(part, i) in contexts[result.fragment_id]" :key="i" :class="{ selected: part.selected }"><span>{{ part.citation.label }}</span><p>{{ part.text }}</p></div></div>
              </div>
            </li>
          </ol>
          <div v-if="results.length && !loading" class="results-end"><span></span>已显示本次检索的 {{ results.length }} 条原文<span></span></div>
        </section>
      </template>

      <template v-else>
        <section class="library-intro"><h1><span class="serif emphasis">{{ libraryLabel }}</span></h1><button class="primary" :disabled="uploading" @click="modal = true"><Plus :size="17" />新建语料库</button></section>
        <p v-if="serverMode" class="shared-library-note">这里的语料由所有访客共同使用，上传和管理操作会同步到共享语料库。</p>
        <div v-if="error" class="notice error" role="alert">{{ error }}</div>
        <div class="corpus-tabs"><div v-for="item in corpora" :key="item.corpus_id" class="corpus-card"><button class="corpus-tab" :class="{ selected: selected === item.corpus_id }" @click="chooseCorpus(item.corpus_id)" @contextmenu.prevent="openCorpusMenu($event, item)" @keydown.shift.f10.prevent="openCorpusMenu($event, item)" title="点击选择，右键删除语料库"><BookOpen :size="18" /><strong>{{ item.name }}</strong><span v-if="item.builtin" class="builtin">预置</span><small>{{ item.fragment_count.toLocaleString() }} 条原文</small></button><button class="corpus-more icon-button" :aria-label="`${item.name}的更多操作`" title="语料库操作" @click.stop="openCorpusMenu($event, item)"><MoreHorizontal :size="18" /></button></div></div>
        <template v-if="corpus">
          <div class="library-details"><div><h2>{{ corpus.name }}</h2></div></div>
          <div class="upload-zone" :class="{ dragging: drag }" @dragover.prevent="drag = true" @dragleave.prevent="drag = false" @drop.prevent="drag = false; selectFile($event.dataTransfer.files[0])"><div class="upload-icon"><Upload :size="22" /></div><h3>上传定制语料</h3><button class="secondary" :disabled="uploading" @click="fileInput.click()"><LoaderCircle v-if="uploading" class="spin" :size="15" /><Plus v-else :size="15" />{{ uploading ? '正在处理' : '选择文件或 ZIP' }}</button><small>TXT、Markdown、JSON、JSONL · UTF-8 · 单文件 10 MB / ZIP 50 MB</small><input ref="fileInput" class="sr-only" type="file" accept=".txt,.md,.json,.jsonl,.zip" @change="selectFile($event.target.files[0])" /></div>
          <p v-if="uploadProgress" class="upload-progress" role="status"><LoaderCircle class="spin" :size="15" />{{ uploadProgress }}</p>
          <p v-if="uploadError" class="notice error" role="alert">{{ uploadError }}</p>
          <section v-if="zipEntries" class="preview-panel zip-preview" aria-label="ZIP 批量导入预览">
            <div class="preview-heading"><div><strong>{{ file?.name }}</strong><p>已选 {{ chosenZipEntries.length }} / {{ zipEntries.length }} 个文件 · {{ zipCount.toLocaleString() }} 条原文</p></div><button class="primary" :disabled="uploading || !zipCanImport" @click="uploadZip">{{ uploading ? '正在处理…' : chosenZipEntries.some(entry => entry.status === 'failed') ? '重试未完成文件' : chosenZipEntries.length && chosenZipEntries.every(entry => entry.status === 'done') ? '导入完成' : '确认批量导入' }}<ArrowRight :size="15" /></button></div>
            <p class="zip-help">说明文档和 metadata 默认不选，可按需勾选。每个文件将单独收录，已导入的相同文件会自动识别。</p>
            <div class="zip-files">
              <div v-for="entry in zipEntries" :key="entry.name" class="zip-file">
                <label><input v-model="entry.selected" type="checkbox" :disabled="uploading || entry.status === 'done'" @change="previewZip()" /><span>{{ entry.name }}<small>{{ (entry.file.size / 1024).toFixed(0) }} KB<span v-if="entry.preview"> · {{ entry.preview.count.toLocaleString() }} 条原文</span><span v-if="entry.status === 'done'"> · {{ entry.duplicate ? '已在库中' : '已加入，索引进度见下方' }}</span></small></span></label>
                <p v-if="entry.selected && (entry.error || entry.importError)" class="resource-error" role="alert">{{ entry.error || entry.importError }}</p>
                <details v-if="entry.selected && entry.preview"><summary>查看切分预览</summary><div v-for="(part, i) in entry.preview.preview" :key="i" class="preview-row"><span>{{ i + 1 }}</span><div><p>{{ part.text }}</p><small>{{ part.citation.label }}</small></div></div></details>
              </div>
            </div>
            <button v-if="chosenZipEntries.some(entry => entry.error)" class="secondary" :disabled="uploading" @click="previewZip()">重新预览失败文件</button>
            <details v-if="zipSkipped.length" class="zip-skipped"><summary>已忽略 {{ zipSkipped.length }} 个隐藏文件或不支持的文件</summary><p v-for="item in zipSkipped" :key="item">{{ item }}</p></details>
          </section>
          <div v-if="preview" class="preview-panel"><div class="preview-heading"><div><strong>{{ file?.name }}</strong><p>将切分为 {{ preview.count }} 条原文，预览前 {{ preview.preview.length }} 条。</p></div><button class="primary" :disabled="uploading" @click="upload">{{ uploading ? '正在导入…' : '确认导入' }}<ArrowRight :size="15" /></button></div><div v-for="(part, i) in preview.preview" :key="i" class="preview-row"><span>{{ i + 1 }}</span><div><p>{{ part.text }}</p><small>{{ part.citation.label }}</small></div></div></div>
          <button class="resource-heading resource-disclosure" :aria-expanded="resourcesOpen" aria-controls="resource-list" :title="resourcesOpen ? '收起收录的文字' : '展开收录的文字'" @click="resourcesOpen = !resourcesOpen"><span>收录的文字 <small>{{ resources.length }}</small></span><ChevronUp v-if="resourcesOpen" :size="18" /><ChevronDown v-else :size="18" /></button>
          <div v-if="resourcesOpen" id="resource-list">
          <div v-if="!resources.length" class="empty-library">还没有文字。添加第一份语料，开始寻找。</div>
          <div v-for="resource in resources" :key="resource.resource_id" class="resource-row"><FileText :size="20" /><div class="resource-info"><button class="resource-title" :title="`查看《${resource.title}》原文`" @click="openResource(resource)">{{ resource.title }}<ArrowUpRight :size="13" /></button><small>{{ resource.job.total }} 条原文<span v-if="resource.job.status === 'processing'"> · 已处理 {{ resource.job.processed }} 条</span></small><p v-if="resource.job.error" class="resource-error">{{ resource.job.error }}</p></div><span v-if="resource.job.status !== 'ready'" class="status" :class="resource.job.status"><span></span>{{ statusText(resource) }}</span><button class="icon-button" :aria-label="`重新处理 ${resource.title}`" :title="`重新处理 ${resource.title}`" :disabled="['pending','processing'].includes(resource.job.status)" @click="reindex(resource)"><RotateCw :size="16" /></button><button class="icon-button" :aria-label="`永久删除 ${resource.title}`" :title="`永久删除 ${resource.title}`" @click="pendingResourceDelete = resource"><Trash2 :size="16" /></button></div>
          </div>
          <p v-if="corpus.builtin" class="source-note">预置语料：简体中文和合本 · <a href="https://github.com/seven1m/open-bibles" target="_blank" rel="noreferrer">Open Bibles 数据源 <ArrowUpRight :size="12" /></a> · 保留来源中的措辞与章节。</p>
        </template>
        <div v-else class="empty-library">还没有语料库，点击“新建语料库”开始。</div>
        <details v-if="archivedCorpora.length" class="deleted-corpora"><summary>旧版归档的语料库（{{ archivedCorpora.length }}）</summary><div v-for="item in archivedCorpora" :key="item.corpus_id"><span>{{ item.name }}</span><button class="secondary" @click="pendingCorpusDelete = item">永久删除</button></div></details>
      </template>
    </main>

    <div v-if="corpusMenu" class="corpus-context-menu" :style="{ left: `${corpusMenu.x}px`, top: `${corpusMenu.y}px` }" role="menu" aria-label="语料库操作"><button role="menuitem" @click="pendingCorpusDelete = corpusMenu.item; corpusMenu = null"><Trash2 :size="15" />删除语料库</button></div>
    <div v-if="pendingCorpusDelete" class="modal-backdrop" @click.self="!deletingCorpus && (pendingCorpusDelete = null)"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="delete-corpus-title"><h2 id="delete-corpus-title">永久删除语料库？</h2><p>将永久删除「{{ pendingCorpusDelete.name }}」及其中全部原文和检索数据，删除后无法恢复。</p><div class="modal-buttons"><button class="secondary" :disabled="deletingCorpus" @click="pendingCorpusDelete = null">取消</button><button class="primary" :disabled="deletingCorpus" @click="deleteCorpus">{{ deletingCorpus ? '删除中…' : '永久删除' }}</button></div></section></div>
    <div v-if="reader" class="modal-backdrop" @click.self="reader = null; readerRequest++"><section class="modal reader-modal" role="dialog" aria-modal="true" aria-labelledby="reader-title"><button class="modal-close icon-button" title="关闭原文" aria-label="关闭原文" @click="reader = null; readerRequest++"><X :size="20" /></button><h2 id="reader-title">{{ reader.title }}</h2><div v-if="readerBusy" class="loading-state">正在读取原文…</div><div v-else class="reader-content"><article v-for="part in reader.fragments" :key="part.fragment_id"><small>{{ part.citation.label }}</small><p class="serif">{{ part.text }}</p></article><p v-if="!reader.fragments.length">暂无原文。</p></div><div class="reader-pagination"><button class="secondary" :disabled="readerBusy || !reader.offset" @click="openResource(reader, Math.max(0, reader.offset - 50))">上一页</button><span>{{ reader.total ? `${reader.offset + 1}–${Math.min(reader.offset + 50, reader.total)} / ${reader.total}` : '0 条' }}</span><button class="secondary" :disabled="readerBusy || reader.offset + 50 >= reader.total" @click="openResource(reader, reader.offset + 50)">下一页</button></div></section></div>
    <div v-if="toast" class="toast" role="status"><Check :size="16" />{{ toast }}</div>
    <div v-if="modal" class="modal-backdrop" @click.self="modal = false" @keydown.esc="modal = false"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><button class="modal-close icon-button" aria-label="关闭" @click="modal = false"><X :size="20" /></button><div class="eyebrow">收集你的表达世界</div><h2 id="create-title">新建语料库</h2><form @submit.prevent="createCorpus"><label>名称<input v-model="name" required maxlength="80" placeholder="例如：喜欢的诗、我的随笔" /></label><label>介绍 <span>可选</span><textarea v-model="description" maxlength="500" rows="3" placeholder="想在这里收集什么样的文字？"></textarea></label><button class="primary" :disabled="saving || !name.trim()" type="submit">{{ saving ? '正在创建…' : '创建语料库' }}<ArrowRight :size="16" /></button></form></section></div>
    <div v-if="pendingResourceDelete" class="modal-backdrop" @click.self="!deletingResource && (pendingResourceDelete = null)"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="archive-title"><h2 id="archive-title">永久删除这份语料？</h2><p>将永久删除「{{ pendingResourceDelete.title }}」的原文和检索数据，删除后无法恢复。</p><div class="modal-buttons"><button class="secondary" :disabled="deletingResource" @click="pendingResourceDelete = null">取消</button><button class="primary" :disabled="deletingResource" @click="deleteResource">{{ deletingResource ? '删除中…' : '永久删除' }}</button></div></section></div>
  </div>
</template>
