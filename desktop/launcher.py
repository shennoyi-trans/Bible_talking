"""Windows desktop entry: WebView2 UI and an owned loopback-only API."""
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, 'Bible_talking', 0x40)


def main():
    smoke = '--smoke-test' in sys.argv
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    portable = (base / 'portable.txt').exists()
    default_data = base / 'data' if portable else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Bible_talking'
    data = Path(os.environ.get('BIBLE_TALKING_DATA_DIR', default_data))
    data.mkdir(parents=True, exist_ok=True)
    log_file = open(data / 'desktop.log', 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log_file
    logging.basicConfig(stream=log_file, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    import portalocker
    lock = portalocker.Lock(str(data / 'desktop.lock'), timeout=0)
    try:
        lock.acquire()
    except portalocker.exceptions.LockException:
        if not smoke:
            message('Bible_talking已经运行，请切换到已打开的窗口。')
        return 2

    models = Path(os.environ.get('MODEL_CACHE_DIR', base / 'models' if (base / 'models').exists() else data / 'models'))
    os.environ['MODEL_CACHE_DIR'] = str(models)
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    if (base / 'models').exists():
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
    # The desktop profile is independent of development data and server configuration.
    from backend.config import Settings
    from backend.main import create_app
    from fastapi.responses import JSONResponse, RedirectResponse
    import uvicorn

    settings = Settings(data_dir=data / 'library', qdrant_url='', preload=not smoke, worker_enabled=not smoke)
    app = create_app(settings)
    secret = secrets.token_urlsafe(32)

    @app.middleware('http')
    async def desktop_session(request, call_next):
        if request.url.path == '/desktop/' + secret:
            response = RedirectResponse('/')
            response.set_cookie('Bible_talking_desktop', secret, httponly=True, samesite='strict')
            return response
        supplied = request.cookies.get('Bible_talking_desktop', '') or request.headers.get('x-Bible_talking-desktop', '')
        if not secrets.compare_digest(supplied, secret):
            return JSONResponse({'detail': '请从Bible_talking桌面窗口打开。'}, status_code=403)
        return await call_next(request)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None,
        access_log=False, loop='asyncio', http='h11', ws='none'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True, name='desktop-api')
    thread.start()

    def await_ready():
        deadline = time.monotonic() + 300
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('本地服务未能启动，请查看 desktop.log。')
            time.sleep(.1)

    try:
        if smoke:
            await_ready()
            # Load the same native bridge/DLLs used by the real window.
            from webview.guilib import initialize
            renderer = initialize('edgechromium')
            assert renderer.renderer == 'edgechromium'
            import httpx
            with httpx.Client(base_url=url, headers={'x-Bible_talking-desktop': secret}, trust_env=False, timeout=120) as client:
                assert client.get('/api/health').status_code == 200
                assert '<div id="app">' in client.get('/').text
                assert httpx.get(url + '/api/corpora', trust_env=False).status_code == 403
                builtin_count = 0
                corpora = client.get('/api/corpora').json()
                if any(c['corpus_id'] == 'corpus_cuv' for c in corpora):
                    builtin = client.post('/api/search', json={'corpus_id': 'corpus_cuv', 'query': '可以给我水喝吗？'}).json()
                    assert len(builtin['results']) == 50 and '水' in builtin['results'][0]['text'], builtin
                    builtin_count = len(builtin['results'])
                corpus = client.post('/api/corpora', json={'name': '打包验证'}).json()['corpus_id']
                upload = client.post(f'/api/corpora/{corpus}/resources',
                    files={'file': ('sample.txt', '请你给我水喝。\n你要去哪里？'.encode('utf-8'))})
                upload.raise_for_status()
                app.state.library.process_one()
                result = client.post('/api/search', json={'corpus_id': corpus, 'query': '给我水喝'}).json()
                assert len(result['results']) == 2, result
                assert '水' in result['results'][0]['text'], result
                report = {'ok': True, 'model': settings.embedding_model, 'results': len(result['results']),
                    'static_ui': True, 'session_protection': True, 'renderer': renderer.renderer, 'bible_results': builtin_count}
                (data / 'smoke-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            return 0

        import webview
        window = webview.create_window('Bible_talking', html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <style>body{background:#f8f7f3;color:#285646;font:16px "Microsoft YaHei";padding:12vh 8vw;line-height:2}h1{font-family:SimSun;font-size:32px}p{color:#7b8776}</style>
            <h1>Bible_talking</h1><p>正在打开本地语料库…</p></html>''',
            width=1080, height=800, min_size=(360, 500), background_color='#f8f7f3')

        def connect():
            try:
                await_ready()
                window.load_url(url + '/desktop/' + secret)
            except Exception:
                logging.exception('Desktop startup failed')
                window.load_html('<h2>启动失败</h2><p>请关闭后重试，或检查 data/desktop.log。</p>')

        webview.start(connect, gui='edgechromium', private_mode=True)
        return 0
    except Exception:
        logging.exception('Desktop error')
        if not smoke:
            message('启动失败。请确认已安装 Microsoft Edge WebView2 Runtime。\n详细信息：' + str(data / 'desktop.log'))
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=35)
        listener.close()
        lock.release()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
