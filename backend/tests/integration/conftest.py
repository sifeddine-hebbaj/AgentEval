"""Shared fixtures for integration tests.

Disposes the async SQLAlchemy connection pool after every test. Without
this, pooled asyncpg connections from one test's event loop leak into
the next test's (different) event loop and asyncpg raises
"attached to a different loop" -- a well-known pitfall when mixing
per-test event loops with a module-level async engine.
"""
import pytest

from agenteval_api.db import engine


@pytest.fixture(autouse=True)
def _dispose_engine_pool_after_test():
    """Sync fixture (works for both sync SDK tests and async API tests).

    Runs teardown in a fresh event loop via asyncio.run() rather than as
    an async fixture, since pytest has no built-in way to await an async
    autouse fixture for a plain sync test function.
    """
    yield
    import asyncio

    try:
        asyncio.run(engine.dispose())
    except RuntimeError:
        pass  # no event loop available at teardown time; nothing to clean up


@pytest.fixture
def anyio_backend():
    return "asyncio"
