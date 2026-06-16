"""Validation handler — verifies data integrity."""

from pathlib import Path
from typing import Any
from datetime import datetime

from data_processing.domain.models.processed_data import ProcessedData, ProcessingStatus
from data_processing.domain.models.base_handler import BaseProcessingHandler
from shared.utils.logging import info
import pandas as pd

COLUMN_IMP_MAPPING = {
    "Declaration No": "declaration_number",
    "Transaction Date": "transaction_date",
    "HS Code": "hs_code",
    "Product Description": "product_description",
    "Product Desc(EN)": "product_description_en",
    "Supplier": "supplier_name",
    "Buyer": "buyer_name",
    "quantity": "quantity",
    "Quantity unit": "quantity_unit",
    "Unit Price(USD)": "unit_price_usd",
    "Unit Price(Currency)": "unit_price_foreign_currency",
    "Total Price(Currency)": "total_price_foreign_currency",
    "Amount": "total_amount_usd",
    "Exchange Rate": "exchange_rate",
    "Incoterms": "incoterms",
    "Payment Method": "payment_method",
    "Import Country": "import_country",
    "Mode of Transport": "transport_mode",
    "Country of Origin": "country_of_origin",
    "Customs Br Code": "customs_branch_code",
    "Customs Br Name": "customs_branch_name",
    "bill_id": "bill_id",
    "buyer_country": "buyer_country",
    "customs_branch_code_2": "customs_branch_code_secondary",
    "date": "date",
    "exporter_country": "exporter_country",
    "foreign_currency": "foreign_currency",
    "importer_address_vn": "importer_address_vn",
    "importer_name_en": "importer_name_en",
    "importer_tel": "importer_tel",
    "type_of_import": "import_type",
}

COLUMN_TYPES = {
    "declaration_number": "int",
    "transaction_date": "str",
    "hs_code": "int",
    "product_description": "str",
    "product_description_en": "str",
    "supplier_name": "str",
    "buyer_name": "str",
    "quantity": "float64",
    "quantity_unit": "str",
    "unit_price_usd": "float64",
    "unit_price_foreign_currency": "float64",
    "total_price_foreign_currency": "float64",
    "total_amount_usd": "float64",
    "exchange_rate": "float",
    "incoterms": "str",
    "payment_method": "str",
    "import_country": "str",
    "transport_mode": "str",
    "country_of_origin": "str",
    "customs_branch_code": "str",   
    "customs_branch_name": "str",
    "bill_id": "int",
    "buyer_country": "str",
    "customs_branch_code_secondary": "str",
    "date": "str",
    "exporter_country": "str",
    "foreign_currency": "str",
    "importer_address_vn": "str",
    "importer_name_en": "str",
    "importer_tel": "str",
    "import_type": "str",
}


class ValidationHandler(BaseProcessingHandler):
    """
    Step 1: Validates raw data for completeness and correctness.
    Checks required fields and basic data type constraints.
    """

    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Nhận data , kiẻm tra xem file_path và file_id có None or "" không ,nếu có thì trả về None,
        nếu không thì gọi self._process_handler()

        Args:
            data: Data to validate

        Returns:
            Updated data with validation results
        """
        # Step 1: Validate file_id va file_path truoc khi doc file.
        info("ValidationHandler Step 1: validating file_id and file_path")
        file_path = self._get_file_path(data)
        if not data.file_id or not file_path:
            info("ValidationHandler Step 1 failed: file_id or file_path is empty")
            return self._fail(
                data=data,
                processing_step={
                    "missing_columns": [],
                    "wrong_type_columns": {},
                    "error": "file_id or file_path is empty",
                },
            )

        # Step 2: Tao params can thiet, sau do chuyen xuong _process_handler.
        info("ValidationHandler Step 2: preparing params for validation handler")
        params = {
            "data": data,
            "file_path": Path(file_path),
            "column_types": COLUMN_TYPES,
        }
        return self._process_handler(**params)

    def _process_handler(
        self,
        data: ProcessedData,
        file_path: Path,
        column_types: dict[str, str],
    ) -> ProcessedData:
        # Step 3: Doc file theo dinh dang file bang pandas read_* tuong ung.
        info(f"ValidationHandler Step 3: reading file {file_path}")
        try:
            df:pd.DataFrame = self._read_file(file_path)
        except Exception as exc:
            info(f"ValidationHandler Step 3 failed: read file failed: {exc}")
            return self._fail(
                data=data,
                processing_step={
                    "missing_columns": [],
                    "wrong_type_columns": {},
                    "error": f"read file failed: {exc}",
                },
            )
        # Step 3.5 : mapping tên cột
        info("ValidationHandler Step 3.5: mapping column names")
        df = df.rename(columns=COLUMN_IMP_MAPPING)
        
        # Step 4: Lay danh sach cot va kiem tra cot bat buoc co bi thieu khong.
        info("ValidationHandler Step 4: checking required columns")
        missing_columns = [
            column for column in column_types.keys() if column not in df.columns
        ]
        info("create df_mapped")
        mapped_columns = [
            column for column in COLUMN_IMP_MAPPING.values() if column in df.columns
        ]
        df_mapped = df[mapped_columns]
        # Step 5: Kiem tra kieu du lieu cua tung cot dang ton tai.
        info("ValidationHandler Step 5: checking column data types")
        wrong_type_of_columns = self._get_wrong_type_columns(df_mapped, column_types)

        # Step 5.5: Neu thieu cot hoac sai kieu du lieu thi tra ket qua ngay lap tuc.
        if missing_columns or wrong_type_of_columns:
            info(
                "ValidationHandler Step 5.5 failed: "
                f"missing columns={missing_columns}, "
                f"wrong type columns={wrong_type_of_columns}"
            )
            return self._fail(
                data=data,
                processing_step={
                    "missing_columns": missing_columns,
                    "wrong_type_columns": wrong_type_of_columns,
                },
                df=df_mapped,
            )

        # Step 6: Neu schema hop le thi kiem tra ty le null cua tung cot.
        info("ValidationHandler Step 6: checking missing value ratio")
        missing_value_result = self._get_missing_value_result(df_mapped)
        if missing_value_result:
            info(
                "ValidationHandler Step 6 warning: "
                f"columns exceed missing value threshold={missing_value_result}"
            )


        # Step 6.5: Schema hop le thi cap nhat validation_handler = Success.
        # Missing-value threshold is recorded as metadata, not treated as a hard failure.
        info("ValidationHandler Step 6.5: validation success")
        structured_data = dict(data.structured_data)
        structured_data["dataframe"] = df_mapped
        validation_result = {"status": "Success"}
        if missing_value_result:
            validation_result["missing_value_warning"] = missing_value_result

        processing_step = dict(structured_data.get("processing_step", {}))
        processing_step["validation_handler"] = validation_result
        structured_data["processing_step"] = processing_step

        return data.model_copy(
            update={
                "structured_data": structured_data,
                "is_valid": True,
                "status": ProcessingStatus.PROCESSING,
                "processing_steps": data.processing_steps
                + [{"validation_handler": validation_result}],
            }
        )

    def _get_file_path(self, data: ProcessedData) -> str | None:
        file_path = data.structured_data.get("file_path")
        if file_path:
            return str(file_path)

        local_path = data.structured_data.get("local_path")
        if local_path:
            return str(local_path)
        
        return None

    def _read_file(self, file_path: Path) -> Any:
        extension = file_path.suffix.lower()

        if extension == ".csv":
            return pd.read_csv(file_path)
        if extension == ".json":
            return pd.read_json(file_path)
        if extension in {".xlsx", ".xls"}:
            return pd.read_excel(file_path)
        if extension == ".parquet":
            return pd.read_parquet(file_path)

        raise ValueError(f"unsupported file format: {extension}")

    def _get_wrong_type_columns(
        self,
        df: Any,
        column_types: dict[str, str],
    ) -> dict[str, dict[str, str]]:
        wrong_type_of_columns = {}

        for column, expected_type in column_types.items():
            if column not in df.columns:
                continue

            if not self._is_expected_type(df[column], expected_type):
                wrong_type_of_columns[column] = {
                    "expect": expected_type,
                    "actual": str(df[column].dtype),
                }

        return wrong_type_of_columns

    def _is_expected_type(self, series: Any, expected_type: str) -> bool:
        dtype = series.dtype
        expected_type = expected_type.strip().lower()

        if expected_type == "int":
            return pd.api.types.is_integer_dtype(dtype)

        if expected_type.__contains__("float"):
            return pd.api.types.is_float_dtype(dtype)

        if expected_type == "str":
            if pd.api.types.is_string_dtype(dtype):
                return True
            if pd.api.types.is_object_dtype(dtype):
                non_null_values = series.dropna()
                return non_null_values.map(lambda value: isinstance(value, str)).all()
            return False

        if expected_type == "object":
            return pd.api.types.is_object_dtype(dtype)

        return False

    def _get_missing_value_result(self, df: Any) -> dict[str, dict[str, float | int]]:
        total_rows = len(df)
        if total_rows == 0:
            return {}

        missing_value_result = {}
        for column in df.columns:
            missing_count = int(df[column].isna().sum())
            missing_ratio = missing_count / total_rows
            if missing_ratio > 0.8:
                missing_value_result[column] = {
                    "col_name": column,
                    "missing_value": missing_ratio,
                    "missing_count": missing_count,
                    "total": total_rows,
                }

        return missing_value_result

    def _fail(
        self,
        data: ProcessedData,
        processing_step: dict[str, Any],
        df: Any | None = None,
    ) -> ProcessedData:
        structured_data = dict(data.structured_data)
        if df is not None:
            structured_data["dataframe"] = df

        return data.model_copy(
            update={
                "structured_data": structured_data,
                "is_valid": False,
                "status": ProcessingStatus.FAILED,
                "errors": data.errors + [str(processing_step)],
                "processing_steps": data.processing_steps + [processing_step],
            }
        )

   
