-- Chạy tự động khi postgres container khởi động lần đầu.
-- Tạo database airflow (metadata) và data_ingestion (app data).

-- Tạo airflow DB nếu chưa có
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')
\gexec

GRANT ALL PRIVILEGES ON DATABASE airflow TO stsbeyond;

-- Tạo data_ingestion DB nếu chưa có
SELECT 'CREATE DATABASE data_ingestion'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'data_ingestion')
\gexec

GRANT ALL PRIVILEGES ON DATABASE data_ingestion TO stsbeyond;
ALTER DATABASE data_ingestion SET search_path TO bronze;

-- Tạo bảng hs_raw_data trong data_ingestion DB
\c data_ingestion

CREATE SCHEMA IF NOT EXISTS bronze;
ALTER SCHEMA bronze OWNER TO stsbeyond;
GRANT USAGE, CREATE ON SCHEMA bronze TO stsbeyond;

SET search_path TO bronze;

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA bronze;

CREATE TABLE IF NOT EXISTS bronze.hs_raw_data (
	id uuid DEFAULT gen_random_uuid() NOT NULL,
	declaration_number text NULL,
	transaction_date text NULL,
	hs_code text NULL,
	product_description text NULL,
	product_description_en text NULL,
	supplier_name text NULL,
	buyer_name text NULL,
	quantity float8 NULL,
	quantity_unit text NULL,
	unit_price_usd float8 NULL,
	unit_price_foreign_currency float8 NULL,
	total_price_foreign_currency float8 NULL,
	total_amount_usd float8 NULL,
	exchange_rate float8 NULL,
	incoterms text NULL,
	payment_method text NULL,
	import_country text NULL,
	transport_mode text NULL,
	country_of_origin text NULL,
	customs_branch_code text NULL,
	customs_branch_name text NULL,
	bill_id int8 NULL,
	buyer_country text NULL,
	customs_branch_code_secondary text NULL,
	"date" text NULL,
	exporter_country text NULL,
	foreign_currency text NULL,
	importer_address_vn text NULL,
	importer_name_en text NULL,
	importer_tel text NULL,
	import_type text NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	need_check int4 NULL,
	data_source varchar NULL,
	mongo_file_id varchar NULL,
	CONSTRAINT hs_raw_data_pkey PRIMARY KEY (id)
);
