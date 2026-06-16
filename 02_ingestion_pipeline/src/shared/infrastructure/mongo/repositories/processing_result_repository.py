"""MongoDB repository for processing results."""

from __future__ import annotations

from shared.domain.processing_result import ProcessingResult
from shared.infrastructure.mongo.base_repository import BaseMongoRepository


class ProcessingResultRepository(BaseMongoRepository[ProcessingResult]):

    COLLECTION_NAME = "processing_results"

    def __init__(self) -> None:
        super().__init__(
            model=ProcessingResult,
            collection_name=self.COLLECTION_NAME,
        )

    def upsert_by_run_id(self, result: ProcessingResult) -> bool:
        """
        Upsert result by run_id.
        Nếu đã tồn tại run_id thì update, chưa có thì insert.
        """
        existing = self.find_one(run_id=result.run_id)
        if existing:
            # gắn _id của document cũ vào model mới để update_one biết update cái nào
            result_with_id = result.model_copy(update={"result_id": existing.result_id})
            return self.update_one(result_with_id)
        else:
            inserted_id = self.insert_one(result)
            return inserted_id is not None