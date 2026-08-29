"""Gorsel/ekran goruntusu isleme — OCR tabanli iddia metni cikarimi.

Bu paket, roadmap'te (docs/ai-infrastructure-roadmap.md, Bolum 5) "tamamen
bos" olarak isaretlenen gorsel kanal icin ilk somut adimdir: bir ekran
goruntusundeki (viral bir saglik iddiasi paylasimi gibi) metni cikarip
mevcut metin-tabanli dogrulama hattina (has_health_topic, build_search_query,
Planner/EvidenceInvestigator) sokmayi saglar.

Kapsam disi (bilerek): "bu gorselde ne var" tarzi coklu-modlu analiz
(ClaudeProvider/GeminiProvider'a gorsel-kodlama eklemek gerekir — ayri is),
ters gorsel arama, ve AI-uretimi gorsel tespiti. Bu paket yalnizca OCR
(metin cikarimi) yapar.
"""

from .ocr import OcrResult, extract_text_from_image, is_ocr_available

__all__ = ["OcrResult", "extract_text_from_image", "is_ocr_available"]
