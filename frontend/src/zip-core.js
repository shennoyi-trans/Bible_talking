import { unzipSync } from 'fflate'

export const ZIP_LIMIT = 50 * 1024 * 1024
export const FILE_LIMIT = 10 * 1024 * 1024
const TOTAL_LIMIT = 100 * 1024 * 1024
const MAX_FILES = 200
const supported = /\.(txt|md|json|jsonl)$/i
const crcTable = Uint32Array.from({ length: 256 }, (_, n) => {
  for (let i = 0; i < 8; i++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1
  return n >>> 0
})
function crc32(bytes) {
  let crc = 0xffffffff
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}
function invalid() { throw Error('ZIP 已损坏或格式不受支持，请重新压缩后上传。') }

// Inspect the central directory before allocation. fflate handles decoding and inflation;
// the extra checks enforce size limits, encryption rejection and CRC integrity.
function directory(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const u16 = offset => view.getUint16(offset, true), u32 = offset => view.getUint32(offset, true)
  let end = bytes.length - 22
  for (; end >= Math.max(0, bytes.length - 65557); end--) {
    if (u32(end) === 0x06054b50 && end + 22 + u16(end + 20) === bytes.length) break
  }
  if (end < 0 || end < bytes.length - 65557) invalid()
  const count = u16(end + 10), start = u32(end + 16), size = u32(end + 12)
  if (u16(end + 4) || u16(end + 6) || u16(end + 8) !== count) invalid()
  if (count === 65535 || start === 0xffffffff || size === 0xffffffff) throw Error('暂不支持 ZIP64，请拆分为普通 ZIP 文件。')
  if (count > MAX_FILES) throw Error('ZIP 最多包含 200 个文件或目录，请分包上传。')
  if (start + size !== end) invalid()
  const entries = []; let cursor = start, total = 0
  for (let i = 0; i < count; i++) {
    if (cursor + 46 > end || u32(cursor) !== 0x02014b50) invalid()
    const flags = u16(cursor + 8), method = u16(cursor + 10), crc = u32(cursor + 16)
    const compressed = u32(cursor + 20), original = u32(cursor + 24), local = u32(cursor + 42)
    const nameLength = u16(cursor + 28), extra = u16(cursor + 30), comment = u16(cursor + 32)
    if (flags & 1) throw Error('暂不支持加密 ZIP，请先移除密码。')
    if (original > FILE_LIMIT) throw Error('ZIP 内单个文件不能超过 10 MB，请拆分后上传。')
    total += original
    if (total > TOTAL_LIMIT) throw Error('ZIP 解压后不能超过 100 MB，请分包上传。')
    if (u16(cursor + 34) || cursor + 46 + nameLength + extra + comment > end) invalid()
    if (((u32(cursor + 38) >>> 16) & 0xf000) === 0xa000) throw Error('ZIP 不支持符号链接，请压缩实际文件。')
    if (local + 30 > start || u32(local) !== 0x04034b50) invalid()
    const localName = u16(local + 26), data = local + 30 + localName + u16(local + 28)
    if (data + compressed > start || u16(local + 6) !== flags || u16(local + 8) !== method || localName !== nameLength) invalid()
    for (let j = 0; j < nameLength; j++) if (bytes[local + 30 + j] !== bytes[cursor + 46 + j]) invalid()
    if (!(flags & 8) && (u32(local + 14) !== crc || u32(local + 18) !== compressed || u32(local + 22) !== original)) invalid()
    if (method === 0 && compressed !== original) invalid()
    entries.push({ method, crc, compressed, original })
    cursor += 46 + nameLength + extra + comment
  }
  if (cursor !== end) invalid()
  return entries
}

export function unpackZip(bytes) {
  if (bytes.length > ZIP_LIMIT) throw Error('ZIP 文件不能超过 50 MB。')
  try {
    const headers = directory(bytes), files = [], skipped = [], seen = new Set()
    let index = 0
    // A dry pass obtains names from the library without decompressing any payload.
    unzipSync(bytes, { filter: info => {
      const header = headers[index++]
      if (!header || header.original !== info.originalSize || header.compressed !== info.size || header.method !== info.compression) invalid()
      const name = info.name.replaceAll('\\', '/').normalize('NFC')
      if (/^[\/]|^[a-z]:/i.test(name) || /[\x00-\x1f]/.test(name) || name.split('/').some(p => p === '..' || p === '.')) throw Error('ZIP 包含不安全的文件路径，请重新打包。')
      if (name.endsWith('/')) return false
      if (name.split('/').some(p => p.startsWith('.') || p === '__MACOSX') || !supported.test(name)) {
        skipped.push(name); return false
      }
      if (seen.has(name)) throw Error(`ZIP 中存在重名文件：${name}`)
      seen.add(name)
      if (![0, 8].includes(info.compression)) throw Error(`不支持此文件的压缩方式：${name}，请使用标准 ZIP 压缩。`)
      const documentation = /(^|\/)(metadata|__macosx)(\/|$)/i.test(name) || /(^|\/)(readme|sources?|license|manifest|catalog|verification|excluded|duplicates)(\.[^/]+)?$/i.test(name)
      files.push({ name, originalName: info.name, selected: !documentation, header })
      return false
    } })
    if (index !== headers.length) invalid()
    if (!files.length) throw Error('ZIP 中没有 TXT、Markdown、JSON 或 JSONL 文件；不支持嵌套 ZIP。')
    // Match individual uploads by basename; retain folder names only to disambiguate.
    const basenames = new Map(), titles = new Set()
    for (const file of files) {
      const basename = file.name.split('/').at(-1)
      basenames.set(basename, (basenames.get(basename) || 0) + 1)
    }
    for (const file of files) {
      const basename = file.name.split('/').at(-1)
      file.title = basenames.get(basename) === 1 ? basename : file.name.replaceAll('/', '／')
      if (Array.from(file.title).length > 200) throw Error('ZIP 内文件路径过长，请缩短文件名或目录层级。')
      if (titles.has(file.title)) throw Error(`ZIP 中存在重名文件：${file.name}`)
      titles.add(file.title)
    }
    const wanted = new Set(files.map(f => f.originalName))
    const extracted = unzipSync(bytes, { filter: info => wanted.has(info.name) })
    return { skipped, files: files.map(({ originalName, header, ...file }) => {
      const content = extracted[originalName]
      if (!content || content.length !== header.original || crc32(content) !== header.crc) throw Error(`ZIP 文件校验失败：${file.name}，请重新打包。`)
      return { ...file, content }
    }) }
  } catch (error) {
    if (error instanceof RangeError || error.code != null) invalid()
    throw error
  }
}
