// Android owns inference; the worker owns local storage, parsing and exact vector search.
let worker, sequence = 0
const requests = new Map()
export const isNative = () => !!window.BibleTalkingNative
export function nativeApi(path, options = {}) {
  if (!worker) {
    worker = new Worker(new URL('./offline.worker.js', import.meta.url), { type: 'module' })
    window.__bibleNativeReply = (id, value, error) => worker.postMessage({ kind: 'embedding', id, value, error })
    worker.onmessage = ({ data }) => {
      if (data.kind === 'encode') { window.BibleTalkingNative.encode(String(data.id), data.text); return }
      const request = requests.get(data.id)
      if (!request) return
      requests.delete(data.id)
      data.error ? request.reject(new Error(data.error)) : request.resolve(data.value)
    }
    worker.onerror = () => {
      for (const request of requests.values()) request.reject(new Error('本地检索未能启动，请关闭应用后重试。'))
      requests.clear(); worker.terminate(); worker = null
    }
  }
  const id = ++sequence
  const body = options.body instanceof FormData ? options.body.get('file') : options.body ? JSON.parse(options.body) : null
  return new Promise((resolve, reject) => {
    requests.set(id, { resolve, reject })
    worker.postMessage({ id, path, method: options.method || 'GET', body })
  })
}
