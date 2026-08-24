"""FastAPI application — ChatGPT/Claude-style Evidence Verification API v2.

Features:
- Streaming (SSE) — Real-time response streaming
- Authentication — API key management
- Rate limiting — Per-user limits
- Conversation history — Past verifications
- Web UI — Chat interface
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..core.database import EvidenceDatabase
from ..core.infrastructure import RateLimiter
from ..engine import DeterministicEngine
from ..pipeline import EvidencePipeline, PipelineResult
from ..sources import (
    PubMedAgent,
    CrossrefAgent,
    ArchiveAgent,
    WHOAgent,
    CDCAgent,
    ECDCAgent,
    CochraneAgent,
    ClinicalTrialsAgent,
    FDAAgent,
    EMAAgent,
    GoogleScholarAgent,
    NEJMAgent,
    JAMAAgent,
    LancetAgent,
    BMJAgent,
    NICEAgent,
    AHAAgent,
    ESCAgent,
    TUSEBAgent,
    EuropePMCAgent,
    OpenAlexAgent,
    SourceOrchestrator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    stream: bool = False
    session_id: str | None = Field(default=None, max_length=64)


class VerifyResponse(BaseModel):
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


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    sources: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    query: str
    results: list[dict]
    total_results: int
    agents_succeeded: int
    agents_failed: int
    agent_stats: list[dict]


class StatsResponse(BaseModel):
    claims: int
    sources: int
    passages: int
    evidence: int
    contradictions: int
    verifications: int
    agents: list[dict]
    total_agents: int


class HistoryResponse(BaseModel):
    records: list[dict]
    total: int


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: str | None = None
    verification_id: str | None = None


class ChatSession(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    created_at: str
    updated_at: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=100)


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: str
    api_key: str
    created_at: str
    rate_limit: int


# ---------------------------------------------------------------------------
# Simple User Store (in-memory for demo, should be DB in production)
# ---------------------------------------------------------------------------

class UserStore:
    """Simple in-memory user store."""
    
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.api_keys: dict[str, str] = {}  # api_key -> user_id
    
    def create_user(self, username: str, email: str) -> dict[str, Any]:
        user_id = f"user::{secrets.token_hex(8)}"
        api_key = f"ak_{secrets.token_hex(24)}"
        user = {
            "user_id": user_id,
            "username": username,
            "email": email,
            "api_key": api_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "rate_limit": 100,  # requests per hour
        }
        self.users[user_id] = user
        self.api_keys[api_key] = user_id
        return user
    
    def get_user_by_api_key(self, api_key: str) -> dict[str, Any] | None:
        user_id = self.api_keys.get(api_key)
        if user_id:
            return self.users.get(user_id)
        return None
    
    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.users.get(user_id)


# ---------------------------------------------------------------------------
# Chat Session Store
# ---------------------------------------------------------------------------

class ChatStore:
    """In-memory chat session store."""
    
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
    
    def create_session(self) -> ChatSession:
        session_id = f"sess::{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc).isoformat()
        session = ChatSession(
            session_id=session_id,
            messages=[],
            created_at=now,
            updated_at=now,
        )
        self.sessions[session_id] = session
        return session
    
    def get_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)
    
    def add_message(self, session_id: str, message: ChatMessage) -> None:
        session = self.sessions.get(session_id)
        if session:
            session.messages.append(message)
            session.updated_at = datetime.now(timezone.utc).isoformat()
    
    def get_history(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        session = self.sessions.get(session_id)
        if session:
            return session.messages[-limit:]
        return []
    
    def list_sessions(self, limit: int = 20) -> list[ChatSession]:
        sessions = list(self.sessions.values())
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    retriever: Any | None = None,
    llm_provider: Any | None = None,
    db_path: str | None = None,
    auto_index: bool | None = None,
) -> FastAPI:
    """Create the FastAPI application.
    
    Features:
    - Streaming (SSE) for real-time responses
    - Authentication with API keys
    - Rate limiting per user
    - Conversation history
    - Web UI (Chat interface)
    """
    app = FastAPI(title="Arı Kaynak Evidence API v2", version="2.0.0")
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Initialize stores
    user_store = UserStore()
    chat_store = ChatStore()
    
    # Initialize rate limiter
    rate_limiter = RateLimiter(max_requests=100, window_seconds=3600)
    
    # Otomatik RAG kurulumu: retriever verilmediyse yerel arsivi endeksle.
    # Bot boylece kendi dogrulanmis makale arsivini gorebilir.
    # EVIDENCE_AUTO_INDEX=0 ile kapatilabilir (testler/hizli baslangic).
    _auto_env = os.getenv("EVIDENCE_AUTO_INDEX", "1").strip().lower() in {"1", "true", "yes", "on"}
    if retriever is None and (auto_index if auto_index is not None else _auto_env):
        try:
            from ...config import Settings
            from ...rag.parser import parse_all_articles
            from ...rag.retriever import ArticleRetriever
            from ...rag.store import ArticleVectorStore

            _settings = Settings()
            _articles_dir = Path(_settings.rag_articles_dir)
            _tr_dir = Path(_settings.rag_tr_dir)
            if _articles_dir.exists():
                if _settings.rag_backend == "chroma":
                    from ...rag.chroma_store import ChromaArticleVectorStore

                    _store = ChromaArticleVectorStore(_settings.rag_chroma_persist_directory)
                else:
                    _store = ArticleVectorStore(_settings.rag_persist_directory)
                retriever = ArticleRetriever(_store)
                _chunks = parse_all_articles(
                    _articles_dir,
                    _tr_dir if _tr_dir.exists() else None,
                )
                if _chunks:
                    for _aid in {c.article_id for c in _chunks}:
                        _store.delete_article(_aid)
                    _upserted = _store.upsert_chunks(_chunks)
                    logger.info(
                        f"RAG auto-index: {_upserted} chunks / "
                        f"{len({c.article_id for c in _chunks})} articles"
                    )
        except Exception as e:
            logger.warning(f"RAG auto-index atlandi: {e}")
            retriever = None

    # Initialize all agents (20 harici + arsiv = 21 kaynak ajanı)
    agents = [
        PubMedAgent(),
        CrossrefAgent(),
        WHOAgent(),
        CDCAgent(),
        ECDCAgent(),
        CochraneAgent(),
        ClinicalTrialsAgent(),
        FDAAgent(),
        EMAAgent(),
        GoogleScholarAgent(),
        NEJMAgent(),
        JAMAAgent(),
        LancetAgent(),
        BMJAgent(),
        NICEAgent(),
        AHAAgent(),
        ESCAgent(),
        TUSEBAgent(),
        EuropePMCAgent(),
        OpenAlexAgent(),
    ]
    if retriever:
        agents.insert(2, ArchiveAgent(retriever))
    
    # Initialize database (if path provided)
    db = EvidenceDatabase(db_path) if db_path else None
    
    # Initialize components
    orchestrator = SourceOrchestrator(agents)
    engine = DeterministicEngine()
    pipeline = EvidencePipeline(orchestrator, engine, llm_provider, db)
    
    app.state.orchestrator = orchestrator
    app.state.engine = engine
    app.state.pipeline = pipeline
    app.state.retriever = retriever
    app.state.db = db
    app.state.user_store = user_store
    app.state.chat_store = chat_store
    app.state.rate_limiter = rate_limiter
    
    # -----------------------------------------------------------------------
    # Auth dependency
    # -----------------------------------------------------------------------
    
    async def get_current_user(request: Request) -> dict[str, Any] | None:
        """Extract API key from header and return user."""
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return user_store.get_user_by_api_key(api_key)
        return None
    
    async def require_auth(request: Request) -> dict[str, Any]:
        """Require authentication."""
        user = await get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return user
    
    async def check_rate_limit(user: dict[str, Any]) -> None:
        """Check rate limit for user."""
        user_id = user["user_id"]
        if not await rate_limiter.acquire(user_id):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # -----------------------------------------------------------------------
    # Endpoints
    # -----------------------------------------------------------------------
    
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "2.0.0", "agents": len(agents)}
    
    # --- Auth endpoints ---
    
    @app.post("/v1/auth/register", response_model=UserResponse)
    async def register(request: CreateUserRequest):
        """Register a new user and get API key."""
        user = user_store.create_user(request.username, request.email)
        return UserResponse(**user)
    
    @app.get("/v1/auth/me")
    async def get_me(user: dict = Depends(require_auth)):
        """Get current user info."""
        return {k: v for k, v in user.items() if k != "api_key"}
    
    # --- Verify endpoint with streaming ---
    
    @app.post("/v1/verify")
    async def verify(request: VerifyRequest, request_obj: Request):
        """Full verification pipeline with optional streaming."""
        # Optional auth (for rate limiting)
        user = await get_current_user(request_obj)
        if user:
            await check_rate_limit(user)
        
        if request.stream:
            return StreamingResponse(
                stream_verification(request.query, pipeline, user),
                media_type="text/event-stream",
            )
        
        result = await pipeline.run(request.query)
        return VerifyResponse(**result.to_dict())
    
    async def stream_verification(query: str, pipeline: EvidencePipeline, user: dict | None):
        """Stream verification steps via SSE."""
        yield f"data: {json.dumps({'type': 'start', 'query': query})}\n\n"
        
        # Step 1: Claim extraction
        yield f"data: {json.dumps({'type': 'step', 'name': 'claim_extraction', 'status': 'running'})}\n\n"
        
        # Step 2: Source discovery
        yield f"data: {json.dumps({'type': 'step', 'name': 'source_discovery', 'status': 'running'})}\n\n"
        
        # Step 3: Evidence engine
        yield f"data: {json.dumps({'type': 'step', 'name': 'evidence_engine', 'status': 'running'})}\n\n"
        
        # Step 4: Contradictions
        yield f"data: {json.dumps({'type': 'step', 'name': 'contradiction_detection', 'status': 'running'})}\n\n"
        
        # Step 5: Interpreter
        yield f"data: {json.dumps({'type': 'step', 'name': 'llm_interpreter', 'status': 'running'})}\n\n"
        
        # Step 6: Graph update
        yield f"data: {json.dumps({'type': 'step', 'name': 'graph_update', 'status': 'running'})}\n\n"
        
        # Run full pipeline
        result = await pipeline.run(query)
        
        # Stream the response text
        response_text = result.cited_response
        chunk_size = 20  # characters per chunk
        
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            await asyncio.sleep(0.02)  # Simulate streaming delay
        
        # Final result
        yield f"data: {json.dumps({'type': 'done', 'result': result.to_dict()})}\n\n"
    
    # --- Chat endpoints ---
    
    @app.post("/v1/chat")
    async def chat_verify(request: VerifyRequest, request_obj: Request):
        """Chat-style verification with session history."""
        user = await get_current_user(request_obj)
        if user:
            await check_rate_limit(user)
        
        # Get or create session
        session_id = request_obj.headers.get("X-Session-ID")
        if not session_id:
            session = chat_store.create_session()
            session_id = session.session_id
        
        # Add user message
        user_msg = ChatMessage(
            role="user",
            content=request.query,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        chat_store.add_message(session_id, user_msg)
        
        # Run verification
        result = await pipeline.run(request.query)
        
        # Add assistant message
        assistant_msg = ChatMessage(
            role="assistant",
            content=result.cited_response,
            timestamp=datetime.now(timezone.utc).isoformat(),
            verification_id=result.verification_id,
        )
        chat_store.add_message(session_id, assistant_msg)
        
        return {
            "session_id": session_id,
            "message": assistant_msg.model_dump(),
            "verification_id": result.verification_id,
        }
    
    @app.get("/v1/chat/history/{session_id}")
    async def chat_history(session_id: str, limit: int = 50):
        """Get chat history for a session."""
        messages = chat_store.get_history(session_id, limit)
        return {"session_id": session_id, "messages": [m.model_dump() for m in messages]}
    
    @app.get("/v1/chat/sessions")
    async def list_sessions(limit: int = 20):
        """List recent chat sessions."""
        sessions = chat_store.list_sessions(limit)
        return {"sessions": [s.model_dump() for s in sessions]}
    
    # --- Search endpoints ---
    
    @app.post("/v1/search", response_model=SearchResponse)
    async def search(request: SearchRequest):
        """Search specific sources without running the full pipeline."""
        result = await orchestrator.search(
            request.query,
            limit_per_agent=request.limit,
            sources=request.sources,
        )
        return SearchResponse(**result)
    
    # --- Stats endpoints ---
    
    @app.get("/v1/stats", response_model=StatsResponse)
    async def stats():
        """Get statistics about the evidence graph."""
        return StatsResponse(
            claims=len(pipeline.claims),
            sources=len(pipeline.sources),
            passages=len(pipeline.passages),
            evidence=len(pipeline.evidence),
            contradictions=len(pipeline.contradictions),
            verifications=len(pipeline.history),
            agents=orchestrator.list_agents(),
            total_agents=len(agents),
        )
    
    # --- History endpoints ---
    
    @app.get("/v1/history", response_model=HistoryResponse)
    async def history(limit: int = 100):
        """Get verification history."""
        records = [r.to_dict() for r in pipeline.history[-limit:]]
        return HistoryResponse(records=records, total=len(pipeline.history))
    
    @app.get("/v1/agents")
    async def list_agents():
        """List all available source agents."""
        return {
            "agents": orchestrator.list_agents(),
            "total_agents": len(agents),
        }
    
    # --- Graph endpoints ---
    
    @app.get("/v1/claims/{claim_id}")
    async def get_claim(claim_id: str):
        """Get a specific claim from the graph."""
        claim = pipeline.claims.get(claim_id)
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found")
        return claim.to_dict()
    
    @app.get("/v1/evidence/{claim_id}")
    async def get_evidence(claim_id: str):
        """Get evidence for a specific claim."""
        evidence_list = [
            ev.to_dict() for ev in pipeline.evidence.values()
            if ev.claim_id == claim_id
        ]
        return {"claim_id": claim_id, "evidence": evidence_list}
    
    @app.get("/v1/contradictions")
    async def get_contradictions():
        """Get all detected contradictions."""
        return {
            "contradictions": [c.to_dict() for c in pipeline.contradictions.values()],
            "total": len(pipeline.contradictions),
        }
    
    @app.get("/v1/verification/{verification_id}")
    async def get_verification(verification_id: str):
        """Get a specific verification record."""
        for record in pipeline.history:
            if record.id == verification_id:
                return record.to_dict()
        raise HTTPException(status_code=404, detail="Verification not found")
    
    # --- Database endpoints ---
    
    @app.get("/v1/db/stats")
    async def db_stats():
        """Get database statistics (requires database to be configured)."""
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")
        return db.get_stats()
    
    @app.get("/v1/db/history")
    async def db_history(limit: int = 100):
        """Get verification history from database (requires database)."""
        if not db:
            raise HTTPException(status_code=404, detail="Database not configured")
        records = db.get_verification_history(limit)
        return {"records": [r.to_dict() for r in records], "total": len(records)}
    
    # --- Conversational Investigator ---
    
    from ...chat import ConversationManager
    
    # In-memory conversation managers per session
    conversation_managers: dict[str, ConversationManager] = {}
    MAX_SESSIONS = 64

    def _get_manager(session_id: str) -> ConversationManager:
        if session_id not in conversation_managers:
            while len(conversation_managers) >= MAX_SESSIONS:
                conversation_managers.pop(next(iter(conversation_managers)))
            conversation_managers[session_id] = ConversationManager(
                orchestrator=orchestrator,
                llm_provider=llm_provider,
                db=db,
            )
        return conversation_managers[session_id]

    @app.post("/v1/investigator/chat")
    async def investigator_chat(request: VerifyRequest):
        """Conversational Investigator endpoint — interaktif kanit arastirma."""
        manager = _get_manager(request.session_id or "default")
        response = await manager.handle_message(request.query)
        
        return {
            "response": response.text,
            "intent": response.intent_type,
            "confidence": response.confidence,
            "sources_cited": response.sources_cited,
            "follow_up_suggestions": response.follow_up_suggestions,
            "metadata": response.metadata,
        }
    
    @app.post("/v1/investigator/reset")
    async def investigator_reset(session_id: str = "default"):
        """Conversation session'i sifirla."""
        if session_id in conversation_managers:
            conversation_managers[session_id].reset()
        return {"status": "ok", "message": "Session sifirlandi"}
    
    @app.get("/v1/investigator/stats")
    async def investigator_stats(session_id: str = "default"):
        """Conversation istatistikleri."""
        if session_id in conversation_managers:
            return conversation_managers[session_id].get_stats()
        return {"turn_count": 0, "total_sources_found": 0}
    
    @app.post("/v1/investigator/chat/stream")
    async def investigator_chat_stream(request: VerifyRequest):
        """Conversational Investigator — adim adim SSE akisi."""
        manager = _get_manager(request.session_id or "default")
        
        async def event(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        
        async def generator():
            started = time.time()
            yield await event({"type": "start", "query": request.query})
            
            steps = [
                ("intent", "İddia çözümleniyor"),
                ("archive", "Arşiv makaleleri taranıyor"),
                ("external", "Harici kaynaklar kontrol ediliyor"),
                ("contradiction", "Çelişkiler inceleniyor"),
                ("synthesis", "Hüküm yazılıyor"),
            ]
            
            task = asyncio.create_task(manager.handle_message(request.query))
            for name, label in steps:
                if task.done():
                    break
                yield await event({"type": "step", "name": name, "label": label})
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.45)
                except asyncio.TimeoutError:
                    continue
            
            response = await task
            yield await event({"type": "steps_done"})
            
            text = response.text
            chunk_size = 14
            for i in range(0, len(text), chunk_size):
                yield await event({"type": "chunk", "content": text[i:i + chunk_size]})
                await asyncio.sleep(0.015)
            
            yield await event({
                "type": "done",
                "intent": response.intent_type,
                "confidence": response.confidence,
                "sources_cited": response.sources_cited,
                "follow_up_suggestions": response.follow_up_suggestions,
                "metadata": response.metadata,
                "duration_ms": int((time.time() - started) * 1000),
            })
        
        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    
    # --- Web UI ---
    
    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        """Serve the chat web UI."""
        return get_chat_ui_html()
    
    return app


# ---------------------------------------------------------------------------
# Web UI HTML
# ---------------------------------------------------------------------------

def get_chat_ui_html() -> str:
    """Return the chat web UI (kagit/murekkep tema, SSE akisli)."""
    return r"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arı Kaynak — Kanıt Soruşturucusu</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root{
            --paper:#d9dccb; --card:#e3e6d4; --deep:#c7cbb6;
            --ink:#1c261f; --ink-soft:#4a564a; --faint:#7c8579;
            --ok:#3f6b4f; --flag:#a23b2e; --amber:#a8763a;
            --line:rgba(28,38,31,.16); --line-strong:rgba(28,38,31,.34);
            --serif:'Fraunces',Georgia,serif;
            --sans:'Inter',-apple-system,sans-serif;
            --mono:'IBM Plex Mono',monospace;
        }
        *{ box-sizing:border-box; margin:0; padding:0; }
        html{ height:100%; }
        body{
            height:100vh; display:flex; flex-direction:column;
            background:var(--paper); color:var(--ink);
            font-family:var(--sans); font-size:16px; line-height:1.6;
            -webkit-font-smoothing:antialiased;
        }
        body::before{
            content:""; position:fixed; inset:0; pointer-events:none; z-index:999;
            opacity:.035;
            background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
        }
        ::selection{ background:var(--deep); }
        button{ font-family:var(--mono); cursor:pointer; }
        :focus-visible{ outline:2px solid var(--ok); outline-offset:2px; }

        /* ---------- Header ---------- */
        .header{
            background:var(--paper);
            border-bottom:1px solid var(--line-strong);
            padding:14px 28px;
            display:flex; align-items:center; gap:14px;
        }
        .mark-box{
            width:36px; height:36px; border:2px solid var(--ink);
            display:flex; align-items:center; justify-content:center;
            font-family:var(--serif); font-weight:700; font-size:19px; flex-shrink:0;
            background:var(--card);
        }
        .mark-text{ display:flex; flex-direction:column; }
        .mark-text b{ font-family:var(--mono); font-size:15px; letter-spacing:.16em; font-weight:500; }
        .mark-text span{ font-family:var(--mono); font-size:11px; letter-spacing:.08em; color:var(--faint); }
        .header-right{ margin-left:auto; display:flex; align-items:center; gap:16px; }
        #stats{ font-family:var(--mono); font-size:12px; color:var(--ink-soft); letter-spacing:.04em; }
        .reset-btn{
            background:transparent; border:1px solid var(--line-strong);
            color:var(--ink-soft); padding:7px 14px; font-size:11px;
            text-transform:uppercase; letter-spacing:.12em;
            transition:all .15s;
        }
        .reset-btn:hover{ background:var(--ink); color:var(--paper); border-color:var(--ink); }

        /* ---------- Chat area ---------- */
        .chat-container{
            flex:1; overflow-y:auto; padding:32px 24px 16px;
            scrollbar-width:thin; scrollbar-color:var(--line-strong) transparent;
        }
        .chat-inner{ max-width:860px; margin:0 auto; display:flex; flex-direction:column; gap:20px; }

        /* Welcome */
        .welcome{ max-width:640px; margin:auto; text-align:center; padding:40px 0; }
        .welcome .tag{ font-family:var(--mono); font-size:11px; letter-spacing:.22em; color:var(--amber); text-transform:uppercase; margin-bottom:14px; }
        .welcome h2{ font-family:var(--serif); font-size:34px; line-height:1.25; margin-bottom:14px; }
        .welcome p{ color:var(--ink-soft); font-size:15px; }
        .examples{ margin-top:34px; display:grid; grid-template-columns:1fr 1fr; gap:12px; text-align:left; }
        .example{
            background:var(--card); border:1px solid var(--line-strong);
            padding:14px 16px 12px; cursor:pointer; transition:all .15s;
            font-family:var(--sans); font-size:14px; line-height:1.5; color:var(--ink);
            position:relative;
        }
        .example::before{
            content:attr(data-no); display:block; font-family:var(--mono);
            font-size:10px; letter-spacing:.18em; color:var(--faint); margin-bottom:6px;
        }
        .example:hover{ border-color:var(--ink); transform:translateY(-2px); box-shadow:3px 4px 0 rgba(28,38,31,.12); }

        /* Messages */
        .message{ animation:fadeUp .3s ease; }
        @keyframes fadeUp{ from{ opacity:0; transform:translateY(8px);} to{ opacity:1; transform:translateY(0);} }
        .message.user{
            align-self:flex-end; max-width:78%;
            background:var(--card); border:1px solid var(--line-strong);
            padding:13px 18px; position:relative;
        }
        .message.user .role{
            font-family:var(--mono); font-size:10px; letter-spacing:.2em;
            color:var(--faint); text-transform:uppercase; margin-bottom:4px;
        }
        .message.assistant{
            align-self:flex-start; width:100%;
            background:var(--card); border:1px solid var(--line-strong);
        }
        .file-head{
            display:flex; align-items:center; gap:12px;
            padding:10px 18px; border-bottom:1px dashed var(--line-strong);
            background:var(--paper);
        }
        .file-head .role{ font-family:var(--mono); font-size:11px; letter-spacing:.18em; color:var(--ink-soft); text-transform:uppercase; }
        .stamp{
            margin-left:auto; font-family:var(--mono); font-size:10px; letter-spacing:.14em;
            text-transform:uppercase; padding:3px 10px; border:2px solid currentColor;
            transform:rotate(-2deg); opacity:0; transition:opacity .4s;
        }
        .stamp.show{ opacity:.85; }
        .stamp.v-ok{ color:var(--ok); } .stamp.v-flag{ color:var(--flag); } .stamp.v-amber{ color:var(--amber); } .stamp.v-faint{ color:var(--faint); }
        .msg-body{ padding:16px 18px 14px; }

        /* Steps timeline */
        .steps{ display:flex; flex-direction:column; gap:8px; margin-bottom:4px; }
        .step{ display:flex; align-items:center; gap:10px; font-family:var(--mono); font-size:12.5px; color:var(--ink-soft); animation:fadeUp .25s ease; }
        .step .icon{
            width:15px; height:15px; border-radius:50%; flex-shrink:0;
            border:2px solid var(--line-strong); position:relative;
        }
        .step.running .icon{ border-color:var(--amber); border-top-color:transparent; animation:spin .7s linear infinite; }
        @keyframes spin{ to{ transform:rotate(360deg);} }
        .step.done .icon{ border-color:var(--ok); background:transparent; }
        .step.done .icon::after{
            content:"✓"; position:absolute; inset:-5px 0 0 -1px;
            font-size:12px; color:var(--ok);
        }
        .step.done{ color:var(--faint); }
        .step.running{ color:var(--ink); }

        /* Content */
        .content{
            margin-top:12px; white-space:pre-wrap; font-size:15.5px; line-height:1.65;
        }
        .content strong{ font-weight:600; }
        .content.streaming::after{
            content:"▍"; color:var(--amber); animation:blink 1s steps(2) infinite;
        }
        @keyframes blink{ 50%{ opacity:0; } }
        .content.error{ color:var(--flag); font-family:var(--mono); font-size:13.5px; }

        /* Meta footer */
        .meta{
            margin-top:14px; padding-top:12px; border-top:1px dashed var(--line-strong);
            display:flex; align-items:center; flex-wrap:wrap; gap:10px 18px;
            font-family:var(--mono); font-size:11.5px; color:var(--faint); letter-spacing:.04em;
        }
        .copy-btn{
            margin-left:auto; background:transparent; border:1px solid var(--line-strong);
            color:var(--ink-soft); font-size:10px; text-transform:uppercase;
            letter-spacing:.12em; padding:4px 10px; transition:all .15s;
        }
        .copy-btn:hover{ background:var(--ink); color:var(--paper); border-color:var(--ink); }

        /* Suggestions */
        .suggest-row{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .chip{
            background:var(--paper); border:1px solid var(--line-strong);
            color:var(--ink-soft); font-size:12px; padding:6px 13px;
            transition:all .15s; text-align:left;
        }
        .chip::before{ content:"+ "; color:var(--amber); }
        .chip:hover{ border-color:var(--ink); color:var(--ink); background:var(--card); }

        /* Input bar */
        .input-container{
            background:var(--paper); border-top:1px solid var(--line-strong); padding:18px 24px 22px;
        }
        .input-wrapper{ max-width:860px; margin:0 auto; display:flex; gap:12px; align-items:flex-end; }
        .input-wrapper textarea{
            flex:1; background:var(--card); border:1px solid var(--line-strong);
            padding:13px 16px; color:var(--ink); font-family:var(--sans);
            font-size:15px; resize:none; min-height:48px; max-height:180px; line-height:1.5;
        }
        .input-wrapper textarea:focus{ outline:none; border-color:var(--ink); box-shadow:2px 3px 0 rgba(28,38,31,.12); }
        .input-wrapper textarea::placeholder{ color:var(--faint); }
        .send-btn{
            background:var(--ink); color:var(--paper); border:1px solid var(--ink);
            padding:13px 26px; font-size:12px; text-transform:uppercase; letter-spacing:.14em;
            transition:all .15s; height:48px;
        }
        .send-btn:hover:not(:disabled){ background:var(--ok); border-color:var(--ok); }
        .send-btn:disabled{ background:var(--deep); border-color:var(--line-strong); color:var(--faint); cursor:not-allowed; }

        @media (max-width:640px){
            .mark-text span, #stats{ display:none; }
            .examples{ grid-template-columns:1fr; }
            .message.user{ max-width:92%; }
            .header{ padding:12px 16px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="mark-box">A</div>
        <div class="mark-text"><b>ARI KAYNAK</b><span>Kanıt Soruşturucusu</span></div>
        <div class="header-right">
            <span id="stats">0 sorgu · 0 kaynak</span>
            <button class="reset-btn" id="resetBtn">Dosyayı Kapat</button>
        </div>
    </div>

    <div class="chat-container" id="chatContainer">
        <div class="chat-inner" id="chatInner">
            <div class="welcome" id="welcome">
                <div class="tag">— Dosya Numarası Bekleniyor —</div>
                <h2>İddia sor,<br>kanıtlarıyla cevap al.</h2>
                <p>Sorunuzu arşivdeki makalelerden ve harici tıbbi kaynaklardan<br>sıra sıra soruşturur, hükümü damga basarak veririm.</p>
                <div class="examples">
                    <button class="example" data-no="DOSYA 01">Kahve kolesterolü yükseltir mi?</button>
                    <button class="example" data-no="DOSYA 02">Kreatin takviyesi böbreğe zarar verir mi?</button>
                    <button class="example" data-no="DOSYA 03">Günlük aspirin kalp krizinden korur mu?</button>
                    <button class="example" data-no="DOSYA 04">Yapay tatillerde şeker yerine bal daha mı sağlıklı?</button>
                </div>
            </div>
        </div>
    </div>

    <div class="input-container">
        <div class="input-wrapper">
            <textarea
                id="userInput"
                placeholder="İddianızı yazın...  (Enter ile gönder)"
                rows="1"
            ></textarea>
            <button class="send-btn" id="sendBtn">Soruştur</button>
        </div>
    </div>

    <script>
        let isProcessing = false;
        let turnCount = 0;
        let sessionId = null;
        try {
            sessionId = localStorage.getItem('ariSession');
            if (!sessionId) {
                sessionId = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2));
                localStorage.setItem('ariSession', sessionId);
            }
        } catch (e) { sessionId = 'default'; }

        const container = document.getElementById('chatContainer');
        const inner = document.getElementById('chatInner');
        const input = document.getElementById('userInput');
        const sendBtn = document.getElementById('sendBtn');

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function renderMarkdown(text) {
            let html = escapeHtml(text);
            html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) =>
                `<a href="${u}" target="_blank" rel="noopener" style="color:var(--ok);font-weight:600;text-decoration:underline;text-underline-offset:2px;">${t}</a>`);
            html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/^(?:&gt;|>) (.+)$/gm, (_, q) =>
                `<span style="display:block;border-left:3px solid var(--amber);padding-left:10px;color:var(--ink-soft);font-size:.92em;margin:5px 0;">${q}</span>`);
            return html;
        }

        function nearBottom() {
            return container.scrollHeight - container.scrollTop - container.clientHeight < 140;
        }

        function scrollDown() { container.scrollTop = container.scrollHeight; }

        function autoResize(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 180) + 'px';
        }

        input.addEventListener('input', () => autoResize(input));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        sendBtn.addEventListener('click', sendMessage);

        document.querySelectorAll('.example').forEach(ex => {
            ex.addEventListener('click', () => {
                input.value = ex.textContent.trim();
                autoResize(input);
                input.focus();
            });
        });

        document.getElementById('resetBtn').addEventListener('click', async () => {
            if (isProcessing) return;
            try { await fetch(`/v1/investigator/reset?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' }); } catch (e) {}
            try {
                sessionId = (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2));
                localStorage.setItem('ariSession', sessionId);
            } catch (e) { sessionId = 'default'; }
            turnCount = 0;
            updateStats({ turn_count: 0, total_sources_found: 0 });
            [...inner.querySelectorAll('.message')].forEach(m => m.remove());
            document.getElementById('welcome').style.display = '';
            input.focus();
        });

        function updateStats(s) {
            document.getElementById('stats').textContent =
                `${s.turn_count || 0} sorgu · ${s.total_sources_found || 0} kaynak`;
        }

        function addUserMsg(text) {
            const welcome = document.getElementById('welcome');
            if (welcome) welcome.style.display = 'none';
            const div = document.createElement('div');
            div.className = 'message user';
            div.innerHTML = `<div class="role">Sen</div><div>${escapeHtml(text)}</div>`;
            inner.appendChild(div);
            scrollDown();
        }

        function addAssistantShell() {
            turnCount++;
            const div = document.createElement('div');
            div.className = 'message assistant';
            div.innerHTML = `
                <div class="file-head">
                    <span class="role">Soruşturma Dosyası №${String(turnCount).padStart(3, '0')}</span>
                    <span class="stamp" id="stamp"></span>
                </div>
                <div class="msg-body">
                    <div class="steps" id="steps"></div>
                    <div class="content" id="content"></div>
                    <div class="meta" id="meta" style="display:none">
                        <span id="metaInfo"></span>
                        <button class="copy-btn" id="copyBtn">Kopyala</button>
                    </div>
                    <div class="suggest-row" id="chips"></div>
                </div>`;
            inner.appendChild(div);
            scrollDown();
            return div;
        }

        function addStepRow(stepsEl, label) {
            const row = document.createElement('div');
            row.className = 'step running';
            row.innerHTML = `<span class="icon"></span><span>${escapeHtml(label)}</span>`;
            stepsEl.appendChild(row);
            scrollDown();
            return row;
        }

        function detectVerdict(text) {
            const m = text.match(/h[uü]k[uü]m:?\s*\**\s*([a-z_ ]+)/i);
            const v = m ? m[1].toLowerCase() : '';
            if (v.includes('unsupported') || v.includes('misrepresented')) return ['v-flag', 'Desteklenmiyor'];
            if (v.includes('partly')) return ['v-amber', 'Kısmen Destekli'];
            if (v.includes('mostly')) return ['v-ok', 'Büyük Ölçüde Destekli'];
            if (v.includes('supported')) return ['v-ok', 'Destekleniyor'];
            if (v.includes('unverified')) return ['v-faint', 'Doğrulanamadı'];
            return null;
        }

        function finalize(div, data, fullText) {
            const content = div.querySelector('#content');
            content.classList.remove('streaming');
            content.innerHTML = renderMarkdown(fullText);

            const stamp = div.querySelector('#stamp');
            const verdict = detectVerdict(fullText);
            if (verdict) {
                stamp.textContent = verdict[1];
                stamp.className = `stamp show ${verdict[0]}`;
            }

            const meta = div.querySelector('#meta');
            meta.style.display = 'flex';
            div.querySelector('#metaInfo').textContent =
                `${data.sources_cited ?? '–'} kaynak · güvenirlik %${Math.round((data.confidence ?? 0) * 100)} · ${(data.duration_ms / 1000).toFixed(1)} sn`;

            div.querySelector('#copyBtn').addEventListener('click', () => {
                navigator.clipboard.writeText(fullText).then(() => {
                    const btn = div.querySelector('#copyBtn');
                    btn.textContent = 'Kopyalandı ✓';
                    setTimeout(() => btn.textContent = 'Kopyala', 1600);
                });
            });

            const chips = div.querySelector('#chips');
            (data.follow_up_suggestions || []).slice(0, 3).forEach(s => {
                const chip = document.createElement('button');
                chip.className = 'chip';
                chip.textContent = s;
                chip.addEventListener('click', () => {
                    if (!isProcessing) { input.value = s; sendMessage(); }
                });
                chips.appendChild(chip);
            });
        }

        async function streamResponse(query, div) {
            const stepsEl = div.querySelector('#steps');
            const content = div.querySelector('#content');
            let fullText = '';

            const resp = await fetch('/v1/investigator/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, session_id: sessionId }),
            });

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                const parts = buffer.split('\n\n');
                buffer = parts.pop();

                for (const part of parts) {
                    const line = part.trim();
                    if (!line.startsWith('data:')) continue;
                    const ev = JSON.parse(line.slice(5));

                    if (ev.type === 'step') {
                        addStepRow(stepsEl, ev.label);
                    } else if (ev.type === 'steps_done') {
                        stepsEl.querySelectorAll('.step.running').forEach(r => {
                            r.classList.remove('running'); r.classList.add('done');
                        });
                        content.classList.add('streaming');
                    } else if (ev.type === 'chunk') {
                        fullText += ev.content;
                        content.textContent = fullText;
                        if (nearBottom()) scrollDown();
                    } else if (ev.type === 'done') {
                        finalize(div, ev, fullText);
                    }
                }
            }
        }

        async function fallbackResponse(query, div) {
            const content = div.querySelector('#content');
            const resp = await fetch('/v1/investigator/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, session_id: sessionId }),
            });
            const data = await resp.json();
            div.querySelector('#steps').querySelectorAll('.step.running')
                .forEach(r => { r.classList.remove('running'); r.classList.add('done'); });
            content.classList.add('streaming');
            content.textContent = data.response;
            finalize(div, {
                sources_cited: data.sources_cited,
                confidence: data.confidence,
                follow_up_suggestions: data.follow_up_suggestions,
                duration_ms: 0,
            }, data.response);
        }

        async function sendMessage() {
            const query = input.value.trim();
            if (!query || isProcessing) return;

            isProcessing = true;
            sendBtn.disabled = true;
            sendBtn.textContent = 'Soruşturuluyor…';
            addUserMsg(query);
            input.value = '';
            autoResize(input);

            const div = addAssistantShell();

            try {
                await streamResponse(query, div);
            } catch (err) {
                try {
                    await fallbackResponse(query, div);
                } catch (err2) {
                    const content = div.querySelector('#content');
                    content.classList.add('error');
                    content.textContent = 'Bağlantı hatası: ' + err2.message;
                }
            }

            fetch(`/v1/investigator/stats?session_id=${encodeURIComponent(sessionId)}`).then(r => r.json()).then(updateStats).catch(() => {});

            isProcessing = false;
            sendBtn.disabled = false;
            sendBtn.textContent = 'Soruştur';
            input.focus();
        }

        updateStats({ turn_count: 0, total_sources_found: 0 });
        input.focus();
    </script>
</body>
</html>"""


# Module-level app instance for uvicorn
app = create_app()
