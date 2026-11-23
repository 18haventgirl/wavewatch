"""Keep Windows from going to sleep on its own while the monitor runs (optional).

Uses SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) from a dedicated
thread.  The display can still turn off, and manual sleep / shutdown still work.
On other systems this is a no-op.
"""
from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

SUPPORTED = sys.platform == 'win32'


def keep_awake(enabled: bool) -> bool:
    if not SUPPORTED:
        return False
    import ctypes
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if enabled else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
