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
import secrets
import time
from datetime import datetime, timezone
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
    SourceOrchestrator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    stream: bool = False


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
    
    # Initialize all agents (19 sources)
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
    """Return the HTML for the chat web UI."""
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arı Kaynak - Fact Checker</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .header {
            background: #1a1a1a;
            padding: 16px 24px;
            border-bottom: 1px solid #333;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .header h1 {
            font-size: 20px;
            color: #fff;
        }
        
        .header .subtitle {
            color: #888;
            font-size: 14px;
        }
        
        .header .status {
            margin-left: auto;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #888;
        }
        
        .header .status .dot {
            width: 8px;
            height: 8px;
            background: #4ade80;
            border-radius: 50%;
        }
        
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        
        .message {
            max-width: 800px;
            width: 100%;
            margin: 0 auto;
            padding: 16px;
            border-radius: 12px;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .message.user {
            background: #1e3a5f;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }
        
        .message.assistant {
            background: #1a1a1a;
            border: 1px solid #333;
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }
        
        .message .role {
            font-size: 12px;
            color: #888;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        
        .message .content {
            line-height: 1.6;
            white-space: pre-wrap;
        }
        
        .message .content strong {
            color: #60a5fa;
        }
        
        .message .meta {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #333;
            font-size: 12px;
            color: #666;
        }
        
        .message .verdict {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
        }
        
        .verdict.supported { background: #065f46; color: #34d399; }
        .verdict.mostly_supported { background: #065f46; color: #34d399; }
        .verdict.partly_supported { background: #78350f; color: #fbbf24; }
        .verdict.unsupported { background: #7f1d1d; color: #f87171; }
        .verdict.unverified { background: #374151; color: #9ca3af; }
        
        .input-container {
            background: #1a1a1a;
            padding: 24px;
            border-top: 1px solid #333;
        }
        
        .input-wrapper {
            max-width: 800px;
            margin: 0 auto;
            display: flex;
            gap: 12px;
        }
        
        .input-wrapper textarea {
            flex: 1;
            background: #0f0f0f;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 12px 16px;
            color: #fff;
            font-size: 15px;
            resize: none;
            min-height: 48px;
            max-height: 200px;
            font-family: inherit;
        }
        
        .input-wrapper textarea:focus {
            outline: none;
            border-color: #60a5fa;
        }
        
        .input-wrapper button {
            background: #60a5fa;
            color: #fff;
            border: none;
            border-radius: 12px;
            padding: 12px 24px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .input-wrapper button:hover {
            background: #3b82f6;
        }
        
        .input-wrapper button:disabled {
            background: #374151;
            cursor: not-allowed;
        }
        
        .typing-indicator {
            display: none;
            align-items: center;
            gap: 4px;
            padding: 16px;
            color: #888;
        }
        
        .typing-indicator.active {
            display: flex;
        }
        
        .typing-indicator span {
            width: 8px;
            height: 8px;
            background: #666;
            border-radius: 50%;
            animation: typing 1.4s infinite;
        }
        
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
        
        @keyframes typing {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-4px); }
        }
        
        .welcome {
            max-width: 800px;
            margin: auto;
            text-align: center;
            padding: 48px 24px;
        }
        
        .welcome h2 {
            font-size: 28px;
            margin-bottom: 16px;
            color: #fff;
        }
        
        .welcome p {
            color: #888;
            font-size: 16px;
            line-height: 1.6;
        }
        
        .welcome .examples {
            margin-top: 32px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .welcome .example {
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 12px 16px;
            cursor: pointer;
            transition: border-color 0.2s;
            text-align: left;
        }
        
        .welcome .example:hover {
            border-color: #60a5fa;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Arı Kaynak</h1>
        <span class="subtitle">AI Fact Checker</span>
        <div class="status">
            <span class="dot"></span>
            <span>19 sources active</span>
        </div>
    </div>
    
    <div class="chat-container" id="chatContainer">
        <div class="welcome" id="welcome">
            <h2>Merhaba!</h2>
            <p>Herhangi bir iddiayı doğrulamak için sorunuzu yazın.<br>
            19 tıbbi kaynaktan kanıt toplayarak hüküm vereceğim.</p>
            <div class="examples">
                <div class="example" onclick="setExample(this)">
                    Vitamin D eksikliği osteoporoz riskini artırır mı?
                </div>
                <div class="example" onclick="setExample(this)">
                    Günlük 10000 adım ölüm riskini azaltır mı?
                </div>
                <div class="example" onclick="setExample(this)">
                    Probiyotikler sindirim sağlığını iyileştirir mi?
                </div>
            </div>
        </div>
        
        <div class="typing-indicator" id="typingIndicator">
            <span></span>
            <span></span>
            <span></span>
            <span style="width: auto; font-size: 13px;">19 kaynaktan kanıt toplanıyor...</span>
        </div>
    </div>
    
    <div class="input-container">
        <div class="input-wrapper">
            <textarea 
                id="userInput" 
                placeholder="İddianızı yazın..."
                rows="1"
                onkeydown="handleKeyDown(event)"
                oninput="autoResize(this)"
            ></textarea>
            <button id="sendBtn" onclick="sendMessage()">Gönder</button>
        </div>
    </div>
    
    <script>
        let sessionId = null;
        let isProcessing = false;
        
        function setExample(el) {
            document.getElementById('userInput').value = el.textContent.trim();
            autoResize(document.getElementById('userInput'));
            document.getElementById('userInput').focus();
        }
        
        function autoResize(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 200) + 'px';
        }
        
        function handleKeyDown(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        }
        
        function addMessage(role, content, meta = null) {
            const container = document.getElementById('chatContainer');
            const welcome = document.getElementById('welcome');
            if (welcome) welcome.style.display = 'none';
            
            const div = document.createElement('div');
            div.className = `message ${role}`;
            
            let html = `<div class="role">${role === 'user' ? 'Sen' : 'Arı Kaynak'}</div>`;
            html += `<div class="content">${escapeHtml(content)}</div>`;
            
            if (meta) {
                html += `<div class="meta">${meta}</div>`;
            }
            
            div.innerHTML = html;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
            
            return div;
        }
        
        function addStreamingMessage() {
            const container = document.getElementById('chatContainer');
            const welcome = document.getElementById('welcome');
            if (welcome) welcome.style.display = 'none';
            
            const div = document.createElement('div');
            div.className = 'message assistant';
            div.id = 'streamingMessage';
            div.innerHTML = `
                <div class="role">Arı Kaynak</div>
                <div class="content" id="streamingContent"></div>
                <div class="meta" id="streamingMeta"></div>
            `;
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
            
            return div;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const query = input.value.trim();
            
            if (!query || isProcessing) return;
            
            isProcessing = true;
            document.getElementById('sendBtn').disabled = true;
            document.getElementById('typingIndicator').classList.add('active');
            
            addMessage('user', query);
            input.value = '';
            autoResize(input);
            
            try {
                const response = await fetch('/v1/verify', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId || '',
                    },
                    body: JSON.stringify({ query, stream: false }),
                });
                
                const data = await response.json();
                sessionId = data.session_id || sessionId;
                
                const meta = `
                    <span class="verdict ${data.verdict}">${data.verdict.replace('_', ' ')}</span>
                    &nbsp;|&nbsp; Confidence: ${Math.round(data.verdict_confidence * 100)}%
                    &nbsp;|&nbsp; Sources: ${data.archive_results.length + data.external_results.length + data.health_org_results.length}
                `;
                
                addMessage('assistant', data.cited_response, meta);
            } catch (error) {
                addMessage('assistant', 'Bir hata oluştu: ' + error.message);
            }
            
            document.getElementById('typingIndicator').classList.remove('active');
            isProcessing = false;
            document.getElementById('sendBtn').disabled = false;
        }
    </script>
</body>
</html>"""
