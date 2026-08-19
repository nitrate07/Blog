"""Rate limiting, caching, and retry utilities."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def acquire(self, key: str = "default") -> bool:
        """Acquire a rate limit token. Returns True if allowed."""
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            
            # Remove old requests
            self.requests[key] = [t for t in self.requests[key] if t > cutoff]
            
            if len(self.requests[key]) < self.max_requests:
                self.requests[key].append(now)
                return True
            return False
    
    async def wait(self, key: str = "default") -> None:
        """Wait until a token is available."""
        while not await self.acquire(key):
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class Cache:
    """Simple in-memory cache with optional persistence."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600.0) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}
        self._access_times: dict[str, float] = {}
    
    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        if key in self._cache:
            value, created_at = self._cache[key]
            if time.time() - created_at < self.ttl_seconds:
                self._access_times[key] = time.time()
                return value
            else:
                del self._cache[key]
                del self._access_times[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        if len(self._cache) >= self.max_size:
            self._evict()
        self._cache[key] = (value, time.time())
        self._access_times[key] = time.time()
    
    def _evict(self) -> None:
        """Evict least recently used items."""
        if not self._access_times:
            return
        oldest_key = min(self._access_times, key=self._access_times.get)
        del self._cache[oldest_key]
        del self._access_times[oldest_key]
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._access_times.clear()
    
    @property
    def size(self) -> int:
        return len(self._cache)


class DiskCache:
    """Persistent disk cache."""
    
    def __init__(self, cache_dir: str = ".cache/evidence", max_size: int = 10000) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self._index: dict[str, float] = {}
        self._load_index()
    
    def _load_index(self) -> None:
        index_file = self.cache_dir / "index.json"
        if index_file.exists():
            try:
                self._index = json.loads(index_file.read_text())
            except Exception:
                self._index = {}
    
    def _save_index(self) -> None:
        index_file = self.cache_dir / "index.json"
        index_file.write_text(json.dumps(self._index))
    
    def _make_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
    
    def get(self, url: str) -> str | None:
        """Get cached response for URL."""
        key = self._make_key(url)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if time.time() - data.get("timestamp", 0) < 86400:  # 24h TTL
                    return data.get("content")
            except Exception:
                pass
        return None
    
    def set(self, url: str, content: str) -> None:
        """Cache response for URL."""
        if len(self._index) >= self.max_size:
            self._evict()
        
        key = self._make_key(url)
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps({
            "url": url,
            "content": content,
            "timestamp": time.time(),
        }))
        self._index[url] = time.time()
        self._save_index()
    
    def _evict(self) -> None:
        """Evict oldest entries."""
        if not self._index:
            return
        oldest_url = min(self._index, key=self._index.get)
        key = self._make_key(oldest_url)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            cache_file.unlink()
        del self._index[oldest_url]
        self._save_index()


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

async def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """Retry a function with exponential backoff."""
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                await asyncio.sleep(delay)
    raise last_exception
