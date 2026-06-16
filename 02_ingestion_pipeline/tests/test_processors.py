"""Unit tests for DataProcessing components."""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from data_processing.domain.models import ProcessedData, ProcessingStatus
from data_processing.application.pipeline_handlers import (
    ValidationHandler,
    NormalizationHandler,
    EnrichmentHandler,
    TransformHandler,
)
from data_processing.application.pipeline_factory import build_default_pipeline


class TestValidationHandler:
    """Tests for ValidationHandler."""

    def test_valid_data(self):
        """Test validation of valid data."""
        handler = ValidationHandler()
        data = ProcessedData(
            file_id="test_1",
            source="test",
            content_clean="test content",
            processed_at=datetime.now(),
        )

        result = handler._process(data)
        assert result.is_valid
        assert "validation" in result.processing_steps

    def test_invalid_data_missing_file_id(self):
        """Test validation fails for missing file_id."""
        handler = ValidationHandler()
        data = ProcessedData(
            file_id="",
            source="test",
            content_clean="test content",
            processed_at=datetime.now(),
        )

        result = handler._process(data)
        assert not result.is_valid
        assert len(result.errors) > 0


class TestNormalizationHandler:
    """Tests for NormalizationHandler."""

    def test_normalize_text(self):
        """Test text normalization."""
        handler = NormalizationHandler()
        data = ProcessedData(
            file_id="test_1",
            source="test",
            content_clean="  HELLO   WORLD  ",
            processed_at=datetime.now(),
            is_valid=True,
        )

        result = handler._process(data)
        assert result.content_clean.lower() == "hello world"
        assert "normalization" in result.processing_steps


class TestEnrichmentHandler:
    """Tests for EnrichmentHandler."""

    def test_enrich_data(self):
        """Test data enrichment."""
        handler = EnrichmentHandler()
        data = ProcessedData(
            file_id="test_1",
            source="test",
            content_clean="hello world test",
            processed_at=datetime.now(),
            is_valid=True,
        )

        result = handler._process(data)
        assert "word_count" in result.structured_data
        assert result.structured_data["word_count"] == 3
        assert "enrichment" in result.processing_steps


class TestPipelineFactory:
    """Tests for pipeline factory."""

    def test_build_default_pipeline(self):
        """Test building default pipeline."""
        pipeline = build_default_pipeline()
        assert pipeline is not None
        # Check pipeline chain
        assert pipeline.__class__.__name__ == "ValidationHandler"

    def test_pipeline_execution(self):
        """Test executing the pipeline."""
        pipeline = build_default_pipeline()
        data = ProcessedData(
            file_id="test_1",
            source="test",
            content_clean="  TEST  DATA  ",
            processed_at=datetime.now(),
        )

        result = pipeline.handle(data)

        # Should have gone through all handlers
        assert "validation" in result.processing_steps
        assert "normalization" in result.processing_steps
        assert "enrichment" in result.processing_steps
        assert "transform" in result.processing_steps


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
