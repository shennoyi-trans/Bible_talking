"""Browser-only QA of the APK's built assets with fixed, real-model embedding fixtures.

This does NOT replace testing Android WebView / JNI on a physical device.
"""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
fixtures={f['text']:f['vector'] for f in json.loads((ROOT/'build/android-embedding-fixtures.json').read_text(encoding='utf-8'))}
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'build/android-assets/web'),**kwargs)
    def do_GET(self):
        if self.path=='/':
            html=(ROOT/'build/android-assets/web/index.html').read_text(encoding='utf-8')
            self.respond('text/html',html.replace('<head>','<head><script src="/preview-bridge.js"></script>').encode())
        elif self.path=='/preview-bridge.js':
            script='''const fixtures = FIXTURES;
window.BibleTalkingNative = {
 encode(id,text) { setTimeout(()=>window.__bibleNativeReply(id,fixtures[text]||null,fixtures[text]?null:'此测试预览仅支持固定测试句子'),20); },
 copy(text) { navigator.clipboard.writeText(text); }, close() {}
};'''.replace('FIXTURES',json.dumps(fixtures,ensure_ascii=False))
            self.respond('text/javascript',script.encode())
        else:super().do_GET()
    def respond(self,mime,body):
        self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def end_headers(self):
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; worker-src 'self'; frame-src 'none'; object-src 'none'")
        super().end_headers()
ThreadingHTTPServer(('127.0.0.1',5174),Handler).serve_forever()
