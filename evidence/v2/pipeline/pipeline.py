"""Evidence Pipeline — the complete verification chain.

Flow:
1. Claim Extraction (rule-based, no LLM)
2. Source Discovery (21 sources in parallel — 20 external + archive)
3. Passage Verification (verify against original sources)
4. Evidence Engine (hakem — deterministic, no LLM)
5. Contradiction Detection (find conflicting evidence)
6. LLM Interpreter (yorumcu — explains verdict)
7. Graph Update (records the chain)
8. Verification History (persistent record)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..core.database import EvidenceDatabase
from ..core.interfaces import EvidenceEngine, SourceAgent
from ..core.types import (
    Claim,
    Contradiction,
    Evidence,
    MethodologicalEvidence,
    Passage,
    Source,
    SourceType,
    VerificationChain,
    VerificationRecord,
    Verdict,
    content_hash,
    make_claim_id,
    make_evidence_id,
    make_passage_id,
    make_source_id,
    make_verification_id,
)
from ..engine.contradiction import ContradictionDetector
from ..engine.engine import SOURCE_TYPE_MAP
from ..engine.verifier import PassageVerifier
from ..sources.orchestrator import SourceOrchestrator

logger = logging.getLogger(__name__)

# Verdict string → Verdict enum
VERDICT_MAP: dict[str, Verdict] = {
    "supported": Verdict.SUPPORTED,
    "mostly supported": Verdict.MOSTLY_SUPPORTED,
    "mostly_supported": Verdict.MOSTLY_SUPPORTED,
    "partly supported": Verdict.PARTLY_SUPPORTED,
    "partly_supported": Verdict.PARTLY_SUPPORTED,
    "misleading": Verdict.MISLEADING,
    "unsupported": Verdict.UNSUPPORTED,
    "unverified": Verdict.UNVERIFIED,
}


# ---------------------------------------------------------------------------
# Step 1: Claim Extraction
# ---------------------------------------------------------------------------

# Turkish to English query translations for common health queries
TURKISH_TO_ENGLISH_QUERIES: dict[str, str] = {
    "glp-1 kilo kaybı": "GLP-1 weight loss semaglutide obesity",
    "glp-1 obezite": "GLP-1 obesity treatment semaglutide",
    "egzersiz kalp": "exercise heart health cardiovascular",
    "egzersiz faydalı": "exercise benefits health",
    "vitamin d eksikliği": "vitamin D deficiency health effects",
    "vitamin d osteoporoz": "vitamin D osteoporosis bone health",
    "probiyotik sindirim": "probiotic gut health digestion",
    "probiyotik bağırsak": "probiotic microbiome gut health",
    "aşı otizm": "vaccine autism safety evidence",
    "aşı yan etki": "vaccine side effects safety",
    "aspirin kalp": "aspirin cardiovascular heart prevention",
    "aspirin fayda": "aspirin benefits risks",
    "ibuprofen ağrı": "ibuprofen pain relief anti-inflammatory",
    "omega-3 kalp": "omega-3 cardiovascular heart health",
    "omega-3 iltihap": "omega-3 inflammation anti-inflammatory",
    "metformin diyabet": "metformin diabetes type 2 treatment",
    "protein kas": "protein muscle growth exercise",
    "kolon kanseri": "colon cancer prevention screening",
    "meme kanseri": "breast cancer screening prevention",
    "diyabet tip 2": "type 2 diabetes treatment management",
    "hipertansiyon": "hypertension blood pressure treatment",
    "kolesterol": "cholesterol heart disease statin",
    "osteoporoz": "osteoporosis bone density calcium",
    " depresyon": "depression treatment exercise",
    "anksiyete": "anxiety treatment management",
    "uyku": "sleep health effects quality",
    "stres": "stress health effects management",
    "bilişsel": "cognitive function brain health memory",
    "enflamasyon": "inflammation chronic disease health",
    "bağışıklık": "immune system immunity health",
    "alerji": "allergy treatment antihistamine",
    "karaciğer": "liver health fatty liver disease",
    "böbrek": "kidney health chronic kidney disease",
    "tiroid": "thyroid health hypothyroidism",
    "prostat": "prostate health cancer screening",
    "göz": "eye health vision macular degeneration",
    "cilt": "skin health aging collagen",
    "saç": "hair loss treatment",
    "yaşlanma": "aging longevity anti-aging",
    "kilo vermek": "weight loss obesity diet exercise",
    "diyet": "diet weight loss nutrition health",
    "beslenme": "nutrition healthy eating diet",
    "antibiyotik": "antibiotic resistance bacterial infection",
    "steroid": "steroid side effects corticosteroid",
    "ilaç etkileşim": "drug interaction medication safety",
    "yan etki": "side effects medication safety",
}


def translate_query_to_english(query: str) -> str:
    """Translate Turkish query to English for PubMed/Crossref searches."""
    query_lower = query.lower()
    
    # Check if query is already mostly in English
    turkish_chars = set("çğıöşüâîûêÇĞIİÖŞÜ")
    turkish_word_count = sum(1 for c in query if c in turkish_chars)
    if turkish_word_count < 3:
        return query
    
    # Try to find matching Turkish phrases
    best_match = None
    best_score = 0
    
    for tr_key, en_value in TURKISH_TO_ENGLISH_QUERIES.items():
        # Count how many words from tr_key appear in query
        tr_words = tr_key.split()
        matches = sum(1 for w in tr_words if w in query_lower)
        score = matches / len(tr_words) if tr_words else 0
        
        if score > best_score:
            best_score = score
            best_match = en_value
    
    if best_match and best_score >= 0.5:
        return best_match
    
    # Fallback: try to extract English terms and create a query
    import re
    # Find words that look like English medical terms
    english_terms = re.findall(
        r'\b(?:GLP|vitamin|omega|probiotic|aspirin|ibuprofen|metformin|exercise|diabetes|cancer|heart|obesity|weight|diet|supplement|vaccine|antibiotic|steroid)\b',
        query, re.IGNORECASE
    )
    
    if english_terms:
        return " ".join(english_terms) + " health effects"
    
    # Last resort: return original
    return query


def extract_claim(user_query: str) -> str:
    """Extract the core claim from a user query. No LLM — pure rule-based."""
    query = user_query.strip()
    
    # Remove common prefixes
    prefixes = [
        "is it true that", "does ", "can ", "should ", "is ",
        "are ", "what about ", "tell me about ", "explain ",
        "verify ", "check ", "fact check ", "did ",
        "bana söyle ", "anlat ", "doğrula ", "kontrol et ",
        "hakkında bilgi ver ", "nedir ", "nasıl ",
    ]
    for prefix in prefixes:
        if query.lower().startswith(prefix):
            query = query[len(prefix):].strip()
            break
    
    # Remove trailing punctuation
    query = query.rstrip("?!.:")
    
    # Add question mark
    if not query.endswith("?"):
        query = query + "?"
    
    return query


def get_search_query(user_query: str) -> str:
    """Get the best search query for external sources."""
    # Translate Turkish to English for PubMed/Crossref
    translated = translate_query_to_english(user_query)
    # Extract claim from translated query
    return extract_claim(translated)


# ---------------------------------------------------------------------------
# Step 2: Source Discovery
# ---------------------------------------------------------------------------

async def discover_sources(
    claim: str,
    orchestrator: SourceOrchestrator,
    limit_per_agent: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Search ALL evidence sources in parallel."""
    result = await orchestrator.search(claim, limit_per_agent=limit_per_agent)
    all_results = result.get("results", [])
    
    archive = [r for r in all_results if r.get("source") == "archive"]
    external = [r for r in all_results if r.get("source") in (
        "pubmed", "crossref", "nejm", "jama", "lancet", "bmj"
    )]
    health_orgs = [r for r in all_results if r.get("source") not in (
        "archive", "pubmed", "crossref", "nejm", "jama", "lancet", "bmj"
    )]
    
    return archive, external, health_orgs


# ---------------------------------------------------------------------------
# Step 3: Passage Verification
# ---------------------------------------------------------------------------

async def verify_passages(
    passages: list[Passage],
    sources: dict[str, Source],
) -> list[dict[str, Any]]:
    """Verify passages against original sources."""
    verifier = PassageVerifier()
    
    source_urls = {s.id: s.url for s in sources.values()}
    verifications = await verifier.verify_passages(passages, source_urls)
    
    return [v.to_dict() for v in verifications]


# ---------------------------------------------------------------------------
# Step 4: Evidence Engine (hakem)
# ---------------------------------------------------------------------------

def run_engine(
    engine: EvidenceEngine,
    claim: str,
    archive: list[dict[str, Any]],
    external: list[dict[str, Any]],
    health_orgs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the evidence engine to judge the claim."""
    return engine.judge(claim, archive, external, health_orgs)


# ---------------------------------------------------------------------------
# Step 5: Contradiction Detection
# ---------------------------------------------------------------------------

def detect_contradictions(
    claim_id: str,
    sources: list[Source],
    matches: list[dict[str, Any]],
) -> list[Contradiction]:
    """Detect contradictions between sources."""
    detector = ContradictionDetector()
    return detector.detect(claim_id, sources, matches)


# ---------------------------------------------------------------------------
# Step 6: LLM Interpreter (yorumcu)
# ---------------------------------------------------------------------------

async def interpret_with_llm(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
    llm_provider: Any | None = None,
    use_chat: bool = False,
) -> str:
    """Interpret the verdict in natural language.
    
    If no LLM provider, use rule-based response.
    LLM is ONLY used as an interpreter — never as evidence source.
    
    Args:
        use_chat: If True, uses chat method with conversation history.
    """
    if llm_provider and hasattr(llm_provider, "generate"):
        try:
            prompt = _build_interpreter_prompt(
                claim, verdict, confidence, matches,
                contradictions, supporting, contradicting,
            )
            
            if use_chat and hasattr(llm_provider, "chat"):
                # Use chat with conversation history
                return await llm_provider.chat(prompt, keep_history=True)
            else:
                # Use single-shot generate
                return await llm_provider.generate(prompt)
        except Exception as e:
            logger.warning(f"LLM interpreter failed, falling back to rule-based: {e}")
    
    return _build_rule_based_response(
        claim, verdict, confidence, matches,
        contradictions, supporting, contradicting,
    )


def _build_interpreter_prompt(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
) -> str:
    """Build prompt for LLM interpreter."""
    evidence_text = ""
    for i, m in enumerate(matches[:5], 1):
        title = m.get("title", "Unknown")
        url = m.get("url", "")
        text = m.get("text", "")[:200]
        quality = m.get("quality_score", 0)
        evidence_text += f"{i}. {title}\n   URL: {url}\n   Quality: {quality:.0%}\n   Excerpt: {text}...\n\n"
    
    contradiction_text = ""
    if contradictions:
        contradiction_text = "\nContradictions detected:\n"
        for c in contradictions:
            contradiction_text += f"- {c.description}\n"
    
    return f"""You are a fact-checking interpreter for Arı Kaynak.

Claim: {claim}
Verdict: {verdict}
Confidence: {confidence:.0%}

Evidence sources:
{evidence_text}
{contradiction_text}
Supporting sources: {len(supporting)}
Contradicting sources: {len(contradicting)}

Explain the verdict in 2-3 sentences. Reference the evidence sources.
Be factual and cite sources. Do NOT generate new evidence.
If there are contradictions, explain why the verdict was still given."""


def _build_rule_based_response(
    claim: str,
    verdict: str,
    confidence: float,
    matches: list[dict[str, Any]],
    contradictions: list[Contradiction],
    supporting: list[str],
    contradicting: list[str],
) -> str:
    """Build detailed, contextual response without LLM."""
    verdict_display = verdict.replace("_", " ").title()
    confidence_pct = round(confidence * 100)
    
    # Claim analysis
    claim_clean = claim.rstrip("?").strip()
    claim_lower = claim_clean.lower()
    
    # Extract key topic from claim
    topic = _extract_topic(claim_lower)
    
    lines = []
    
    # Header
    lines.append(f"## {claim_clean}")
    lines.append("")
    
    # Verdict badge
    verdict_emoji = {
        "Supported": "✅", "Mostly Supported": "🟢",
        "Partly Supported": "🟡", "Misleading": "🟠",
        "Unsupported": "❌", "Unverified": "⚪",
    }.get(verdict_display, "⚪")
    
    lines.append(f"**Hüküm:** {verdict_emoji} {verdict_display}")
    lines.append(f"**Güven:** %{confidence_pct}")
    lines.append("")
    
    # Summary
    lines.append("### Özet")
    lines.append("")
    summary = _build_summary(claim_clean, verdict, confidence, matches, topic)
    lines.append(summary)
    lines.append("")
    
    # Evidence analysis
    if matches:
        lines.append("### Kanıt Analizi")
        lines.append("")
        
        # Filter relevant matches
        relevant = [m for m in matches if m.get("relevance", 0) > 0.1][:5]
        
        if relevant:
            for i, m in enumerate(relevant, 1):
                title = m.get("title", "Bilinmeyen kaynak")
                url = m.get("url", "")
                source_type = m.get("source_type", "unknown")
                quality = m.get("quality_score", 0)
                journal = m.get("journal", "")
                text = m.get("text", "")[:300]
                year = m.get("published_year", "")
                
                lines.append(f"**Kaynak {i}:** {title}")
                if url:
                    lines.append(f"🔗 [{url}]({url})")
                if journal:
                    lines.append(f"📖 {journal}" + (f" ({year})" if year else ""))
                lines.append(f"📊 Kaynak Kalitesi: {quality:.0%} | Tip: {source_type}")
                
                # Extract relevant excerpt
                if text:
                    excerpt = _extract_relevant_excerpt(text, claim_lower, topic)
                    if excerpt:
                        lines.append(f"> {excerpt}")
                lines.append("")
        else:
            lines.append("Bu konuda doğrudan kanıt bulunamadı.")
            lines.append("")
    
    # Methodology note
    lines.append("### Yöntem Notu")
    lines.append("")
    methodology = _build_methodology_note(matches, topic)
    lines.append(methodology)
    lines.append("")
    
    # Contradictions
    if contradictions:
        lines.append("### Çelişkiler")
        lines.append("")
        for c in contradictions:
            lines.append(f"⚠️ {c.description}")
        lines.append("")
    
    # Source breakdown
    lines.append("### Kaynak Dağılımı")
    lines.append("")
    source_stats = _analyze_sources(matches)
    lines.append(f"- **Toplam Kaynak:** {len(matches)}")
    lines.append(f"- **Birincil Kaynak (RCT, Koort):** {source_stats['primary']}")
    lines.append(f"- **İkincil Kaynak (Derleme, Meta-analiz):** {source_stats['secondary']}")
    lines.append(f"- **Üçüncül Kaynak (Kılavuz, Kurum):** {source_stats['tertiary']}")
    lines.append(f"- **Ortalama Kaynak Kalitesi:** %{source_stats['avg_quality']:.0f}")
    lines.append("")
    
    # Confidence explanation
    lines.append("### Güven Açıklaması")
    lines.append("")
    confidence_explanation = _explain_confidence(confidence, source_stats, contradictions)
    lines.append(confidence_explanation)
    lines.append("")
    
    # Footer
    lines.append("---")
    lines.append("*Arı Kaynak Evidence Engine tarafından oluşturuldu. Kanıt yalnızca doğrulanmış kaynaklardan alınmıştır.*")
    
    return "\n".join(lines)


def _extract_topic(claim_lower: str) -> str:
    """Extract main topic from claim."""
    topics = {
        "glp-1": ["glp-1", "glp1", "semaglutide", "liraglutide", "ozempic", "wegovy"],
        "egzersiz": ["egzersiz", "exercise", "physical activity", "fiziksel aktivite"],
        "kalp": ["kalp", "heart", "cardiovascular", "kardiyovasküler", "cardiac"],
        "kanser": ["kanser", "cancer", "tumor", "tümör"],
        "diyabet": ["diyabet", "diabetes", "insulin", "insülin"],
        "vitamin d": ["vitamin d", "vitamin d3", "d vitamini"],
        "omega-3": ["omega-3", "omega 3", "fish oil", "balık yağı"],
        "probiyotik": ["probiyotik", "probiotic", "microbiome", "mikrobiyom"],
        "aşı": ["aşı", "vaccine", "vaccination", "aşılama"],
        "ilaç": ["drug", "medication", "ilaç", "pharmaceutical"],
        "beslenme": ["nutrition", "beslenme", "diet", "diyet", "food", "gıda"],
        "uyku": ["sleep", "uyku", "insomnia", "uykusuzluk"],
        "stres": ["stress", "stres", "anxiety", "kaygı", "mental health"],
        "kas": ["muscle", "kas", "strength", "güç", "protein"],
        "kilo": ["weight", "kilo", "obesity", "obezite", "slimming"],
    }
    
    for topic, keywords in topics.items():
        for kw in keywords:
            if kw in claim_lower:
                return topic
    
    return "genel sağlık"


def _extract_relevant_excerpt(text: str, claim_lower: str, topic: str) -> str:
    """Extract the most relevant excerpt from passage."""
    sentences = text.replace("\n", " ").split(". ")
    
    # Score sentences by relevance
    scored = []
    claim_words = set(claim_lower.split())
    topic_words = set(topic.split()) if topic else set()
    
    for sent in sentences:
        sent_lower = sent.lower()
        score = 0
        
        # Direct claim word matches
        for word in claim_words:
            if word in sent_lower:
                score += 2
        
        # Topic word matches
        for word in topic_words:
            if word in sent_lower:
                score += 1
        
        # Scientific indicators
        indicators = ["found", "showed", "demonstrated", "associated", "risk",
                      "benefit", "effective", "significant", "result", "study",
                      "bulundu", "gösterdi", "ortaya", "sonuç", "etkili"]
        for ind in indicators:
            if ind in sent_lower:
                score += 1
        
        if score > 0:
            scored.append((score, sent.strip()))
    
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        if len(best) > 400:
            best = best[:400] + "..."
        return best
    
    # Fallback: return first meaningful sentence
    for sent in sentences:
        if len(sent) > 30:
            return sent[:400] + ("..." if len(sent) > 400 else "")
    
    return text[:400] + ("..." if len(text) > 400 else "")


def _build_summary(claim: str, verdict: str, confidence: float, matches: list, topic: str) -> str:
    """Build a detailed summary based on evidence."""
    if not matches:
        return f"Bu konuda yeterli kanıt bulunamadı. {topic.title()} hakkında güvenilir kaynaklardan bilgi edinmek için sağlık kuruluşlarının web sitelerini kontrol etmenizi öneririz."
    
    # Count evidence types
    relevant = [m for m in matches if m.get("relevance", 0) > 0.1]
    
    verdict_map = {
        "supported": "desteklenmektedir",
        "mostly_supported": "çoğunlukla desteklenmektedir",
        "partly_supported": "kısmen desteklenmektedir",
        "misleading": "yanıltıcı bilgi içermektedir",
        "unsupported": "desteklenmemektedir",
        "unverified": "henüz doğrulanmamıştır",
    }
    
    verdict_tr = verdict_map.get(verdict, "değerlendirilmemiştir")
    
    summary = f"Yapılan **{len(relevant)} kaynak** incelemesi sonucunda, bu iddia **{verdict_tr}**. "
    
    if confidence >= 0.7:
        summary += "Bu hüküm yüksek güvenilirliğe sahiptir. "
    elif confidence >= 0.5:
        summary += "Bu hüküm orta düzeyde güvenilirliğe sahiptir. "
    else:
        summary += "Bu hüküm düşük güvenilirliğe sahiptir, ek kanıtlara ihtiyaç vardır. "
    
    # Add topic-specific context
    if topic != "genel sağlık":
        summary += f"\n\n**{topic.title()}** hakkında bilimsel literatür incelendi ve elde edilen kanıtlar değerlendirildi."
    
    return summary


def _build_methodology_note(matches: list, topic: str) -> str:
    """Build methodology note based on source types."""
    source_types = set(m.get("source_type", "unknown") for m in matches)
    
    note = "Bu değerlendirmede aşağıdaki kaynak türleri kullanılmıştır:\n\n"
    
    type_descriptions = {
        "primary": "Birincil kaynaklar (RCT'ler, kohort çalışmaları) - En yüksek kanıt düzeyi",
        "secondary": "İkincil kaynaklar (sistematik derlemeler, meta-analizler) - Yüksek kanıt düzeyi",
        "tertiary": "Üçüncül kaynaklar (klinik kılavuzlar, sağlık kuruluşları) - Güvenilir bilgi kaynağı",
        "academic": "Akademik kaynaklar - Hakemli dergi çalışmaları",
        "international_organization": "Uluslararası sağlık kuruluşları (WHO, CDC) - Resmi bilgi kaynağı",
        "government": "Hükümet kaynakları - Resmi sağlık otoriteleri",
    }
    
    for st in source_types:
        if st in type_descriptions:
            note += f"- {type_descriptions[st]}\n"
    
    note += "\n**Not:** Bu değerlendirme yalnızca doğrulanmış kaynaklardan elde edilen kanıtlara dayanmaktadır."
    
    return note


def _analyze_sources(matches: list) -> dict:
    """Analyze source distribution."""
    primary = 0
    secondary = 0
    tertiary = 0
    total_quality = 0
    count = 0
    
    for m in matches:
        st = m.get("source_type", "unknown")
        quality = m.get("quality_score", 0)
        
        if st in ("primary", "clinical_trial"):
            primary += 1
        elif st in ("secondary", "academic"):
            secondary += 1
        elif st in ("tertiary", "international_organization", "government"):
            tertiary += 1
        
        if quality > 0:
            total_quality += quality
            count += 1
    
    return {
        "primary": primary,
        "secondary": secondary,
        "tertiary": tertiary,
        "avg_quality": (total_quality / count * 100) if count > 0 else 0,
    }


def _explain_confidence(confidence: float, source_stats: dict, contradictions: list) -> str:
    """Explain confidence level."""
    if confidence >= 0.8:
        explanation = "Yüksek güven: "
        if source_stats["primary"] >= 2:
            explanation += "Birden fazla birincil kaynak (RCT, kohort) bulunmaktadır. "
        if source_stats["avg_quality"] >= 70:
            explanation += "Kaynakların ortalama kalitesi yüksektir. "
    elif confidence >= 0.6:
        explanation = "Orta güven: "
        explanation += "Yeterli kanıt mevcut ancak daha fazla birincil kaynak güçlendirici olur. "
    elif confidence >= 0.4:
        explanation = "Düşük-Orta güven: "
        explanation += "Kanıtlar sınırlıdır veya çelişkili bulunmaktadır. "
    else:
        explanation = "Düşük güven: "
        explanation += "Yeterli kanıt bulunmamaktadır. Ek araştırmaya ihtiyaç vardır. "
    
    if contradictions:
        explanation += f"\n\n{len(contradictions)} çelişkili kaynak tespit edildi. Bu durum hüküm güvenilirliğini etkileyebilir."
    
    return explanation


# ---------------------------------------------------------------------------
# Step 7: Graph Update
# ---------------------------------------------------------------------------

def update_graph(
    claim_text: str,
    verdict: str,
    confidence: float,
    rating: int,
    matches: list[dict[str, Any]],
    supporting: list[str],
    contradicting: list[str],
    contradictions: list[Contradiction],
    claims: dict[str, Claim] | None = None,
    sources: dict[str, Source] | None = None,
    passages: dict[str, Passage] | None = None,
    evidence: dict[str, Evidence] | None = None,
) -> dict[str, Any]:
    """Record the verification chain in the Evidence Graph."""
    claim_id = make_claim_id(claim_text)
    verdict_enum = VERDICT_MAP.get(verdict, Verdict.UNVERIFIED)
    
    # Create claim
    claim = Claim(
        id=claim_id,
        text=claim_text,
        author="pipeline",
        category="Health",
        date_filed="",
        file_number=0,
    )
    if claims is not None:
        claims[claim_id] = claim
    
    # Create sources and passages from top matches
    created_sources: list[Source] = []
    created_passages: list[Passage] = []
    
    for m in matches[:5]:
        source_url = m.get("url", "")
        if not source_url:
            continue
        
        source_id = make_source_id(source_url)
        st_str = m.get("source_type", "unknown")
        source = Source(
            id=source_id,
            url=source_url,
            title=m.get("title", ""),
            source_type=SOURCE_TYPE_MAP.get(st_str, SourceType.UNKNOWN),
            journal=m.get("journal"),
            impact_factor=m.get("impact_factor"),
        )
        if sources is not None:
            sources[source_id] = source
        created_sources.append(source)
        
        passage_text = m.get("text", "")[:1000]
        passage = Passage(
            id=make_passage_id(claim_id, len(created_passages)),
            text=passage_text,
            source_id=source_id,
            relevance=m.get("relevance", 0.5),
            content_hash=content_hash(passage_text) if passage_text else None,
        )
        if passages is not None:
            passages[passage.id] = passage
        created_passages.append(passage)
    
    # Create evidence
    ev = Evidence(
        id=make_evidence_id(claim_id),
        claim_id=claim_id,
        passages=created_passages,
        verdict=verdict_enum,
        confidence=confidence,
        rating_value=rating,
        supporting_sources=supporting,
        contradicting_sources=contradicting,
    )
    if evidence is not None:
        evidence[ev.id] = ev
    
    return {
        "claim": claim,
        "sources": created_sources,
        "passages": created_passages,
        "evidence": ev,
        "contradictions": contradictions,
    }


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """Result of running the full verification pipeline."""
    verification_id: str
    query: str
    extracted_claim: str
    archive_results: list[dict]
    external_results: list[dict]
    health_org_results: list[dict]
    passage_verifications: list[dict]
    contradictions: list[dict]
    verdict: str
    verdict_confidence: float
    rating_value: int
    supporting_sources: list[str]
    contradicting_sources: list[str]
    cited_response: str
    steps: list[dict]
    graph_claim_id: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "query": self.query,
            "extracted_claim": self.extracted_claim,
            "archive_results": self.archive_results,
            "external_results": self.external_results,
            "health_org_results": self.health_org_results,
            "passage_verifications": self.passage_verifications,
            "contradictions": self.contradictions,
            "verdict": self.verdict,
            "verdict_confidence": round(self.verdict_confidence, 3),
            "rating_value": self.rating_value,
            "supporting_sources": self.supporting_sources,
            "contradicting_sources": self.contradicting_sources,
            "cited_response": self.cited_response,
            "steps": self.steps,
            "graph_claim_id": self.graph_claim_id,
            "created_at": self.created_at,
        }


class EvidencePipeline:
    """The complete verification pipeline.
    
    Flow:
    1. Claim Extraction (rule-based, no LLM)
    2. Source Discovery (21 sources in parallel — 20 external + archive)
    3. Passage Verification (verify against original sources)
    4. Evidence Engine (hakem — deterministic, no LLM)
    5. Contradiction Detection (find conflicting evidence)
    6. LLM Interpreter (yorumcu — explains verdict)
    7. Graph Update (records the chain)
    8. Verification History (persistent record)
    """
    
    def __init__(
        self,
        orchestrator: SourceOrchestrator,
        engine: EvidenceEngine,
        llm_provider: Any | None = None,
        db: EvidenceDatabase | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.engine = engine
        self.llm_provider = llm_provider
        self.db = db
        
        # In-memory graph storage
        self.claims: dict[str, Claim] = {}
        self.sources: dict[str, Source] = {}
        self.passages: dict[str, Passage] = {}
        self.evidence: dict[str, Evidence] = {}
        self.contradictions: dict[str, Contradiction] = {}
        self.history: list[VerificationRecord] = []
    
    async def run(self, user_query: str) -> PipelineResult:
        """Execute the complete verification pipeline."""
        verification_id = make_verification_id()
        steps: list[dict[str, Any]] = []
        created_at = datetime.now(timezone.utc).isoformat()
        
        # Step 0: Translate query for external sources
        search_query = get_search_query(user_query)
        is_translated = search_query != extract_claim(user_query)
        
        # Step 1: Claim Extraction
        extracted_claim = extract_claim(user_query)
        steps.append({"name": "claim_extraction", "status": "done", "data": {"claim": extracted_claim}})
        
        # Step 2: Source Discovery (21 sources in parallel — 20 external + archive)
        archive, external, health_orgs = await discover_sources(
            search_query, self.orchestrator,
        )
        steps.append({"name": "source_discovery", "status": "done", "data": {
            "archive": len(archive),
            "external": len(external),
            "health_orgs": len(health_orgs),
            "total": len(archive) + len(external) + len(health_orgs),
        }})
        
        # Step 3: Evidence Engine (hakem)
        engine_result = run_engine(self.engine, extracted_claim, archive, external, health_orgs)
        steps.append({"name": "evidence_engine", "status": "done", "data": {
            "verdict": engine_result["verdict"],
            "confidence": engine_result["confidence"],
            "rating": engine_result["rating_value"],
            "total_evidence": len(engine_result["evidence_items"]),
        }})
        
        # Step 4: Contradiction Detection
        claim_id = make_claim_id(extracted_claim)
        contradictions = detect_contradictions(
            claim_id,
            list(self.sources.values()),
            engine_result["matches"],
        )
        steps.append({"name": "contradiction_detection", "status": "done", "data": {
            "contradictions_found": len(contradictions),
        }})
        
        # Step 5: LLM Interpreter (yorumcu)
        supporting = engine_result.get("supporting_sources", [])
        contradicting = engine_result.get("contradicting_sources", [])
        
        cited_response = await interpret_with_llm(
            extracted_claim,
            engine_result["verdict"],
            engine_result["confidence"],
            engine_result["matches"],
            contradictions,
            supporting,
            contradicting,
            llm_provider=self.llm_provider,
        )
        steps.append({"name": "llm_interpreter", "status": "done", "data": {"response_length": len(cited_response)}})
        
        # Step 6: Graph Update
        graph_result = update_graph(
            extracted_claim,
            engine_result["verdict"],
            engine_result["confidence"],
            engine_result["rating_value"],
            engine_result["matches"],
            supporting,
            contradicting,
            contradictions,
            claims=self.claims,
            sources=self.sources,
            passages=self.passages,
            evidence=self.evidence,
        )
        steps.append({"name": "graph_update", "status": "done", "data": {"claim_id": graph_result["claim"].id}})
        
        # Step 7: Passage Verification
        passage_verifications = await verify_passages(
            graph_result["passages"],
            self.sources,
        )
        steps.append({"name": "passage_verification", "status": "done", "data": {
            "verified": sum(1 for v in passage_verifications if v.get("verified")),
            "total": len(passage_verifications),
        }})
        
        # Step 8: Save verification record
        record = VerificationRecord(
            id=verification_id,
            query=user_query,
            claim_text=extracted_claim,
            verdict=engine_result["verdict"],
            confidence=engine_result["confidence"],
            rating_value=engine_result["rating_value"],
            sources_count=len(archive) + len(external) + len(health_orgs),
            passages_count=len(graph_result["passages"]),
            contradictions_count=len(contradictions),
            created_at=created_at,
            steps=steps,
            cited_response=cited_response,
        )
        self.history.append(record)
        
        # Step 9: Persist to database (if configured)
        if self.db is not None:
            self._save_to_database(
                graph_result["claim"],
                graph_result["sources"],
                graph_result["passages"],
                graph_result["evidence"],
                contradictions,
                record,
            )
        
        return PipelineResult(
            verification_id=verification_id,
            query=user_query,
            extracted_claim=extracted_claim,
            archive_results=archive,
            external_results=external,
            health_org_results=health_orgs,
            passage_verifications=passage_verifications,
            contradictions=[c.to_dict() for c in contradictions],
            verdict=engine_result["verdict"],
            verdict_confidence=engine_result["confidence"],
            rating_value=engine_result["rating_value"],
            supporting_sources=supporting,
            contradicting_sources=contradicting,
            cited_response=cited_response,
            steps=steps,
            graph_claim_id=graph_result["claim"].id,
            created_at=created_at,
        )
    
    def _save_to_database(
        self,
        claim: Claim,
        sources: list[Source],
        passages: list[Passage],
        evidence: Evidence,
        contradictions: list[Contradiction],
        record: VerificationRecord,
    ) -> None:
        """Persist all artifacts to the SQLite database."""
        try:
            self.db.save_claim(claim)
            for source in sources:
                self.db.save_source(source)
            for passage in passages:
                self.db.save_passage(passage)
            self.db.save_evidence(evidence)
            for contradiction in contradictions:
                self.db.save_contradiction(contradiction)
            self.db.save_verification_record(record)
        except Exception as e:
            logger.warning(f"Failed to save to database: {e}")
