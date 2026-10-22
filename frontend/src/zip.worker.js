import { unpackZip } from './zip-core'

self.onmessage = ({ data }) => {
  try {
    const result = unpackZip(new Uint8Array(data))
    self.postMessage({ result }, result.files.map(file => file.content.buffer))
  } catch (error) { self.postMessage({ error: error.message }) }
}
