"""
Shared Flask extensions — instantiated here, initialised via init_app() in app.py.
Import from this module to avoid circular dependencies.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

# Rate limiter — no default limits; apply per-route with @limiter.limit(...)
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# Response cache — SimpleCache for single-instance; swap to RedisCache for multi-instance.
# Configured via init_app() in app.py.
cache = Cache()
