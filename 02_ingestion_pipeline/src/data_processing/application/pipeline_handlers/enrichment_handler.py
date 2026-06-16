"""Enrichment handler — adds metadata and supplementary information."""

from datetime import datetime

from data_processing.domain.models.base_handler import BaseProcessingHandler
from data_processing.domain.models.processed_data import ProcessedData



class EnrichmentHandler(BaseProcessingHandler):
    """
    Step 3: Enriches data by adding metadata, statistics, and derived information.
    Examples: word count, character count, language detection, entity extraction.
    """

    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Enrich data with additional metadata.

        Args:
            data: Data to enrich

        Returns:
            Data with enriched metadata
        """
        # Skip if data is not valid
        if not data.is_valid:
            return data.model_copy(
                update={"processing_steps": data.processing_steps + ["enrichment"]}
            )

        # Calculate statistics
        content = data.content_clean or ""
        words = content.split()
        sentences = [s.strip() for s in content.split(".") if s.strip()]

        enriched_data = {
            **data.structured_data,
            "word_count": len(words),
            "char_count": len(content),
            "sentence_count": len(sentences),
            "avg_word_length": (
                len(content) / len(words) if words else 0
            ),  # Approximate
            "enriched_at": datetime.utcnow().isoformat(),
        }

        return data.model_copy(
            update={
                "structured_data": enriched_data,
                "processing_steps": data.processing_steps + ["enrichment"],
            }
        )
