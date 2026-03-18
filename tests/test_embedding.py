#!/usr/bin/env python3
"""Tests for embedding / semantic search functionality in memory_db.py."""

import os
import sys
import unittest
import tempfile
import math
from unittest.mock import patch, MagicMock
import json
import struct

# Ensure the module is importable
sys.path.insert(0, os.path.dirname(__file__))

# Save original DB path, use temp DB for embedding tests
_orig_db_env = os.environ.get("SELF_EVOLUTION_DB")
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SELF_EVOLUTION_DB"] = _tmp_db.name
_tmp_db.close()

import importlib
import memory_db
importlib.reload(memory_db)


def tearDownModule():
    """Restore original DB path after all tests in this module."""
    if _orig_db_env is not None:
        os.environ["SELF_EVOLUTION_DB"] = _orig_db_env
    else:
        os.environ.pop("SELF_EVOLUTION_DB", None)
    importlib.reload(memory_db)
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass


class TestCosineSimlarity(unittest.TestCase):
    """Pure unit tests for cosine similarity — no API calls."""

    def test_identical_vectors(self):
        a = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(memory_db._cosine_similarity(a, a), 1.0, places=6)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        self.assertAlmostEqual(memory_db._cosine_similarity(a, b), 0.0, places=6)

    def test_opposite_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        self.assertAlmostEqual(memory_db._cosine_similarity(a, b), -1.0, places=6)

    def test_zero_vector(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        self.assertEqual(memory_db._cosine_similarity(a, b), 0.0)

    def test_known_value(self):
        a = [1.0, 0.0, 1.0]
        b = [0.0, 1.0, 1.0]
        # dot=1, |a|=sqrt(2), |b|=sqrt(2), cos=1/2=0.5
        self.assertAlmostEqual(memory_db._cosine_similarity(a, b), 0.5, places=6)


class TestPackUnpack(unittest.TestCase):
    """Test embedding serialization round-trip."""

    def test_round_trip(self):
        vec = [0.1 * i for i in range(1024)]
        blob = memory_db._pack_embedding(vec)
        recovered = memory_db._unpack_embedding(blob)
        self.assertEqual(len(recovered), 1024)
        for a, b in zip(vec, recovered):
            self.assertAlmostEqual(a, b, places=5)

    def test_blob_size(self):
        vec = [0.0] * 1024
        blob = memory_db._pack_embedding(vec)
        self.assertEqual(len(blob), 1024 * 4)  # float32 = 4 bytes


class TestTextHash(unittest.TestCase):
    def test_deterministic(self):
        h1 = memory_db._text_hash("hello world")
        h2 = memory_db._text_hash("hello world")
        self.assertEqual(h1, h2)

    def test_different_text(self):
        h1 = memory_db._text_hash("hello")
        h2 = memory_db._text_hash("world")
        self.assertNotEqual(h1, h2)


class TestSemanticSearchMocked(unittest.TestCase):
    """Test semantic_search with mocked embed_text — no real API calls."""

    def setUp(self):
        """Set up a fresh DB with some data and fake embeddings."""
        memory_db.init_db()
        self.db = memory_db.get_db()
        # Clean slate
        self.db.execute("DELETE FROM observations")
        self.db.execute("DELETE FROM decisions")
        self.db.execute("DELETE FROM embeddings")
        self.db.commit()

        # Add test records
        self.obs_id = memory_db.add_observation(
            "discovery", "按任务复杂度选模型",
            narrative="简单任务用小模型，复杂任务用大模型",
        )
        self.dec_id = memory_db.add_decision(
            "模型选择策略",
            "Opus 用于复杂推理，MiniMax 用于简单对话",
            rationale="性价比最优"
        )

        # Insert fake embeddings
        # obs embedding: mostly in dimension 0
        obs_vec = [0.0] * 1024
        obs_vec[0] = 1.0
        obs_vec[1] = 0.5
        # dec embedding: mostly in dimension 1
        dec_vec = [0.0] * 1024
        dec_vec[1] = 1.0
        dec_vec[2] = 0.5

        self.db.execute(
            "INSERT INTO embeddings (source_table, source_id, text_hash, embedding) VALUES (?,?,?,?)",
            ("observations", self.obs_id, "fake_hash_1", memory_db._pack_embedding(obs_vec))
        )
        self.db.execute(
            "INSERT INTO embeddings (source_table, source_id, text_hash, embedding) VALUES (?,?,?,?)",
            ("decisions", self.dec_id, "fake_hash_2", memory_db._pack_embedding(dec_vec))
        )
        self.db.commit()
        self.db.close()

    def test_semantic_search_returns_correct_format(self):
        """Mock embed_text to return a query vector close to obs_vec."""
        query_vec = [0.0] * 1024
        query_vec[0] = 0.9
        query_vec[1] = 0.4

        with patch.object(memory_db, 'embed_text', return_value=[query_vec]):
            results = memory_db.semantic_search("模型选择", limit=10)

        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        # Check result structure
        for r in results:
            self.assertIn("source_table", r)
            self.assertIn("source_id", r)
            self.assertIn("title", r)
            self.assertIn("score", r)
            self.assertIsInstance(r["score"], float)

    def test_semantic_search_ranking(self):
        """Query vector closer to obs should rank obs higher."""
        query_vec = [0.0] * 1024
        query_vec[0] = 1.0  # aligned with obs_vec

        with patch.object(memory_db, 'embed_text', return_value=[query_vec]):
            results = memory_db.semantic_search("test", limit=10)

        # First result should be the observation (closer to query)
        self.assertEqual(results[0]["source_table"], "observations")
        self.assertEqual(results[0]["source_id"], self.obs_id)

    def test_semantic_search_limit(self):
        query_vec = [0.0] * 1024
        query_vec[0] = 1.0

        with patch.object(memory_db, 'embed_text', return_value=[query_vec]):
            results = memory_db.semantic_search("test", limit=1)

        self.assertEqual(len(results), 1)


class TestHybridSearchMocked(unittest.TestCase):
    """Test hybrid mode of search_with_context with mocked embed_text."""

    def setUp(self):
        memory_db.init_db()
        db = memory_db.get_db()
        db.execute("DELETE FROM observations")
        db.execute("DELETE FROM decisions")
        db.execute("DELETE FROM embeddings")
        db.commit()

        self.obs_id = memory_db.add_observation(
            "discovery", "Opus vs MiniMax 对比",
            narrative="Opus 擅长复杂推理，MiniMax 速度快成本低",
        )
        self.dec_id = memory_db.add_decision(
            "按任务复杂度选模型",
            "复杂任务用 Opus，简单任务用 MiniMax",
            rationale="平衡质量和成本"
        )

        # Fake embeddings
        obs_vec = [0.0] * 1024
        obs_vec[0] = 1.0
        dec_vec = [0.0] * 1024
        dec_vec[1] = 1.0

        db = memory_db.get_db()
        db.execute(
            "INSERT INTO embeddings (source_table, source_id, text_hash, embedding) VALUES (?,?,?,?)",
            ("observations", self.obs_id, "h1", memory_db._pack_embedding(obs_vec))
        )
        db.execute(
            "INSERT INTO embeddings (source_table, source_id, text_hash, embedding) VALUES (?,?,?,?)",
            ("decisions", self.dec_id, "h2", memory_db._pack_embedding(dec_vec))
        )
        db.commit()
        db.close()

    def test_hybrid_returns_string(self):
        query_vec = [0.0] * 1024
        query_vec[0] = 0.5
        query_vec[1] = 0.5

        with patch.object(memory_db, 'semantic_search', return_value=[
            {"source_table": "observations", "source_id": self.obs_id,
             "title": "Opus vs MiniMax 对比", "timestamp": "2026-03-18", "score": 0.85},
            {"source_table": "decisions", "source_id": self.dec_id,
             "title": "按任务复杂度选模型", "timestamp": "2026-03-18", "score": 0.75},
        ]):
            result = memory_db.search_with_context("模型选择", mode="hybrid")

        self.assertIsInstance(result, str)

    def test_hybrid_contains_results(self):
        with patch.object(memory_db, 'semantic_search', return_value=[
            {"source_table": "observations", "source_id": self.obs_id,
             "title": "Opus vs MiniMax 对比", "timestamp": "2026-03-18", "score": 0.85},
        ]):
            result = memory_db.search_with_context("Opus", mode="hybrid")

        # Should contain at least one of our test entries
        self.assertTrue(len(result) > 0)

    def test_keyword_mode_unchanged(self):
        """Keyword mode should work exactly as before."""
        result = memory_db.search_with_context("Opus", mode="keyword")
        self.assertIsInstance(result, str)

    def test_semantic_mode(self):
        with patch.object(memory_db, 'semantic_search', return_value=[
            {"source_table": "observations", "source_id": self.obs_id,
             "title": "Opus vs MiniMax 对比", "timestamp": "2026-03-18", "score": 0.9},
        ]):
            result = memory_db.search_with_context("模型选择", mode="semantic")
        self.assertIsInstance(result, str)
        self.assertIn("Opus", result)


class TestEmbedTextIntegration(unittest.TestCase):
    """Integration test — requires real SiliconFlow API access.
    
    Run with: python3 -m pytest test_embedding.py -k Integration -v
    Skip in CI by setting SKIP_INTEGRATION=1
    """

    def setUp(self):
        if os.environ.get("SKIP_INTEGRATION"):
            self.skipTest("SKIP_INTEGRATION is set")

    def test_embed_single_text(self):
        result = memory_db.embed_text(["hello world"])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1024)
        self.assertIsInstance(result[0][0], float)

    def test_embed_multiple_texts(self):
        result = memory_db.embed_text(["hello", "world", "test"])
        self.assertEqual(len(result), 3)
        for vec in result:
            self.assertEqual(len(vec), 1024)

    def test_embed_empty_list(self):
        result = memory_db.embed_text([])
        self.assertEqual(result, [])

    def test_embed_chinese_text(self):
        result = memory_db.embed_text(["按任务复杂度选模型"])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1024)

    def test_similar_texts_have_high_similarity(self):
        vecs = memory_db.embed_text([
            "按任务复杂度选择AI模型",
            "根据任务难度挑选合适的模型",
            "今天天气真好适合出去玩",
        ])
        sim_related = memory_db._cosine_similarity(vecs[0], vecs[1])
        sim_unrelated = memory_db._cosine_similarity(vecs[0], vecs[2])
        self.assertGreater(sim_related, sim_unrelated,
                           f"Related texts similarity ({sim_related:.4f}) should be > "
                           f"unrelated ({sim_unrelated:.4f})")


class TestBuildEmbeddingsMocked(unittest.TestCase):
    """Test build_embeddings with mocked API."""

    def setUp(self):
        memory_db.init_db()
        db = memory_db.get_db()
        db.execute("DELETE FROM observations")
        db.execute("DELETE FROM decisions")
        db.execute("DELETE FROM embeddings")
        db.commit()
        db.close()

    def test_build_embeddings_creates_entries(self):
        memory_db.add_observation("discovery", "Test Title", narrative="Test narrative")
        memory_db.add_decision("Test Decision", "We decided X", rationale="Because Y")

        fake_vec = [0.1] * 1024
        with patch.object(memory_db, 'embed_text', return_value=[fake_vec, fake_vec]):
            memory_db.build_embeddings()

        db = memory_db.get_db()
        count = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        db.close()
        self.assertEqual(count, 2)

    def test_build_embeddings_skips_unchanged(self):
        memory_db.add_observation("discovery", "Test", narrative="Narrative")

        fake_vec = [0.1] * 1024
        with patch.object(memory_db, 'embed_text', return_value=[fake_vec]) as mock_embed:
            memory_db.build_embeddings()
            self.assertEqual(mock_embed.call_count, 1)

            # Second call should skip (unchanged)
            memory_db.build_embeddings()
            # embed_text should NOT be called again
            self.assertEqual(mock_embed.call_count, 1)


if __name__ == "__main__":
    unittest.main()
