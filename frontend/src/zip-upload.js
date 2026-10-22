export { ZIP_LIMIT, FILE_LIMIT } from './zip-core'

export async function readZip(file) {
  const bytes = await file.arrayBuffer()
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./zip.worker.js', import.meta.url), { type: 'module' })
    const finish = () => { clearTimeout(timeout); worker.terminate() }
    const timeout = setTimeout(() => { finish(); reject(Error('解压超时，请拆分 ZIP 后重试。')) }, 30000)
    worker.onerror = () => { finish(); reject(Error('无法解压 ZIP，请重新压缩后上传。')) }
    worker.onmessage = ({ data }) => {
      finish()
      if (data.error) reject(Error(data.error))
      else resolve({ skipped: data.result.skipped, files: data.result.files.map(({ content, ...item }) => ({
        ...item, file: new File([content], item.title), status: '', preview: null, error: '',
      })) })
    }
    worker.postMessage(bytes, [bytes])
  })
}
