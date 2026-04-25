"""
RAG retrieval and grounded answering over historical news articles.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from src.config import AppConfig
from src.news.news_models import NewsArticle, NewsRagAnswer, NewsRagCitation

logger = logging.getLogger("autofetchstock.news.rag")


class NewsRagService:
    """Build, query, and answer against a local news embedding index."""

    def __init__(self, config: AppConfig, news_dir: Path) -> None:
        self._config = config
        self._news_dir = Path(news_dir)
        self._embeddings_path = self._news_dir / "rag_embeddings.npz"
        self._metadata_path = self._news_dir / "rag_metadata.json"
        self._client = None
        self._answer_model = "gemini-3.1-flash-lite-preview"

        if self._enabled:
            self._init_client()

    @property
    def _enabled(self) -> bool:
        return bool(getattr(self._config, "news_rag_enabled", False))

    def _init_client(self) -> None:
        if not self._config.gemini_api_key:
            logger.warning("News RAG enabled but GEMINI_API_KEY is not configured")
            return
        try:
            import google.genai as genai
            self._client = genai.Client(api_key=self._config.gemini_api_key)
        except Exception as exc:
            logger.warning("News RAG client init failed: %s", exc)

    def build_or_update_index(self, historical_articles: List[NewsArticle]) -> int:
        """Build or incrementally update the local embedding index."""
        if not self._enabled or self._client is None:
            return 0

        matrix, metadata = self._load_index()
        matrix, metadata = self._gc_old_rows(matrix, metadata)
        existing_hashes = {item.get("content_hash") for item in metadata}
        new_rows = []
        new_items = []
        limit = int(getattr(self._config, "news_rag_max_new_embeddings_per_day", 100))

        for article in historical_articles:
            item = self._article_metadata(article)
            if item["content_hash"] in existing_hashes:
                continue
            if len(new_items) >= limit:
                logger.warning("News RAG embedding daily limit reached: %d", limit)
                break
            vector = self._embed_text(self._article_text(article))
            if vector is None:
                continue
            new_rows.append(vector)
            new_items.append(item)
            existing_hashes.add(item["content_hash"])

        if new_rows:
            new_matrix = np.vstack(new_rows)
            matrix = new_matrix if matrix.size == 0 else np.vstack([matrix, new_matrix])
            metadata.extend(new_items)

        self._save_index(matrix, metadata)
        return len(new_items)

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[NewsRagCitation]:
        """Retrieve top-k similar historical news chunks."""
        if not self._enabled or self._client is None or not query.strip():
            return []
        matrix, metadata = self._load_index()
        if matrix.size == 0 or not metadata:
            return []

        query_vector = self._embed_text(query)
        if query_vector is None:
            return []
        top_k = top_k or int(getattr(self._config, "news_rag_top_k", 8))

        matrix_norm = np.linalg.norm(matrix, axis=1)
        query_norm = np.linalg.norm(query_vector)
        denom = matrix_norm * query_norm
        denom[denom == 0] = 1.0
        scores = matrix.dot(query_vector) / denom
        order = np.argsort(scores)[::-1][:top_k]

        citations = []
        for idx in order:
            item = metadata[int(idx)]
            citations.append(NewsRagCitation(
                url=item.get("url", ""),
                title=item.get("title", ""),
                source=item.get("source", ""),
                published_at=item.get("published_at", ""),
                score=round(float(scores[int(idx)]), 4),
            ))
        return citations

    def answer(self, query: str, chat_history: Optional[List[dict]] = None) -> NewsRagAnswer:
        """Answer a user question using retrieved news citations."""
        if not self._enabled:
            return NewsRagAnswer(
                answer="新聞問答目前未啟用",
                failed=True,
                error_reason="news_rag_enabled=false",
            )
        if self._client is None:
            return NewsRagAnswer(
                answer="目前無法使用新聞問答",
                failed=True,
                error_reason="Gemini client unavailable",
            )
        citations = self.retrieve(query)
        if not citations:
            return NewsRagAnswer(
                answer="目前沒有足夠的歷史新聞可回答這個問題",
                citations=[],
                failed=True,
                error_reason="no citations",
            )

        history = self._trim_history(chat_history or [])
        prompt = self._build_answer_prompt(query, history, citations)
        try:
            response = self._client.models.generate_content(
                model=self._answer_model,
                contents=prompt,
            )
            answer = (response.text or "").strip()
        except Exception as exc:
            logger.warning("News RAG answer failed: %s", exc)
            return NewsRagAnswer(
                answer="目前無法回答，請稍後再試",
                citations=citations,
                failed=True,
                error_reason=str(exc)[:120],
            )
        return NewsRagAnswer(answer=answer, citations=citations, failed=False)

    def _load_index(self) -> Tuple[np.ndarray, List[dict]]:
        matrix = np.empty((0, 0), dtype=float)
        metadata: List[dict] = []
        if self._embeddings_path.exists():
            try:
                matrix = np.load(self._embeddings_path)["embeddings"]
            except Exception as exc:
                logger.warning("Failed to load RAG embeddings: %s", exc)
                matrix = np.empty((0, 0), dtype=float)
        if self._metadata_path.exists():
            try:
                with open(self._metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f).get("items", [])
            except Exception as exc:
                logger.warning("Failed to load RAG metadata: %s", exc)
                metadata = []
        if matrix.size and len(metadata) != matrix.shape[0]:
            logger.warning("RAG index row mismatch; resetting index")
            return np.empty((0, 0), dtype=float), []
        if not matrix.size:
            metadata = []
        return matrix, metadata

    def _save_index(self, matrix: np.ndarray, metadata: List[dict]) -> None:
        self._news_dir.mkdir(parents=True, exist_ok=True)
        np.savez(self._embeddings_path, embeddings=matrix)
        with open(self._metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {"updated_at": datetime.now().isoformat(), "items": metadata},
                f,
                ensure_ascii=False,
                indent=2,
            )

    def _gc_old_rows(
        self,
        matrix: np.ndarray,
        metadata: List[dict],
    ) -> Tuple[np.ndarray, List[dict]]:
        if not metadata or matrix.size == 0:
            return matrix, metadata
        keep_indices = []
        kept = []
        for idx, item in enumerate(metadata):
            try:
                published = datetime.fromisoformat(item.get("published_at", ""))
            except ValueError:
                published = datetime.now()
            cutoff = (
                datetime.now(published.tzinfo) if published.tzinfo else datetime.now()
            ) - timedelta(days=int(self._config.news_rag_window_days))
            if published >= cutoff:
                keep_indices.append(idx)
                kept.append(item)
        if len(keep_indices) == len(metadata):
            return matrix, metadata
        return matrix[keep_indices] if keep_indices else np.empty((0, 0), dtype=float), kept

    def _embed_text(self, text: str) -> Optional[np.ndarray]:
        try:
            response = self._client.models.embed_content(
                model=self._config.news_rag_embedding_model,
                contents=text,
            )
            embedding = getattr(response, "embedding", None)
            if embedding is not None and hasattr(embedding, "values"):
                return np.array(embedding.values, dtype=float)
            embeddings = getattr(response, "embeddings", None)
            if embeddings:
                return np.array(embeddings[0].values, dtype=float)
        except Exception as exc:
            logger.warning("News RAG embedding failed: %s", exc)
        return None

    @staticmethod
    def _article_text(article: NewsArticle) -> str:
        body = article.excerpt or article.summary or article.full_text[:500]
        return f"{article.title}\n{body}".strip()

    def _article_metadata(self, article: NewsArticle) -> dict:
        text = self._article_text(article)
        content_hash = hashlib.sha1(
            f"{article.url}|{text}".encode("utf-8")
        ).hexdigest()
        return {
            "url": article.url,
            "title": article.title,
            "source": article.source,
            "published_at": article.published_at.isoformat(),
            "category": article.category.value,
            "excerpt": article.excerpt,
            "content_hash": content_hash,
        }

    def _trim_history(self, history: List[dict]) -> List[dict]:
        max_turns = int(getattr(self._config, "news_rag_max_chat_history_turns", 6))
        return history[-max_turns * 2:]

    @staticmethod
    def _build_answer_prompt(
        query: str,
        history: List[dict],
        citations: List[NewsRagCitation],
    ) -> str:
        citation_lines = [
            f"[{idx + 1}] {c.title} | {c.source} | {c.published_at} | {c.url}"
            for idx, c in enumerate(citations)
        ]
        history_lines = [
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in history
        ]
        return (
            "你是財經新聞問答助理。只能根據引用新聞回答，不要捏造來源。\n"
            "回答請用繁體中文，並用 [1] [2] 標示引用。\n\n"
            f"歷史對話：\n{chr(10).join(history_lines) or '（無）'}\n\n"
            f"引用新聞：\n{chr(10).join(citation_lines)}\n\n"
            f"使用者問題：{query}"
        )
