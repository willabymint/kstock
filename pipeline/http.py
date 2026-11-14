import hashlib
import os
import threading
import time
from pathlib import Path

import requests

CACHE = Path(os.getenv("CACHE_DIR", ".cache"))
_lock = threading.Lock()
_last = [0.0]


class Http:
    """요청 간격 제한 + 재시도 + 디스크 캐시(ttl 시간 단위)."""

    def __init__(self, min_interval: float = 0.12):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        self.min_interval = min_interval
        CACHE.mkdir(exist_ok=True, parents=True)

    def _wait(self):
        with _lock:
            dt = time.time() - _last[0]
            if dt < self.min_interval:
                time.sleep(self.min_interval - dt)
            _last[0] = time.time()

    def get(self, url, params=None, ttl_h: float = 0, encoding=None, binary=False):
        key = hashlib.sha1((url + repr(sorted((params or {}).items()))).encode()).hexdigest()
        f = CACHE / key
        if ttl_h and f.exists() and time.time() - f.stat().st_mtime < ttl_h * 3600:
            data = f.read_bytes()
        else:
            last = None
            for i in range(3):
                try:
                    self._wait()
                    r = self.s.get(url, params=params, timeout=25)
                    r.raise_for_status()
                    data = r.content
                    if ttl_h:
                        f.write_bytes(data)
                    break
                except Exception as e:  # noqa: BLE001
                    last = e
                    time.sleep(1.5 * (i + 1))
            else:
                raise last
        if binary:
            return data
        if encoding == "auto":  # 네이버는 페이지마다 utf-8 / euc-kr 이 섞여 있음
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode("cp949", errors="replace")
        return data.decode(encoding or "utf-8", errors="replace")
