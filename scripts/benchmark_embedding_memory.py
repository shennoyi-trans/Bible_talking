"""Offline, isolated model-memory comparison; does not open the library database.

Run once with --baseline, then without it, using separate output paths.
The baseline reproduces the previous 4-thread, batch-64, arena-enabled settings.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ['HF_HUB_OFFLINE'] = '1'


def memory_mib():
    if sys.platform == 'win32':
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                    'PagefileUsage', 'PeakPagefileUsage')]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        current, peak = counters.WorkingSetSize, counters.PeakWorkingSetSize
    elif sys.platform == 'linux':
        stats = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
        current = int(stats['VmRSS'].split()[0]) * 1024
        peak = int(stats['VmHWM'].split()[0]) * 1024
    else:
        raise RuntimeError('This benchmark supports Windows and Linux')
    return {'rss_mib': round(current / 2**20, 1), 'peak_rss_mib': round(peak / 2**20, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from backend.config import Settings
    from backend.vectors import Embedder
    import numpy as np

    settings = Settings()
    settings.validate()
    texts = [(f'第{i}段。' + '今天的风很轻，我们走到河边谈论生活，希望明天也能平安喜乐。' * 24)
             for i in range(64)]
    report = {'mode': 'baseline' if args.baseline else 'low-resource',
              'platform': sys.platform, 'texts': len(texts), 'before': memory_mib()}
    start = time.monotonic()
    if args.baseline:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=settings.embedding_model,
            cache_dir=os.getenv('MODEL_CACHE_DIR', str(settings.data_dir / 'models')), threads=4)
        vectors = [v.tolist() for v in model.passage_embed(texts, batch_size=64)]
        query = [v.tolist() for v in model.query_embed(['愿你平安'], batch_size=64)]
    else:
        model = Embedder(settings)
        vectors = model.encode(texts)
        query = model.encode(['愿你平安'], query=True)
    report['encode_seconds'] = round(time.monotonic() - start, 2)
    report['after_encode'] = memory_mib()
    if not args.baseline:
        # Advance the last-use timestamp instead of sleeping for a minute.
        model.last_used -= settings.embedding_idle_seconds + 1
        model.release_if_idle()
        assert model.model is None
    report['after_idle'] = memory_mib()
    if not args.baseline:
        reloaded = model.encode(['愿你平安'], query=True)
        report['reload_max_abs_difference'] = float(np.max(np.abs(np.array(query) - reloaded)))
        model.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output.with_suffix('.npz'), vectors=np.array(vectors), query=np.array(query))
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
