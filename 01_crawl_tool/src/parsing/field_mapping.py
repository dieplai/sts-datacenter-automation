"""API-key ↔ display-name mapping for transaction records.

FIELD_MAPPING    canonical: internal key → CSV/Excel column header
ALIASES          old CSV header (case-insensitive) → internal key, so we can
                 resume into a file whose columns were named under an older
                 version of the mapping
update_mapping_from_server
                 merge server-provided `title[]` entries into ALIASES so the
                 scraper keeps working when 52wmb renames a column
"""

# Primary source of truth for NEW files. Keys are API JSON field names,
# values are the column headers we write to CSV/Excel.
FIELD_MAPPING = {
    # Metadata
    'segment': 'segment',
    'page': 'page',
    'stt': 'stt',

    # Transaction ID & Date
    'date': 'Transaction Date',
    'bill_no': 'Declaration No',
    'bill_id': 'Bill of Lading ID',
    'export_declaration_number': 'Export serial number',
    'id': 'Unique identification number',
    'type_of_export_code': 'Type of Export Code',
    'type_of_export_name': 'Type of Export Name',

    # Product Info
    'hs': 'HS Code',
    'descript': 'Product Description',
    'product_desc_en': 'Product Desc(EN)',

    # Buyer Info
    'buyer': 'Buyer',
    'buyer_country': 'Import Country',
    'importer_address_1': 'Buyer Address 1',
    'importer_address_2': 'Buyer Address 2',
    'importer_address_3': 'Buyer Address 3',
    'importer_address_4': 'Buyer Address 4',
    'importer_address_5': 'Buyer Address 5',
    'importer_address_6': 'Buyer Address 6',
    'importer_address_7': 'Buyer Address 7',
    'importer_address_8': 'Buyer Address 8',
    'importer_code': 'Company tax number',
    'importer_id': 'Importer ID',
    'importer_tel': 'Buyer Tel',
    'buyer_address': "Buyer's address",

    # Supplier Info
    'seller': 'Supplier',
    'exporter_id': 'Supplier ID',
    'exporter_name_en': 'Supplier(EN)',
    'exporter_address_vn': 'Supplier Address(VN)',
    'exporter_tel': 'Supplier Tel',
    'exporter_address': 'Supplier Address',
    'exporter_telephone_number': "Supplier's phone number",
    'seller_country': 'Supply Country',

    # Shipping & Logistics
    'trans': 'Mode of Transport',
    'incoterms': 'Incoterms',
    'origin_country': 'Country of Origin',
    'customs_br_code_1': 'Customs Br Code',
    'customs_br_code_2': 'Customs Br Name',
    'customs_branch_name': 'Customs Branch Name(VN)',
    'payment_method': 'Payment Method',
    'buyer_port': 'Import port',
    'seller_port': 'Port of departure',
    'carrier': 'Carrier',
    'flight_voyage_number': 'Flight/voyage number',

    # Financial Info
    'qty': 'quantity',
    'qty_unit': 'Quantity unit',
    'unit_name': 'Unit',
    'uusd': 'Unit Price(USD)',
    'unit_value_in_fc': 'Unit Price(Currency)',
    'total_value_in_fc': 'Total Price(Currency)',
    'amount': 'Amount',
    'foreign_currency': 'Currency',
    'exchange_rate': 'Exchange Rate',
    'amount_currency': 'Currency',
}

# Maps display names found in older CSVs to API keys. Used for robust
# mapping when resuming a session whose CSV was written under a previous
# header scheme.
ALIASES = {
    'declaration no': 'bill_no',
    'declaration number': 'bill_no',
    'bill of lading number': 'bill_no',
    'transaction date': 'date',
    'hs code': 'hs',
    'product description': 'descript',
    'product desc': 'descript',
    'export serial number': 'export_declaration_number',
    'unique identification number': 'id',
    'unit price(usd)': 'uusd',
    'unit price': 'uusd',
    'total amount(usd)': 'amount',
    'total amount': 'amount',
    'quantity': 'qty',
    'quantity unit': 'qty_unit',
    'currency': 'amount_currency',
    'buyer address': 'buyer_address',
    'supplier address': 'exporter_address_vn',
    'transportation mode': 'trans',
    'mode of transport': 'trans',
    'trade mode': 'incoterms',
    'customs br name': 'customs_br_code_2',
    'customs name': 'customs_br_code_2',
    'importing country': 'buyer_country',
    'exchange rate': 'exchange_rate',

    # Variants removed from duplicate FIELD_MAPPING values:
    'transaction_date': 'date',
    'billid': 'bill_id',
    'declaration_number': 'export_declaration_number',
    'supplier': 'seller',
    'total_value': 'total_value_in_fc',
    'price': 'unit_value_in_fc',
}


def update_mapping_from_server(server_titles, aliases=None):
    """Merge server-provided column definitions into the ALIASES dict.

    Each `title` row looks like `{"field_title": "bill_no", "field_des":
    "Declaration No"}`. We add `field_des.lower() → field_title` so that
    an existing CSV whose header is `"Declaration No"` can still be
    resumed by the new run.

    Mutates `aliases` in place (defaults to the module-level ALIASES).
    """
    if aliases is None:
        aliases = ALIASES
    try:
        for item in server_titles:
            field_title = item.get('field_title')
            field_des = item.get('field_des')
            if not field_title or not field_des:
                continue
            aliases[field_des.lower().strip()] = field_title
    except Exception:
        # Never fail the scrape just because a server row is malformed.
        pass
    return aliases
