import test from 'node:test'
import assert from 'node:assert/strict'
import { zipSync, strToU8, strFromU8 } from 'fflate'
import { unpackZip, FILE_LIMIT, ZIP_LIMIT } from './src/zip-core.js'

const pack = (files, level = 6) => zipSync(Object.fromEntries(Object.entries(files).map(([name, text]) => [name, strToU8(text)])), { level })
const centralOffset = bytes => new DataView(bytes.buffer).getUint32(bytes.length - 6, true)

test('nested UTF-8 corpus files retain contents and standalone upload titles', () => {
  const archive = unpackZip(pack({ '鲁迅/呐喊.jsonl': '{"text":"狂人日记"}', '鲁迅/野草.txt': '秋夜', 'README.md': '# 说明', 'metadata/a.json': '{}' , '__MACOSX/._a.txt': 'hidden', '目录.csv': 'a,b' }))
  assert.deepEqual(archive.files.filter(f => f.selected).map(f => f.title), ['呐喊.jsonl', '野草.txt'])
  assert.equal(strFromU8(archive.files[0].content), '{"text":"狂人日记"}')
  assert.equal(archive.files.length, 4)
  assert.deepEqual(archive.skipped, ['__MACOSX/._a.txt', '目录.csv'])
})

test('same basenames in separate folders remain distinct', () => {
  const files = unpackZip(pack({ 'a/x.txt': '甲', 'b/x.txt': '乙' })).files
  assert.deepEqual(files.map(f => f.title), ['a／x.txt', 'b／x.txt'])
})

test('unsafe paths and normalized duplicate paths are rejected', () => {
  for (const name of ['../x.txt', '/x.txt', 'C:\\x.txt', 'a/../x.txt']) assert.throws(() => unpackZip(pack({ [name]: 'a' })), /不安全/)
  assert.throws(() => unpackZip(pack({ 'a/x.txt': 'a', 'a\\x.txt': 'b' })), /重名/)
  assert.throws(() => unpackZip(pack({ 'e\u0301.txt': 'a', 'é.txt': 'b' })), /重名/)
})

test('corruption, truncation, and encryption produce actionable errors', () => {
  const corrupted = pack({ 'x.txt': 'text' }, 0)
  corrupted[35] ^= 1
  assert.throws(() => unpackZip(corrupted), /校验失败/)
  const encrypted = pack({ 'x.txt': 'text' })
  encrypted[centralOffset(encrypted) + 8] |= 1
  assert.throws(() => unpackZip(encrypted), /加密/)
  assert.throws(() => unpackZip(new Uint8Array(0)), /损坏/)
  assert.throws(() => unpackZip(pack({ 'x.txt': 'text' }).slice(0, -3)), /损坏/)
})

test('limits reject excessive decompressed size and entry counts before inflation', () => {
  const huge = pack({ 'x.txt': 'a' })
  new DataView(huge.buffer).setUint32(centralOffset(huge) + 24, FILE_LIMIT + 1, true)
  assert.throws(() => unpackZip(huge), /单个文件不能超过/)
  assert.throws(() => unpackZip(new Uint8Array(ZIP_LIMIT + 1)), /50 MB/)
  const many = Object.fromEntries(Array.from({ length: 201 }, (_, i) => [`${i}.txt`, 'a']))
  assert.throws(() => unpackZip(pack(many)), /200/)
  const total = pack(Object.fromEntries(Array.from({ length: 11 }, (_, i) => [`${i}.txt`, 'a'])))
  const view = new DataView(total.buffer)
  let cursor = centralOffset(total)
  for (let i = 0; i < 11; i++) {
    const local = view.getUint32(cursor + 42, true)
    view.setUint32(local + 22, FILE_LIMIT, true)
    view.setUint32(cursor + 24, FILE_LIMIT, true)
    cursor += 46 + view.getUint16(cursor + 28, true) + view.getUint16(cursor + 30, true) + view.getUint16(cursor + 32, true)
  }
  assert.throws(() => unpackZip(total), /100 MB/)
})

test('archives containing only unsupported or nested ZIP files are rejected', () => {
  assert.throws(() => unpackZip(pack({ 'nested.zip': 'zip', 'image.png': 'png' })), /没有 TXT/)
})
