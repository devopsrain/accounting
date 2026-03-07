"""
Shared Flask extensions — instantiated here, initialised via init_app() in app.py.
Import from this module to avoid circular dependencies.

Both Flask-Limiter and Flask-Caching are optional at import time; no-op stubs are
provided so the rest of the application loads cleanly even if the packages are not
yet installed.  init_app() calls are guarded by the same flags in app.py.
"""

# ── Rate limiter ──────────────────────────────────────────────────
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
    LIMITER_AVAILABLE = True
except ImportError:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "Flask-Limiter not installed; rate-limiting is disabled. "
        "Run: pip install Flask-Limiter>=3.5.0"
    )

    class _NoLimiter:
        """No-op stub used when Flask-Limiter is not installed."""
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def init_app(self, app):
            pass

    limiter = _NoLimiter()
    LIMITER_AVAILABLE = False

# ── Response cache ────────────────────────────────────────────────
try:
    from flask_caching import Cache
    cache = Cache()
    CACHE_AVAILABLE = True
except ImportError:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "Flask-Caching not installed; caching is disabled. "
        "Run: pip install Flask-Caching>=2.1.0"
    )

    class _NoCache:
        """No-op stub used when Flask-Caching is not installed."""
        def get(self, key):
            return None
        def set(self, key, value, timeout=None):
            pass
        def delete(self, key):
            pass
        def cached(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def init_app(self, app, config=None):
            pass

    cache = _NoCache()
    CACHE_AVAILABLE = False
