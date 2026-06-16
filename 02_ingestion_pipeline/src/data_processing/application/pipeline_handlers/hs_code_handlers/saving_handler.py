"""Saving handler for HS-code processing pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_processing.domain.models.base_handler import BaseProcessingHandler
from data_processing.domain.models.processed_data import ProcessedData, ProcessingStatus


class SavingHandler(BaseProcessingHandler):
    """
    Mark rows that need manual review.

    _process() prepares and validates input.
    _process_handler() adds a `need_check` column with default value 0.
    """

    step_name = "saving"

    def __init__(
        self,
        export_dir: str | Path = "exports",
    ) -> None:
        super().__init__()
        self.export_dir = Path(export_dir)

    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Execute the saving step for a processed HS-code dataset.

        Processing steps:
        1. If input data is already invalid, append the saving step and skip.
        2. Read structured_data and get the input dataframe.
        3. Validate the dataframe.
        4. Pass validated params to _process_handler for need_check marking.
        """
        # Step 1: Neu data da invalid tu handler truoc, chi ghi audit step va bo qua.
        if not data.is_valid:
            return data.model_copy(
                update={"processing_steps": data.processing_steps + [self.step_name]}
            )

        try:
            # Step 2: Lay structured_data va dataframe input.
            structured_data = dict(data.structured_data)
            df = structured_data.get("dataframe")
            if df is None:
                raise ValueError("dataframe not found in structured_data")

            # Step 3: Validate cac param dau vao truoc khi chay business logic.
            self._validate_process_params(
                df=df,
            )
        except Exception as exc:
            return self._fail(data, f"saving params invalid: {exc}")

        params = {
            "data": data,
            "df": df,
            "structured_data": structured_data,
        }

        # Step 4: Chuyen param da validate xuong handler chinh.
        return self._process_handler(**params)

    def _process_handler(
        self,
        data: ProcessedData,
        df: pd.DataFrame,
        structured_data: dict[str, Any],
    ) -> ProcessedData:
        """
        Mark rows that need manual review and update pipeline output.

        Processing steps:
        1. Clone the dataframe to avoid mutating data from previous handlers.
        2. Add "need_check" column with default value 0.
        3. Store dataframe and saving_result metadata.
        4. Append saving metadata to processing_step.
        5. Return updated ProcessedData with PROCESSING status.
        """
        # Step 5: Clone dataframe de tranh mutate data tu handler truoc.
        source_df = df.copy()
        source_df["need_check"] = 0

        need_check_df = source_df[source_df["need_check"] == 1].copy()

        # Step 8: Cap nhat structured_data de tra ve pipeline.
        updated_structured_data = dict(structured_data)
        updated_structured_data["dataframe"] = source_df
        updated_structured_data["saving_export_dataframe"] = need_check_df
        updated_structured_data["saving_result"] = {
            "total_rows": int(len(source_df)),
            "need_check_rows": int(source_df["need_check"].sum()),
        }

        processing_step = dict(updated_structured_data.get("processing_step", {}))
        processing_step["saving_handler"] = updated_structured_data["saving_result"]
        updated_structured_data["processing_step"] = processing_step

        # Step 9: Tao ProcessedData ket qua.
        return data.model_copy(
            update={
                "structured_data": updated_structured_data,
                "status": ProcessingStatus.PROCESSING,
                "processing_steps": data.processing_steps + [self.step_name],
            }
        )

    def _validate_process_params(
        self,
        df: Any,
    ) -> None:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("dataframe must be a pandas DataFrame")

    def _fail(self, data: ProcessedData, error: str) -> ProcessedData:
        structured_data = dict(data.structured_data)
        processing_step = dict(structured_data.get("processing_step", {}))
        processing_step["saving_handler"] = {"error": error}
        structured_data["processing_step"] = processing_step

        return data.model_copy(
            update={
                "structured_data": structured_data,
                "status": ProcessingStatus.FAILED,
                "is_valid": False,
                "errors": data.errors + [error],
                "processing_steps": data.processing_steps + [self.step_name],
            }
        )
