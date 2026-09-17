"""Local event processing; no retrieval or network services."""
from .processor import Processor, Result
from .store import Store

__all__ = ['Processor', 'Result', 'Store']
