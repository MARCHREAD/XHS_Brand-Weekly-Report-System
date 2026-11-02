"""Vendored pure-Python signer adapted from xhshow 0.2.0 (MIT)."""

from .client import Xhshow
from .config import CryptoConfig
from .core.crypto import CryptoProcessor
from .session import SessionManager, SignState

__version__ = "0.2.0-vendored"
__all__ = ["CryptoConfig", "CryptoProcessor", "SessionManager", "SignState", "Xhshow"]
