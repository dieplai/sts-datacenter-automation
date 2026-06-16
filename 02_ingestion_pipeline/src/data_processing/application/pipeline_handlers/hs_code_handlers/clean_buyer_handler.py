"""Clean buyer handler for HS-code processing pipelines."""

from __future__ import annotations

import pandas as pd

from data_processing.domain.models.base_handler import BaseProcessingHandler
from data_processing.domain.models.processed_data import ProcessedData, ProcessingStatus


BUYER_COLUMN = "Buyer"
BUYER_CLEANED_COLUMN = "Buyer Cleaned"
BUYER_ADDRESS_COLUMN = "Buyer Address"
BUYER_ADDRESS_CLEANED_COLUMN = "Buyer Address Cleaned"
BUYER_ADDRESS_COLUMNS = tuple(f"Buyer Address {index}" for index in range(1, 9))


class GroupByBuyerByAddressHandler(BaseProcessingHandler):
    """
    Clean buyer names and classify buyer-address outliers.

    _process() only prepares params, validates input, and creates the service.
    _process_handler() executes the clean buyer workflow from clean_buyer_process.md.
    """

    step_name = "clean_buyer"

    def _process(self, data: ProcessedData) -> ProcessedData:
        # Step 1: Neu data da invalid tu handler truoc, chi ghi audit step va bo qua.
        if not data.is_valid:
            return data.model_copy(
                update={"processing_steps": data.processing_steps + [self.step_name]}
            )

        try:
            # Step 2: Lay structured_data va dataframe input tu key mac dinh hoac key fallback.
            structured_data = dict(data.structured_data)
            df = structured_data.get("dataframe")
            if df is None:
                raise ValueError("dataframe not found in structured_data")

        except Exception as exc:
            return self._fail(data, f"clean buyer params invalid: {exc}")

        params = {
            "data": data,
            "df": df,
        }

        # Step 5: Chuyen param da validate xuong handler chinh de xu ly quy trinh clean buyer.
        handler_result = self._process_handler(**params)

        # Step 6: Sau khi handler xu ly xong, cap nhat ket qua vao ProcessedData.
        return handler_result

    def _process_handler(
        self,
        data: ProcessedData,
        df: pd.DataFrame,
    ) -> ProcessedData:
        grouped_df1 = (
            df.groupby("importer_address_vn")["buyer_name"]
            .agg(
                buyer_set=lambda series: set(
                    buyer
                    for buyer in series.dropna()
                    if str(buyer).strip()
                ),
                buyer_count=lambda series: series.nunique(),
            )
            .reset_index()
            .sort_values("buyer_count", ascending=False)
        )

        df = df.merge(
            grouped_df1[
                ["importer_address_vn", "buyer_count"]
            ],
            on="importer_address_vn",
            how="left",
        )
        # Statistics
        processing_dict = {
            "group_buyer_by_address": {
                "one_address_many_buyers": int(
                    (grouped_df1["buyer_count"] > 1).sum()
                )
            }
        }
        structured_data = dict(data.structured_data)
        structured_data["dataframe"] = df
        processing_step = dict(structured_data.get("processing_step", {}))
        processing_step["group_buyer_by_address"] = processing_dict[
            "group_buyer_by_address"
        ]
        structured_data["processing_step"] = processing_step

        return data.model_copy(
            update={
                "structured_data": structured_data,
                "status": ProcessingStatus.PROCESSING,
                "processing_steps": data.processing_steps + [processing_dict],
            }
        )
