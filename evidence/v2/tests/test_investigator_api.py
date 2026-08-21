"""Tests for Conversational Investigator API endpoints."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from evidence.chat.conversation import ConversationManager
from evidence.chat.response import ChatResponse
from evidence.v2.api.app import VerifyRequest, create_app


def _parse_sse(body: str) -> list[dict]:
    events = []
    for part in body.split("\n\n"):
        part = part.strip()
        if not part.startswith("data:"):
            continue
        events.append(json.loads(part[len("data:"):]))
    return events


class TestInvestigatorAPI:
    @pytest.fixture(autouse=True)
    def fast_handle(self, monkeypatch):
        """handle_message'i ag/LLM cagrisi yapmayan sahte cevapla degistir."""

        async def fake_handle(self, user_query: str) -> ChatResponse:
            self.state.turn_count += 1
            return ChatResponse(
                text=f"**Hüküm:** supported — {user_query}",
                intent_type="claim_verification",
                confidence=0.87,
                sources_cited=3,
                follow_up_suggestions=["Takip sorusu 1", "Takip sorusu 2"],
            )

        monkeypatch.setattr(ConversationManager, "handle_message", fake_handle)

    @pytest.mark.asyncio
    async def test_chat_returns_response(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat",
                json={"query": "Kahve kolesterolu yukseltir mi?"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "Kahve" in data["response"]
            assert data["intent"] == "claim_verification"
            assert data["confidence"] == pytest.approx(0.87)
            assert data["sources_cited"] == 3
            assert len(data["follow_up_suggestions"]) == 2

    @pytest.mark.asyncio
    async def test_default_session_used_without_session_id(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/investigator/chat", json={"query": "deneme sorgusu"})
            stats = await client.get("/v1/investigator/stats")
            assert stats.json()["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_sessions_are_isolated(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/investigator/chat", json={"query": "sorgu bir", "session_id": "A"})
            await client.post("/v1/investigator/chat", json={"query": "sorgu iki", "session_id": "A"})
            await client.post("/v1/investigator/chat", json={"query": "sorgu uc", "session_id": "B"})

            stats_a = (await client.get("/v1/investigator/stats", params={"session_id": "A"})).json()
            stats_b = (await client.get("/v1/investigator/stats", params={"session_id": "B"})).json()

            assert stats_a["turn_count"] == 2
            assert stats_b["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_stats_unknown_session_returns_zeros(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/investigator/stats", params={"session_id": "yok"})
            assert resp.status_code == 200
            assert resp.json() == {"turn_count": 0, "total_sources_found": 0}

    @pytest.mark.asyncio
    async def test_reset_only_target_session(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/investigator/chat", json={"query": "sorgu bir", "session_id": "A"})
            await client.post("/v1/investigator/chat", json={"query": "sorgu iki", "session_id": "B"})

            resp = await client.post("/v1/investigator/reset", params={"session_id": "A"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            stats_a = (await client.get("/v1/investigator/stats", params={"session_id": "A"})).json()
            stats_b = (await client.get("/v1/investigator/stats", params={"session_id": "B"})).json()
            assert stats_a["turn_count"] == 0
            assert stats_b["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_stream_event_order_and_payload(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat/stream",
                json={"query": "Aspirin kalp krizinden korur mu?", "session_id": "S"},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")

            events = _parse_sse(resp.text)
            types = [e["type"] for e in events]

            assert types[0] == "start"
            assert types.count("step") >= 1
            assert "steps_done" in types
            assert types.count("chunk") >= 1
            assert types[-1] == "done"

            # chunk'lar sirali birlesince tam metin olmali
            text = "".join(e["content"] for e in events if e["type"] == "chunk")
            assert text.startswith("**Hüküm:** supported")

            done = events[-1]
            assert done["intent"] == "claim_verification"
            assert done["confidence"] == pytest.approx(0.87)
            assert done["sources_cited"] == 3
            assert done["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_stream_uses_session_manager(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/v1/investigator/chat/stream", json={"query": "sorgu bir", "session_id": "SX"})
            stats = (await client.get("/v1/investigator/stats", params={"session_id": "SX"})).json()
            assert stats["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_query_too_short_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/v1/investigator/chat", json={"query": "ab"})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_session_id_max_length_rejected(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/investigator/chat",
                json={"query": "gecerli sorgu", "session_id": "x" * 65},
            )
            assert resp.status_code == 422


class TestSessionEviction:
    @pytest.fixture(autouse=True)
    def fast_handle(self, monkeypatch):
        async def fake_handle(self, user_query: str) -> ChatResponse:
            self.state.turn_count += 1
            return ChatResponse(text="ok", intent_type="general_question", confidence=0.5)

        monkeypatch.setattr(ConversationManager, "handle_message", fake_handle)

    @pytest.mark.asyncio
    async def test_max_sessions_eviction(self):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 64 oturum doldur (default + s01..s63), sonra 65.'yi ac
            await client.post("/v1/investigator/chat", json={"query": "default sorgu"})
            for i in range(1, 64):
                await client.post(
                    "/v1/investigator/chat",
                    json={"query": f"sorgu {i}", "session_id": f"s{i:02d}"},
                )
            await client.post("/v1/investigator/chat", json={"query": "yeni gelen", "session_id": "s64"})

            # En eski oturum (default) evict edildi -> sifirlardan doner
            stats_default = (await client.get("/v1/investigator/stats")).json()
            assert stats_default == {"turn_count": 0, "total_sources_found": 0}

            # En yeni oturum yasiyor
            stats_new = (await client.get("/v1/investigator/stats", params={"session_id": "s64"})).json()
            assert stats_new["turn_count"] == 1


class TestVerifyRequestModel:
    def test_session_id_optional(self):
        v = VerifyRequest(query="test sorgu burada")
        assert v.session_id is None

    def test_session_id_accepted(self):
        v = VerifyRequest(query="test sorgu burada", session_id="abc")
        assert v.session_id == "abc"
