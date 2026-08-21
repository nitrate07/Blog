"""Pytest ortak yapilandirmasi.

Auto-index testlerde kapali: her create_app cagrisinda 82 makalenin
yeniden endekslenmesi test paketini gereksiz yere yavaslatir.
RAG entegrasyonunun kendisi test_rag_*.py ve ozel isaretli testlerde kapsanir.
"""

import os

os.environ.setdefault("EVIDENCE_AUTO_INDEX", "0")
