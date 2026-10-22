const uid = prefix => `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`
export { uid }
export function parseText(text, title) {
  const chars = Array.from(text), fragments = []; let start = 0, paragraph = 0, heading = ''
  while (start < chars.length) {
    let end = start; while (end < chars.length && !['\n', '\r'].includes(chars[end])) end++
    if (end === start) { start++; continue }
    paragraph++
    const line = chars.slice(start, end).join('')
    if (line.trimStart().startsWith('#')) { heading = line.replace(/^[# ]+/, '').trim(); start = end + 1; continue }
    let cursor = start, trimmedEnd = end
    while (cursor < trimmedEnd && /\s/u.test(chars[cursor])) cursor++
    while (trimmedEnd > cursor && /\s/u.test(chars[trimmedEnd - 1])) trimmedEnd--
    while (cursor < trimmedEnd) {
      let stop = Math.min(cursor + 220, trimmedEnd)
      if (stop < trimmedEnd) for (let k = stop - 1; k >= cursor; k--) if ('。！？!?；;'.includes(chars[k])) { stop = k + 1; break }
      let left = cursor, right = stop
      while (left < right && /\s/u.test(chars[left])) left++
      while (right > left && /\s/u.test(chars[right - 1])) right--
      if (right > left) fragments.push({ text: chars.slice(left, right).join(''), start_offset: left, end_offset: right,
        citation: { scheme: 'document', title, paragraph, heading, label: `${title} · ${heading ? heading + ' · ' : ''}第 ${paragraph} 段` } })
      cursor = stop
    }
    start = end + 1
  }
  return { text, fragments }
}
export async function parseUpload(file) {
  if (!file || file.size > 10 * 1024 * 1024) throw Error('文件不能超过 10 MB。')
  let text
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()) } catch { throw Error('请上传 UTF-8 编码的文本。') }
  const suffix = file.name.split('.').pop().toLowerCase()
  if (['txt', 'md'].includes(suffix)) return validate(parseText(text, file.name))
  if (!['json', 'jsonl'].includes(suffix)) throw Error('支持 TXT、Markdown、JSON、JSONL 文件。')
  let records
  try { records = suffix === 'json' ? JSON.parse(text) : text.split(/\r?\n/).filter(s => s.trim()).map(s => JSON.parse(s)) }
  catch { throw Error('JSON 格式错误，请检查后重新上传。') }
  if (!Array.isArray(records) || !records.length) throw Error('JSON 需要非空数组，每条记录包含 text 和可选的 citation。')
  const texts = [], fragments = []; let offset = 0
  records.forEach((record, index) => {
    if (typeof record?.text !== 'string' || !record.text.trim()) throw Error(`第 ${index + 1} 条记录缺少有效的 text。`)
    if (record.citation != null && (typeof record.citation !== 'object' || Array.isArray(record.citation))) throw Error('citation 必须是对象。')
    const citation = { scheme: 'document', label: `${file.name} · 第 ${index + 1} 条`, ...record.citation }
    if (typeof citation.label !== 'string' || Array.from(citation.label).length > 500) throw Error('出处 label 必须是 500 字以内的文本。')
    const count = Array.from(record.text).length
    const parts = count > 400 ? parseText(record.text, file.name).fragments : [{ text: record.text, start_offset: 0, end_offset: count }]
    for (const p of parts) fragments.push({ ...p, start_offset: p.start_offset + offset, end_offset: p.end_offset + offset, citation })
    texts.push(record.text); offset += count + 1
  })
  return validate({ text: texts.join('\n'), fragments })
}
function validate(parsed) {
  if (!parsed.fragments.length) throw Error('文件中没有可切分的正文。')
  if (parsed.fragments.length > 50000) throw Error('单个文件最多包含 50,000 个片段，请分批上传。')
  return parsed
}
export function indexSpans(text) {
  const chars = Array.from(text), result = [[0, chars.length]]
  for (const match of text.matchAll(/[「“]([^」”\n]{2,160})[」”]/gu)) {
    const start = Array.from(text.slice(0, match.index + 1)).length
    let left = start, right = start + Array.from(match[1]).length
    while (left < right && /\s/u.test(chars[left])) left++
    while (right > left && /\s/u.test(chars[right - 1])) right--
    if (right - left < chars.length - 4) result.push([left, right])
  }
  return result.filter((v, i) => result.findIndex(x => x[0] === v[0] && x[1] === v[1]) === i)
}
export function rankVectors(vector, vectors, spans, fragments, allowed, topK) {
  if (vector.length !== 512 || vectors.length !== spans.length * 512) throw Error('向量索引格式不正确。')
  const hits = []
  for (let i = 0; i < spans.length; i++) {
    const fragment = fragments[spans[i][0]]
    if (!allowed.has(fragment.resource_id)) continue
    let score = 0; const start = i * 512
    for (let j = 0; j < 512; j++) score += vector[j] * vectors[start + j]
    hits.push({ score, fragment, start: spans[i][1], end: spans[i][2] })
  }
  hits.sort((a, b) => b.score - a.score)
  const seen = new Set(), output = []
  for (const hit of hits) {
    if (seen.has(hit.fragment.fragment_id)) continue
    seen.add(hit.fragment.fragment_id); output.push(hit)
    if (output.length === topK) break
  }
  return output
}
