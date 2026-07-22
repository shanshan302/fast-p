"""兼容旧导入；新代码按 collection/rules/data/workflow 能力边界使用。"""

from .collection import CollectionError, CollectorWorker
from .data import Store, export_results, fingerprint, load_rows, make_export
from .rules import (
    brand_matches,
    brand_variants,
    find_match,
    model_matches,
    number,
    qualifying_tiers,
)
from .workflow import Cancelled, JobRunner


FastCliError = CollectionError

__all__ = [
    "Cancelled",
    "CollectionError",
    "CollectorWorker",
    "FastCliError",
    "JobRunner",
    "Store",
    "brand_matches",
    "brand_variants",
    "export_results",
    "find_match",
    "fingerprint",
    "load_rows",
    "make_export",
    "model_matches",
    "number",
    "qualifying_tiers",
]
