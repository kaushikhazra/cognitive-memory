"""Embedding service — lazy-loaded sentence-transformers with in-memory numpy matrix."""

from __future__ import annotations

from typing import Optional

import numpy as np


class EmbeddingService:
    """Manages embeddings: lazy model loading, vector generation, similarity search."""

    DIMENSIONS = 384
    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self):
        self._model = None
        # In-memory matrix: maps memory_id -> row index
        self._id_to_idx: dict[str, int] = {}
        self._idx_to_id: dict[int, str] = {}
        self._matrix: Optional[np.ndarray] = None  # shape: (N, 384)
        self._next_idx: int = 0

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def _ensure_model(self) -> None:
        """Lazy-load the embedding model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.MODEL_NAME)

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for text. Returns float32 array of shape (384,)."""
        self._ensure_model()
        vec = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype(np.float32)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for multiple texts. Returns (N, 384) array."""
        self._ensure_model()
        vecs = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return vecs.astype(np.float32)

    def to_bytes(self, embedding: np.ndarray) -> bytes:
        """Convert numpy embedding to bytes for SQLite storage."""
        return embedding.astype(np.float32).tobytes()

    def from_bytes(self, data: bytes) -> np.ndarray:
        """Convert bytes from SQLite back to numpy embedding."""
        return np.frombuffer(data, dtype=np.float32).copy()

    # --- In-memory matrix management ---

    def load_matrix(self, embeddings: dict[str, np.ndarray]) -> None:
        """Load initial embedding matrix from {memory_id: vector} dict."""
        if not embeddings:
            self._matrix = np.empty((0, self.DIMENSIONS), dtype=np.float32)
            self._id_to_idx = {}
            self._idx_to_id = {}
            self._next_idx = 0
            return

        ids = list(embeddings.keys())
        vectors = [embeddings[mid] for mid in ids]
        self._matrix = np.vstack(vectors).astype(np.float32)
        self._id_to_idx = {mid: i for i, mid in enumerate(ids)}
        self._idx_to_id = {i: mid for i, mid in enumerate(ids)}
        self._next_idx = len(ids)

    def add_to_matrix(self, memory_id: str, embedding: np.ndarray) -> None:
        """Add a new embedding to the in-memory matrix."""
        vec = embedding.astype(np.float32).reshape(1, -1)
        if self._matrix is None or self._matrix.shape[0] == 0:
            self._matrix = vec
        else:
            self._matrix = np.vstack([self._matrix, vec])
        idx = self._next_idx
        self._id_to_idx[memory_id] = idx
        self._idx_to_id[idx] = memory_id
        self._next_idx += 1

    def remove_from_matrix(self, memory_id: str) -> None:
        """Remove an embedding from the in-memory matrix."""
        if memory_id not in self._id_to_idx:
            return
        idx = self._id_to_idx[memory_id]
        # Delete the row and rebuild index mappings
        if self._matrix is not None and self._matrix.shape[0] > 0:
            self._matrix = np.delete(self._matrix, idx, axis=0)

        # Rebuild mappings
        del self._id_to_idx[memory_id]
        del self._idx_to_id[idx]
        new_id_to_idx = {}
        new_idx_to_id = {}
        for i, (old_idx, mid) in enumerate(sorted(self._idx_to_id.items())):
            new_id_to_idx[mid] = i
            new_idx_to_id[i] = mid
        self._id_to_idx = new_id_to_idx
        self._idx_to_id = new_idx_to_id
        self._next_idx = len(self._id_to_idx)

    def replace_in_matrix(self, memory_id: str, embedding: np.ndarray) -> None:
        """Replace an existing embedding in the matrix."""
        if memory_id in self._id_to_idx:
            idx = self._id_to_idx[memory_id]
            self._matrix[idx] = embedding.astype(np.float32)
        else:
            self.add_to_matrix(memory_id, embedding)

    # --- Search ---

    def cosine_search(self, query_vec: np.ndarray, top_k: int = 30) -> list[tuple[str, float]]:
        """Search the in-memory matrix for top-k most similar. Returns [(memory_id, score)]."""
        if self._matrix is None or self._matrix.shape[0] == 0:
            return []

        query = query_vec.astype(np.float32).reshape(1, -1)
        # Normalize for cosine similarity
        query_norm = query / (np.linalg.norm(query, axis=1, keepdims=True) + 1e-10)
        matrix_norm = self._matrix / (np.linalg.norm(self._matrix, axis=1, keepdims=True) + 1e-10)

        scores = (matrix_norm @ query_norm.T).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            idx_int = int(idx)
            if idx_int in self._idx_to_id:
                results.append((self._idx_to_id[idx_int], float(scores[idx_int])))
        return results

    def cosine_similarity_pair(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        a = vec_a.astype(np.float32)
        b = vec_b.astype(np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def get_matrix_size_mb(self) -> float:
        """Get approximate memory usage of the embedding matrix in MB."""
        if self._matrix is None:
            return 0.0
        return self._matrix.nbytes / (1024 * 1024)

    @property
    def matrix_count(self) -> int:
        """Number of embeddings in the matrix."""
        if self._matrix is None:
            return 0
        return self._matrix.shape[0]
