from __future__ import annotations

import builtins
import logging

if not hasattr(builtins, "logging"):
    builtins.logging = logging

__all__ = ["logging"]
