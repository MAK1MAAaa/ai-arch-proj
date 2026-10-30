"""Paths and versioned retrieval contracts shared by preparation and serving."""

import os
from pathlib import Path

MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
TEXT_VERSION = "e5-document-v1"
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_HOME = Path(os.environ.get("ARCHSEARCH_HOME", Path.cwd() / ".archsearch"))
PERIOD_LABEL = "地中海罗马资料与全球历史遗址（古代至近现代）"
TYPE_LABELS = {
    "settlement": "聚落",
    "villa": "别墅庄园",
    "port": "港口",
    "bath": "浴场",
    "theatre": "剧场",
    "archaeological-site": "考古遗址",
    "historic-site": "历史遗址",
}
