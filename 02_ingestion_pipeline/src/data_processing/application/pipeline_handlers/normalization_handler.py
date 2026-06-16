"""Normalization handler — cleans and standardizes text data."""

import re
from data_processing.domain.models.processed_data import ProcessedData
from data_processing.domain.models.base_handler import BaseProcessingHandler


class NormalizationHandler(BaseProcessingHandler):
    """
    Step 2: Normalizes text format, encoding, whitespace, and case.
    Ensures consistent data format for downstream processing.
    """

    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Normalize text content.

        Args:
            data: Data to normalize

        Returns:
            Data with normalized text
        """
        # Skip if data is not valid
        if not data.is_valid:
            return data.model_copy(
                update={"processing_steps": data.processing_steps + ["normalization"]}
            )

        # Normalize text content
        clean_content = self._normalize_text(data.content_clean or "")

        return data.model_copy(
            update={
                "content_clean": clean_content,
                "processing_steps": data.processing_steps + ["normalization"],
            }
        )

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text by removing extra whitespace and converting to lowercase.

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        # Remove extra whitespace
        text = " ".join(text.split())

        # Remove special characters but keep basic punctuation
        text = re.sub(r"[^\w\s\.\,\!\?\-\']", "", text)

        # Convert to lowercase
        text = text.lower()

        # Trim edges
        text = text.strip()

        return text
