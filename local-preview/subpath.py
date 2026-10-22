"""Preview the built frontend behind an Nginx-style stripped path prefix.

Start local-preview/start.ps1 with PUBLIC_ORIGIN=http://127.0.0.1:5174,
build frontend/dist, then run this script and open /Bible_talking/.
Local verification only; production uses Nginx.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PREFIX = '/Bible_talking'
HOP_HEADERS = {'connection', 'transfer-encoding', 'content-length', 'server', 'date'}


class Proxy(BaseHTTPRequestHandler):
    def forward(self):
        parsed = urlsplit(self.path)
        if parsed.path == PREFIX:
            self.send_response(308)
            self.send_header('Location', PREFIX + '/' + ('?' + parsed.query if parsed.query else ''))
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not parsed.path.startswith(PREFIX + '/'):
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if length > 12 * 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(length) if length else None
        headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP_HEADERS}
        request = Request('http://127.0.0.1:8000' + self.path[len(PREFIX):],
                          data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=120)
        except HTTPError as error:
            response = error
        except OSError:
            self.send_error(502, 'Start the backend on port 8000 first')
            return
        with response:
            content = response.read()
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(content)

    do_GET = do_HEAD = do_POST = do_DELETE = forward


if __name__ == '__main__':
    print('Built subpath preview: http://127.0.0.1:5174/Bible_talking/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 5174), Proxy).serve_forever()
