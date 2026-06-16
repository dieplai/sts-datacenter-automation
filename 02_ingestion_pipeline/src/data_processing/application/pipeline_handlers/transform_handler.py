"""Transform handler — transforms data to database-ready format."""

from datetime import datetime
from data_processing.domain.models.processed_data import ProcessedData, ProcessingStatus
from data_processing.domain.models.base_handler import BaseProcessingHandler


class TransformHandler(BaseProcessingHandler):
    """
    Step 4: Transforms data into database-ready format.
    Final step in the pipeline before persistence.
    """

    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Transform data to final format.

        Args:
            data: Data to transform

        Returns:
            Transformed data ready for storage
        """
        # Final status update
        status = ProcessingStatus.SUCCESS if data.is_valid else ProcessingStatus.FAILED

        transformed_data = data.model_copy(
            update={
                "status": status,
                "processed_at": datetime.utcnow(),
                "processing_steps": data.processing_steps + ["transform"],
            }
        )

        return transformed_data
