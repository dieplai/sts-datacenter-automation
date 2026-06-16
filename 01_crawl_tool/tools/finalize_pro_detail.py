"""
Pro 2026 Data Finalization Tool (Market Analysis - Detail Mode)

Specialized data cleaning, mapping, and conversion pipeline for Pro 2026 Detail data.
Features:
- Fixed Canonical Order based on core_pro_detail alignment.
- Mode Selector: Clean, Reorder, Map Columns, Convert Format.
- Automatic filtering for 'detail_' prefixed files.
- Duplicate removal.
- Empty column cleanup.
- Dynamic column merging for unmapped API fields.

Usage:
    python tools/finalize_pro_detail.py
"""

import pandas as pd
import os
import csv
import re
from datetime import datetime

# ============================================================
# CANONICAL COLUMN ORDER
# ============================================================
DETAIL_DISPLAY_ORDER = [
    # ===== METADATA =====
    'segment', 'page', 'stt',
    
    # ===== TRANSACTION ID =====
    'Declaration No',
    'Transaction Date',
    'Bill of Lading ID',
    'Unique Identification Number',
    'Export Serial Number',
    
    # ===== PRODUCT INFO =====
    'HS Code',
    'Product Description',
    'Product Desc (EN)',
    
    # ===== SUPPLIER INFO (Vietnamese Exporter) =====
    'Supplier',
    'Supplier (EN)',
    'Supplier ID',
    'Supplier Address (VN)',
    "Supplier's Phone Number",
    'Supply Country',
    
    # ===== BUYER INFO (Foreign Importer) =====
    'Buyer',
    'Buyer (EN)',
    "Buyer's Address",
    'Buyer Address 1', 'Buyer Address 2', 'Buyer Address 3', 'Buyer Address 4',
    'Buyer Address 5', 'Buyer Address 6', 'Buyer Address 7', 'Buyer Address 8',
    'Buyer Tel',
    'Importer ID',
    'Company Tax Number',
    
    # ===== COMPANY INFO =====
    'Company Address',
    'Company CEO',
    'Company Email',
    'Company Tel',
    'Company Zip',
    
    # ===== FINANCIAL INFO =====
    'Qty',
    'Quantity Unit',
    'Unit',
    'Weight',
    'Weight Unit',
    'Unit Price (USD)',
    'Unit Price (Currency)',
    'Total Amount (USD)',
    'Total Price (Currency)',
    'CIF Amount',
    'FOB Amount',
    'Import Tax Amount',
    'Currency',
    'Exchange Rate',
    
    # ===== TRADE & LOGISTICS =====
    'Trade Mode',
    'Destination Country',
    'Importing Country',
    'Country of Origin',
    'Transportation Mode',
    'Import Port',
    'Port of Departure',
    'Carrier',
    'Flight/Voyage Number',
    
    # ===== CUSTOMS INFO =====
    'Customs Br Code',
    'Customs Br Name',
    'Customs Branch Name (VN)',
    'VN Port Customs Warehouse',
    'Custom',
    'Payment Method',
    'Type of Export Code',
    'Type of Export Name',
    'Type of Import Code',
]

# ============================================================
# FIELD MAPPING
# ============================================================
FIELD_MAPPING = {
    # ===== METADATA =====
    'segment': 'segment',
    'page': 'page',
    'stt': 'stt',
    
    # ===== TRANSACTION ID & DATE =====
    'date': 'Transaction Date',
    'bill_no': 'Declaration No',
    'billid': 'Bill of Lading ID',
    'bill_id': 'Bill of Lading ID',  # Internal numeric ID, NOT Declaration No
    'export_declaration_number': 'Export Serial Number',
    'export_serial_number': 'Export Serial Number',
    'id': 'Unique Identification Number',
    'unique_identification_number': 'Unique Identification Number',
    'type_of_export_code': 'Type of Export Code',
    'type_of_export_name': 'Type of Export Name',
    'type_of_import': 'Type of Import Code',
    
    # ===== PRODUCT INFO =====
    'hs': 'HS Code',
    'descript': 'Product Description',
    'product_desc_en': 'Product Desc (EN)',
    'product_desc(en)': 'Product Desc (EN)',  # NEW
    
    # ===== BUYER INFO =====
    'buyer': 'Buyer',
    'buyer_country': 'Destination Country',
    'import_country': 'Importing Country',
    'importing_country': 'Importing Country',  # NEW
    'chinese_importer_address': "Buyer's Address",
    'importer_address_vn': "Buyer's Address",
    'buyer_address(vn)': "Buyer's Address",  # NEW
    'importer_address_1': 'Buyer Address 1',
    'buyer_address_line_1': 'Buyer Address 1',  # NEW
    'importer_address_2': 'Buyer Address 2',
    'buyer_address_line_2': 'Buyer Address 2',  # NEW
    'importer_address_3': 'Buyer Address 3',
    'buyer_address_line_3': 'Buyer Address 3',  # NEW
    'importer_address_4': 'Buyer Address 4',
    'buyer_address_line_4': 'Buyer Address 4',  # NEW
    'importer_address_5': 'Buyer Address 5',
    'buyer_address_line_5': 'Buyer Address 5',  # NEW
    'importer_address_6': 'Buyer Address 6',
    'buyer_address_line_6': 'Buyer Address 6',  # NEW
    'importer_address_7': 'Buyer Address 7',
    'buyer_address_line_7': 'Buyer Address 7',  # NEW
    'importer_address_8': 'Buyer Address 8',
    'buyer_address_line_8': 'Buyer Address 8',  # NEW
    'importer_code': 'Company Tax Number',
    'importer_id': 'Importer ID',
    'importer_tel': 'Buyer Tel',
    'importer_name_en': 'Buyer (EN)',
    'buyer_name(en)': 'Buyer (EN)',  # NEW
    'buyer_address': "Buyer's Address",
    
    # ===== SUPPLIER INFO =====
    'seller': 'Supplier',
    'exporter_id': 'Supplier ID',
    'exporter_name_en': 'Supplier (EN)',
    'exporter_name(en)': 'Supplier (EN)',  # NEW
    'exporter_address_vn': 'Supplier Address (VN)',
    'exporter_address(vn)': 'Supplier Address (VN)',  # NEW
    'vietnam_exporter_address': 'Supplier Address (VN)',
    'exporter_tel': "Supplier's Phone Number",
    'exporter_telephone_number': "Supplier's Phone Number",
    'seller_country': 'Supply Country',
    'exporter_country': 'Supply Country',
    'exporter_country_name': 'Supply Country',
    'supply_country': 'Supply Country',  # NEW
    
    # ===== COMPANY INFO =====
    'address': 'Company Address',
    'ceo': 'Company CEO',
    'email': 'Company Email',
    'tel': 'Company Tel',
    'zip': 'Company Zip',
    
    # ===== SHIPPING & LOGISTICS =====
    'trans': 'Transportation Mode',
    'mode_of_export': 'Transportation Mode',
    'mode_of_transport': 'Transportation Mode',
    'transportation_mode': 'Transportation Mode',  # NEW
    'incoterms': 'Trade Mode',
    'trade_mode': 'Trade Mode',  # NEW
    'origin_country': 'Country of Origin',
    'country_of_origin': 'Country of Origin',  # NEW
    'customs_code': 'Customs Code',
    'customs_name': 'Customs Name',
    'name_of_customs': 'Customs Name',
    'customs_br_code': 'Customs Br Code',
    'customs_br_code_1': 'Customs Br Code',  # Same as Customs Br Code
    'customs_branch_code_1': 'Customs Br Code',  # Same as Customs Br Code
    'customs_br_code_2': 'Customs Br Name',
    'customs_branch_code_2': 'Customs Br Name',
    'customs_br_name': 'Customs Br Name',
    'customs_branch_name': 'Customs Branch Name',
    'customs_branch_name(vn)': 'Customs Branch Name (VN)',  # NEW
    'vn_port_customs_warehouse_name': 'VN Port Customs Warehouse',
    'custom': 'Custom',
    'payment_method': 'Payment Method',
    'import_port': 'Import Port',
    'buyer_port': 'Import Port',
    'port_of_departure': 'Port of Departure',
    'seller_port': 'Port of Departure',
    'carrier': 'Carrier',
    'flight_voyage_number': 'Flight/Voyage Number',
    'flight/voyage_number': 'Flight/Voyage Number',  # NEW
    'flight_vessel_code': 'Flight/Voyage Number',
    
    # ===== FINANCIAL INFO =====
    'quantity': 'Qty',
    'qty': 'Qty',
    'qty_unit': 'Quantity Unit',
    'quantity_unit': 'Quantity Unit',
    'unit': 'Unit',
    'unit_name': 'Unit',
    'uusd': 'Unit Price (USD)',
    'unit_price_usd': 'Unit Price (USD)',
    'unit_price(usd)': 'Unit Price (USD)',  # NEW
    'price': 'Unit Price (USD)',
    'unit_value_in_fc': 'Unit Price (Currency)',
    'unit_price_currency': 'Unit Price (Currency)',
    'unit_price(currency)': 'Unit Price (Currency)',  # NEW
    'total_price_currency': 'Total Price (Currency)',
    'total_price(currency)': 'Total Price (Currency)',  # NEW
    'total_value_in_fc': 'Total Price (Currency)',
    'total_value': 'Total Amount (USD)',
    'amount': 'Total Amount (USD)',
    'currency': 'Currency',
    'foreign_currency': 'Currency',
    'amount_currency': 'Currency',
    'exchange_rate': 'Exchange Rate',
    'duty_exchange_rate': 'Exchange Rate',
    'vnd_exchange_rate': 'Exchange Rate',
    'cif_amount': 'CIF Amount',
    'fob_amount': 'FOB Amount',
    'import_tax_amount': 'Import Tax Amount',
    'weight': 'Weight',
    'weight_unit': 'Weight Unit',
    'address_of_exporter': 'Supplier Address (VN)',
    'declaration_number': 'Declaration No',
    'importer_telephone_number': 'Buyer Tel',
    'vietnam_importer_address': "Buyer's Address",
    'importer_std': 'Buyer (EN)',
    'list_date': 'Transaction Date',  # Duplicate of Transaction Date
    'source_file': 'source_file',
}

# ============================================================
# COLUMN CONSOLIDATION
# ============================================================
COLUMN_CONSOLIDATION = [
    ('Unit Price (Currency)', 'Unit Price (USD)'),
    ('Total Price (Currency)', 'Total Amount (USD)'),
]

def normalize(s):
    """Normalize string for comparison"""
    if not s: return ""
    return "".join(c.lower() for c in str(s) if c.isalnum())

def are_values_equivalent(v1, v2):
    """Check if two values are effectively the same (ignoring case, punctuation, common aliases)."""
    # 0. Numeric (Float) comparison
    try:
        f1 = float(str(v1).strip().replace(',', ''))
        f2 = float(str(v2).strip().replace(',', ''))
        import math
        if math.isclose(f1, f2, rel_tol=1e-3, abs_tol=1e-3):
            return True
    except (ValueError, TypeError):
        pass

    s1 = str(v1).strip().lower()
    s2 = str(v2).strip().lower()
    
    # 1. Exact match
    if s1 == s2: return True
    
    # 2. Subset match
    if s1 in s2 or s2 in s1: return True
    
    # 3. Normalized match (remove punctuation/spaces)
    n1 = normalize(v1)
    n2 = normalize(v2)
    if n1 == n2: return True
    
    # 4. High similarity ratio (>85% similar = probably same entity)
    # This handles cases like "Advancer Denim Co.Ltd." vs "advance denim co., ltd"
    if len(n1) > 5 and len(n2) > 5:
        # Simple Jaccard-like similarity based on character sets
        set1 = set(n1)
        set2 = set(n2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        if union > 0 and (intersection / union) > 0.8:
            # Additionally check if most characters are shared
            longer = n1 if len(n1) > len(n2) else n2
            shorter = n1 if len(n1) <= len(n2) else n2
            match_count = sum(1 for c in shorter if c in longer)
            if match_count / len(shorter) > 0.85:
                return True
    
    # 5. Known aliases
    aliases = [
        ('viet nam', 'vietnam'),
        ('limited', 'ltd'),
        ('company', 'co'),
        ('corporation', 'corp'),
        ('incorporated', 'inc')
    ]
    
    for a, b in aliases:
        if (a in s1 and b in s2) or (b in s1 and a in s2):
            # Replace alias and check again
            t1 = s1.replace(a, b)
            t2 = s2.replace(a, b)
            if normalize(t1) == normalize(t2): return True
            
    return False

def is_value_prettier(v1, v2):
    """
    Compare two equivalent values and return which one is 'prettier'.
    Returns: 1 if v1 is prettier, 2 if v2 is prettier, 0 if equal.
    
    Simple check: Proper case (first letter uppercase) is prettier.
    """
    s1 = str(v1).strip()
    s2 = str(v2).strip()
    
    if s1 == s2: return 0
    
    # Simple: Proper case wins (first letter uppercase, not all caps)
    s1_proper = len(s1) > 0 and s1[0].isupper() and not s1.isupper()
    s2_proper = len(s2) > 0 and s2[0].isupper() and not s2.isupper()
    
    if s1_proper and not s2_proper: return 1
    if s2_proper and not s1_proper: return 2
    
    return 0

def clean_duplicate_rows(df):
    """Remove duplicates while ignoring metadata."""
    print("\n🧹 Removing duplicate rows...")
    original_count = len(df)
    ignore_cols = ['segment', 'page', 'stt']
    check_cols = [col for col in df.columns if col not in ignore_cols]
    
    duplicates_mask = df.duplicated(subset=check_cols, keep='first')
    df_clean = df[~duplicates_mask].copy()
    
    removed = original_count - len(df_clean)
    print(f"   ✅ Removed {removed:,} duplicates ({original_count:,} -> {len(df_clean):,})")
    return df_clean

def map_and_merge_columns(df):
    """Merge unmapped API columns with smart quality-based selection."""
    print("\n🔗 Mapping and merging columns with smart filtering...")
    
    # ============================================================
    # PRE-PROCESSING: Clean special columns
    # ============================================================
    # bill_id sometimes has negative values like "-943890253" 
    # but should be "943890253" to match Bill of Lading ID
    if 'bill_id' in df.columns:
        df['bill_id'] = df['bill_id'].apply(
            lambda x: str(x).lstrip('-') if pd.notna(x) and str(x).startswith('-') else x
        )
        print("   🧹 Cleaned 'bill_id': removed negative signs")
    
    norm_to_canonical = {}
    for k, v in FIELD_MAPPING.items():
        norm_to_canonical[normalize(k)] = v
        norm_to_canonical[normalize(v)] = v
    
    columns_to_drop = []
    merge_count = 0
    
    for col in df.columns:
        norm_col = normalize(col)
        if norm_col in norm_to_canonical:
            canonical = norm_to_canonical[norm_col]
            if col == canonical: continue
            
            if canonical in df.columns:
                # ============================================================
                # SMART QUALITY ANALYSIS & FILTERING
                # ============================================================
                
                # 1. Coverage statistics
                null_count_src = df[col].isna().sum()
                null_count_tgt = df[canonical].isna().sum()
                coverage_src = (len(df) - null_count_src) / len(df) * 100
                coverage_tgt = (len(df) - null_count_tgt) / len(df) * 100
                
                # 2. Find sample for comparison
                sample_idx = None
                for idx in range(min(50, len(df))):
                    if pd.notna(df[col].iloc[idx]) or pd.notna(df[canonical].iloc[idx]):
                        sample_idx = idx
                        break
                
                # 3. Value comparison
                values_differ = False
                if sample_idx is not None:
                    val_src = df[col].iloc[sample_idx]
                    val_tgt = df[canonical].iloc[sample_idx]
                    
                    if pd.notna(val_src) and pd.notna(val_tgt):
                        if str(val_src).strip() != str(val_tgt).strip():
                            values_differ = True
                
                # ============================================================
                # SMART DECISION: Choose better quality column WITH CONFLIC CHECK
                # ============================================================
                
                # Check for conflicts FIRST
                if values_differ and sample_idx is not None:
                     val_src = df[col].iloc[sample_idx]
                     val_tgt = df[canonical].iloc[sample_idx]
                     
                     if not are_values_equivalent(val_src, val_tgt):
                         str_src = str(val_src).strip()
                         str_tgt = str(val_tgt).strip()
                         src_digits = any(c.isdigit() for c in str_src)
                         tgt_digits = any(c.isdigit() for c in str_tgt)
                         
                         if src_digits and not tgt_digits:
                             print(f"   💡 Tự động gộp: Chọn '{col}' thay vì '{canonical}' (chứa số hiệu chính xác)")
                             df[canonical] = df[col] # Ép ghi đè source sang canonical
                         elif tgt_digits and not src_digits:
                             print(f"   💡 Tự động gộp: Giữ '{canonical}' thay vì '{col}' (chứa số hiệu chính xác)")
                         elif len(str_src) > len(str_tgt) + 5:
                             print(f"   💡 Tự động gộp: Chọn '{col}' thay vì '{canonical}' (thông tin chi tiết hơn)")
                             df[canonical] = df[col]
                         elif len(str_tgt) > len(str_src) + 5:
                             print(f"   💡 Tự động gộp: Giữ '{canonical}' thay vì '{col}' (thông tin chi tiết hơn)")
                         else:
                             print(f"   ⚠️  CONFLICT DETECTED: '{col}' vs '{canonical}'")
                             print(f"      Val 1: '{str_src[:40]}'")
                             print(f"      Val 2: '{str_tgt[:40]}'")
                             print(f"      🚫  SKIPPING MERGE to preserve data integrity.")
                             
                             new_col_name = f"{canonical}_CONFLICT_{col}"
                             counter = 1
                             while new_col_name in df.columns:
                                 new_col_name = f"{canonical}_CONFLICT_{col}_{counter}"
                                 counter += 1
                             df.rename(columns={col: new_col_name}, inplace=True)
                             print(f"      👉 Renamed '{col}' to '{new_col_name}'")
                             continue

                # If source has significantly better coverage (>10% difference), prefer it
                coverage_diff = coverage_src - coverage_tgt
                
                if coverage_diff > 10:
                    # SOURCE IS BETTER - Keep source, drop canonical, rename source
                    print(f"   🎯 '{col}' has BETTER coverage ({coverage_src:.1f}% vs {coverage_tgt:.1f}%)")
                    
                    # Fill source from canonical (reverse merge)
                    mask = (df[col].isna() | (df[col] == '') | (df[col] == 'nan'))
                    fillable = (mask & df[canonical].notna()).sum()
                    
                    if fillable > 0:
                        df.loc[mask, col] = df.loc[mask, canonical]
                        print(f"   📋 Merged '{canonical}' → '{col}' (filled {fillable:,} values)")
                    
                    # Drop canonical, rename source to canonical
                    df.drop(columns=[canonical], inplace=True)
                    df.rename(columns={col: canonical}, inplace=True)
                    print(f"   ✅ Kept better quality column as '{canonical}'")
                    
                else:
                    # CANONICAL IS BETTER OR SIMILAR - Standard merge
                    if coverage_diff < -10:
                        print(f"   🎯 '{canonical}' has BETTER coverage ({coverage_tgt:.1f}% vs {coverage_src:.1f}%)")
                    
                    # Smart merge: Fill empty AND prefer prettier values when both exist
                    empty_mask = (df[canonical].isna() | (df[canonical] == '') | (df[canonical] == 'nan'))
                    fillable = (empty_mask & df[col].notna()).sum()
                    
                    # Fill empty values first
                    if fillable > 0:
                        df.loc[empty_mask, canonical] = df.loc[empty_mask, col]
                    
                    # For rows where BOTH have values, prefer the prettier one.
                    # Vectorized: src is "proper case" (first char upper, not all-caps)
                    # and canonical is NOT → upgrade canonical to src.
                    both_have_values = df[col].notna() & df[canonical].notna() & (df[col] != '') & (df[canonical] != '')
                    prettier_upgraded = 0

                    if both_have_values.any():
                        src_s = df.loc[both_have_values, col].astype(str).str.strip()
                        tgt_s = df.loc[both_have_values, canonical].astype(str).str.strip()
                        src_proper = src_s.str[:1].str.isupper() & ~src_s.str.isupper()
                        tgt_proper = tgt_s.str[:1].str.isupper() & ~tgt_s.str.isupper()
                        upgrade_mask = src_proper & ~tgt_proper
                        if upgrade_mask.any():
                            df.loc[upgrade_mask[upgrade_mask].index, canonical] = \
                                src_s[upgrade_mask].values
                            prettier_upgraded = int(upgrade_mask.sum())
                    
                    final_coverage = ((len(df) - df[canonical].isna().sum()) / len(df)) * 100
                    
                    if prettier_upgraded > 0:
                        print(f"   📋 Merged '{col}' → '{canonical}' (filled {fillable:,}, upgraded {prettier_upgraded:,} prettier values)")
                    elif fillable > 0:
                        print(f"   📋 Merged '{col}' → '{canonical}' (filled {fillable:,} values, {coverage_src:.1f}% + {coverage_tgt:.1f}% → {final_coverage:.1f}%)")
                    else:
                        print(f"   📋 Merged '{col}' → '{canonical}' (coverage: {coverage_src:.1f}% + {coverage_tgt:.1f}%)")
                    
                    columns_to_drop.append(col)
                
                merge_count += 1
                
            else:
                # Canonical doesn't exist, simple rename
                df.rename(columns={col: canonical}, inplace=True)
                print(f"   📋 Renamed '{col}' → '{canonical}'")
                merge_count += 1
    
    if columns_to_drop:
        df.drop(columns=columns_to_drop, inplace=True)
    print(f"   ✅ Processed {merge_count} mappings, dropped {len(columns_to_drop)} columns, kept {merge_count - len(columns_to_drop)} better quality columns")
    return df

def consolidate_columns(df):
    """Consolidate semantically equivalent columns."""
    print("\n🔄 Consolidating semantically equivalent columns...")
    consolidation_count = 0
    
    for source_col, target_col in COLUMN_CONSOLIDATION:
        if source_col in df.columns:
            if target_col in df.columns:
                mask = df[target_col].isna() | (df[target_col] == '') | (df[target_col].astype(str) == 'nan')
                source_has_data = ~(df[source_col].isna() | (df[source_col] == '') | (df[source_col].astype(str) == 'nan'))
                rows_to_copy = mask & source_has_data
                copied_count = rows_to_copy.sum()
                if copied_count > 0:
                    df.loc[rows_to_copy, target_col] = df.loc[rows_to_copy, source_col]
                df.drop(columns=[source_col], inplace=True)
                consolidation_count += 1
            else:
                df.rename(columns={source_col: target_col}, inplace=True)
                consolidation_count += 1
    
    print(f"   ✅ Consolidated {consolidation_count} column pairs")

def reorder_columns(df):
    """Align columns with canonical order."""
    print("\n📋 Reordering columns to canonical format...")
    file_cols = list(df.columns)
    ordered = [c for c in DETAIL_DISPLAY_ORDER if c in file_cols]
    extras = sorted([c for c in file_cols if c not in DETAIL_DISPLAY_ORDER])
    final_cols = ordered + extras
    print(f"   📊 Canonical: {len(ordered)}, Extra: {len(extras)}")
    return df[final_cols]

def sort_by_date(df):
    """Sort rows by Transaction Date descending (newest first)."""
    DATE_COL = 'Transaction Date'
    if DATE_COL not in df.columns:
        print("\n📅 Sort: 'Transaction Date' column not found, skipping.")
        return df
    print(f"\n📅 Sorting by '{DATE_COL}' (newest first)...")
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], dayfirst=False, errors='coerce')
    df = df.sort_values(DATE_COL, ascending=False, na_position='last').reset_index(drop=True)
    # Keep display-friendly string format (YYYY-MM-DD)
    df[DATE_COL] = df[DATE_COL].dt.strftime('%Y-%m-%d').where(df[DATE_COL].notna(), other='')
    print(f"   ✅ Sorted {len(df):,} rows by date.")
    return df

def clean_empty_columns(df):
    """Remove ALL columns that are 100% empty."""
    print("\n🗑️  Checking for empty columns...")
    cols_before = len(df.columns)

    # Deduplicate column names first (duplicate names cause df[col] to return
    # a DataFrame instead of a Series, breaking .str accessor).
    # Ignore intentional _CONFLICT_ columns — they are expected extras.
    real_dupes = [
        c for c in df.columns[df.columns.duplicated(keep=False)].unique()
        if '_CONFLICT_' not in str(c)
    ]
    if real_dupes:
        print(f"   ⚠️  Duplicate column names detected, deduplicating: {real_dupes}")
    if df.columns.duplicated().any():
        seen: dict = {}
        new_cols = []
        for col in df.columns:
            if col in seen:
                seen[col] += 1
                new_cols.append(f"{col}.{seen[col]}")
            else:
                seen[col] = 0
                new_cols.append(col)
        df.columns = new_cols

    df.dropna(axis=1, how='all', inplace=True)

    empty_str_cols = []
    for col in df.columns:
        series = df[col]
        # Guard: skip if somehow still a DataFrame (shouldn't happen after dedup)
        if isinstance(series, pd.DataFrame):
            continue
        if (series.astype(str).str.strip() == '').all():
            empty_str_cols.append(col)

    if empty_str_cols:
        df.drop(columns=empty_str_cols, inplace=True)
    removed = cols_before - len(df.columns)
    print(f"   ✅ Deleted {removed} empty columns.")
    return df

def convert_format(input_path, target_format):
    """Convert file between xlsx and csv."""
    print(f"\n🔄 Converting to {target_format.upper()}...")
    ext = os.path.splitext(input_path)[1].lower()
    if ext == '.csv':
        df = pd.read_csv(input_path, encoding='utf-8-sig', low_memory=False)
    else:
        df = pd.read_excel(input_path, engine='openpyxl')
    
    out_dir = os.path.dirname(input_path)
    base_name = os.path.basename(input_path)
    name_no_ext = os.path.splitext(base_name)[0]
    
    if target_format == 'csv':
        out_path = os.path.join(out_dir, name_no_ext + '.csv')
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
    else:
        out_path = os.path.join(out_dir, name_no_ext + '.xlsx')
        df.to_excel(out_path, index=False, engine='openpyxl')
    
    print(f"   ✅ Saved: {out_path}")
    return out_path

# ============================================================
# FILE & PROCESSING UTILS
# ============================================================

def list_files(target_dir=None, skip_filter=False):
    """List all CSV/XLSX files in targeted or default directories."""
    if target_dir:
        search_dirs = [target_dir]
    else:
        search_dirs = ["output/done", "output", "output/intermediate", "."]
        
    all_files = []
    for d in search_dirs:
        if os.path.exists(d):
            # Include all CSV/XLSX
            # If not skip_filter, exclude already finalized/merged ones
            files = []
            for f in os.listdir(d):
                if f.endswith(('.csv', '.xlsx')):
                    if skip_filter or not f.startswith(('final_', 'FINAL_', 'FINALIZED_', 'CLEANED_', 'MAPPED_', 'REORDERED_', 'MERGED_')):
                        files.append(os.path.join(d, f))
                    else:
                        pass # Filtered out
            all_files.extend(files)
        else:
            print(f"   ⚠️ Directory not found: '{d}'")
            
    # Sort by modification time (newest first)
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return all_files

def detect_file_groups(files):
    """Auto-detect file groups based on filename patterns."""
    groups = {
        'by_company': {},
        'by_type': {'import': [], 'export': []},
        'all': files.copy()
    }
    
    for f in files:
        basename = os.path.basename(f).lower()
        match = re.search(r'detail_vietnam_([a-z_]+)_(import|export)', basename)
        if match:
            company = match.group(1).rstrip('_')
            trade_type = match.group(2)
            if company not in groups['by_company']: groups['by_company'][company] = []
            groups['by_company'][company].append(f)
            groups['by_type'][trade_type].append(f)
        else:
            if 'import' in basename: groups['by_type']['import'].append(f)
            elif 'export' in basename: groups['by_type']['export'].append(f)
            
            company_match = re.search(r'(import|export)_([a-z]+)', basename)
            if company_match:
                company = company_match.group(2)
                if company not in groups['by_company']: groups['by_company'][company] = []
                groups['by_company'][company].append(f)
    return groups

def process_single_file(input_path, mode):
    """Process a single file with specified mode."""
    print(f"\n🚀 Processing: {os.path.basename(input_path)}")
    ext = os.path.splitext(input_path)[1].lower()
    if ext == '.csv':
        df = pd.read_csv(input_path, encoding='utf-8-sig', low_memory=False)
    else:
        df = pd.read_excel(input_path, engine='openpyxl')
    
    print(f"   📊 Loaded {len(df):,} rows")
        
    if mode in ["3", "5"]:
        df = map_and_merge_columns(df)
        consolidate_columns(df)
    
    if mode in ["1", "5"]:
        df = clean_duplicate_rows(df)
        df = clean_empty_columns(df)
        
    if mode in ["2", "5"]:
        df = reorder_columns(df)
    
    return df

def merge_files(file_list, group_name="merged"):
    """Merge multiple files into one DataFrame."""
    print(f"\n🔗 Merging {len(file_list)} files into '{group_name}'...")
    all_dfs = []
    for f in file_list:
        try:
            basename = os.path.basename(f)
            print(f"   📂 Loading: {basename}")
            ext = os.path.splitext(f)[1].lower()
            if ext == '.csv':
                df = pd.read_csv(f, encoding='utf-8-sig', low_memory=False)
            else:
                df = pd.read_excel(f, engine='openpyxl')
            
            df['source_file'] = basename
            all_dfs.append(df)
        except Exception as e:
            print(f"   ❌ Error loading {basename}: {e}")

    if not all_dfs:
        return pd.DataFrame()

    merged_df = pd.concat(all_dfs, ignore_index=True)
    print(f"   ✅ Merged total: {len(merged_df):,} rows")
    return merged_df

# ============================================================
# UI HELPERS
# ============================================================

def print_header(text):
    line = "=" * 70
    print(f"\n{line}")
    print(text.center(70))
    print(line)

def select_folder():
    """Step 0: Select which directory to scan for files."""
    print_header("STEP 0: SELECT SOURCE FOLDER")
    folders = [
        ("output", "📂 Main Output (Freshly scraped)"),
        ("output/done", "✅ Done (Finalized files)"),
        ("output/intermediate", "⏳ Intermediate (Checkpoint saves)"),
        (".", "🏠 Root Directory"),
        (None, "🔍 ALL DIRECTORIES (Scan everywhere)"),
        ("CUSTOM", "📁 Custom Folder (Nhập đường dẫn khác)")
    ]
    
    for i, (path, desc) in enumerate(folders, 1):
        if path == "CUSTOM":
            exists = ""
        else:
            exists = " [Exists]" if path is None or os.path.exists(path) else " [Not Found]"
        print(f"  [{i}] {desc:<40}{exists}")
        
    choice = input("\n👉 Choose folder (1-6, default: 1): ").strip() or "1"
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(folders):
            if folders[idx][0] == "CUSTOM":
                current_nav = "output"
                while True:
                    print_header(f"📂 BROWSING: {current_nav}")
                    # List only subdirectories
                    try:
                        subs = [d for d in os.listdir(current_nav) if os.path.isdir(os.path.join(current_nav, d)) and not d.startswith('.')]
                    except Exception as e:
                        print(f"   ❌ Error: {e}")
                        break
                    
                    print(f"  [0] 📂 CHỌN THƯ MỤC NÀY ({current_nav})")
                    for i, d in enumerate(subs, 1):
                        print(f"  [{i}] 📁 {d}")
                    print(f"  [B] 🔙 Quay lại (Back)")
                    print(f"  [M] ⌨️  Nhập tay (Manual path)")
                    
                    nav_choice = input(f"\n👉 Chọn thư mục con (0-{len(subs)}, B/M): ").strip().upper()
                    
                    if nav_choice == "0":
                        return current_nav, True
                    elif nav_choice == "B":
                        current_nav = os.path.dirname(current_nav) or "."
                    elif nav_choice == "M":
                        manual = input("   📝 Nhập đường dẫn folder: ").strip().replace('"', '').replace("'", "")
                        manual = os.path.normpath(os.path.expanduser(manual))
                        return (manual if manual and os.path.exists(manual) else "output"), True
                    else:
                        try:
                            s_idx = int(nav_choice) - 1
                            if 0 <= s_idx < len(subs):
                                current_nav = os.path.join(current_nav, subs[s_idx])
                        except:
                            print("❌ Lựa chọn không hợp lệ")
                
                return current_nav, True
            return folders[idx][0], False
    except:
        pass
    
    return "output", False # Default to output if invalid

def select_files(all_files):
    print_header("STEP 1: SELECT FILES")
    print(f"\n📂 Found {len(all_files)} files:")
    for i, path in enumerate(all_files, 1):
        size = os.path.getsize(path) / (1024*1024)
        print(f"  [{i:2d}] {os.path.basename(path):<55} {size:6.2f}MB")
    
    print("\n💡 Options: 'ALL', '1,3,5', '1-5'")
    selection = input("\n👉 Your selection: ").strip().upper()
    
    if selection == 'ALL': return all_files
    
    try:
        indices = set()
        for part in selection.replace(' ', '').split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                indices.update(range(start, end + 1))
            else:
                indices.add(int(part))
        selected = [all_files[i-1] for i in sorted(indices) if 1 <= i <= len(all_files)]
        if not selected: print("❌ Valid files not selected"); return None
        return selected
    except:
        print("❌ Invalid format"); return None

def select_mode(selected_files):
    print_header("STEP 2: SELECT PROCESSING MODE")
    groups = detect_file_groups(selected_files)
    companies = list(groups['by_company'].keys())
    
    print(f"\n📊 Selected: {len(selected_files)} files")
    if companies: print(f"   Detected companies: {', '.join(companies)}")
    
    print("\n🎯 Processing Options:")
    print("  [1] 📄 INDIVIDUAL    → Process separately")
    print("  [2] 🔗 MERGE ALL     → Combine into 1 file")
    print("  [3] 📝 CUSTOM NAME   → Merge with custom name")
    if companies:
        print("  [4] 🏢 BY COMPANY    → Auto-merge by company")
    if groups['by_type']['import'] or groups['by_type']['export']:
        print("  [5] 📦 BY TYPE       → Auto-merge by Import/Export")
    
    choice = input("\n👉 Your choice: ").strip()
    
    if choice == "1": return ("individual", None)
    elif choice == "2": return ("merge_all", None)
    elif choice == "3":
        name = input("   📝 Output filename (no ext): ").strip()
        return ("custom", name or "MERGED_custom")
    elif choice == "4" and companies: return ("by_company", None)
    elif choice == "5": return ("by_type", None)
    else: print("❌ Invalid choice"); return (None, None)

def _browse_output_folder(start: str = "output") -> str:
    """Interactive directory browser for output folder selection."""
    current = start if os.path.isdir(start) else "."
    while True:
        print_header(f"📂 BROWSING: {current}")
        try:
            subs = sorted(
                d for d in os.listdir(current)
                if os.path.isdir(os.path.join(current, d)) and not d.startswith('.')
            )
        except Exception as e:
            print(f"   ❌ Lỗi: {e}")
            return current
        print(f"  [0] 📂 CHỌN THƯ MỤC NÀY  ({current})")
        for i, d in enumerate(subs, 1):
            print(f"  [{i:2d}] 📁 {d}")
        print(f"  [B] 🔙 Quay lại (Back)")
        print(f"  [M] ⌨️  Nhập tay (Manual path)")
        nav = input(f"\n👉 Chọn (0-{len(subs)}, B, M): ").strip().upper()
        if nav == "0":
            return current
        elif nav == "B":
            parent = os.path.dirname(os.path.abspath(current))
            current = parent if parent != os.path.abspath(current) else current
        elif nav == "M":
            manual = input("   📝 Nhập đường dẫn: ").strip().replace('"', '').replace("'", "")
            manual = os.path.normpath(os.path.expanduser(manual))
            if os.path.isdir(manual) or not os.path.exists(manual):
                return manual
            print(f"   ⚠️  Không tìm thấy: {manual}")
        else:
            try:
                s_idx = int(nav) - 1
                if 0 <= s_idx < len(subs):
                    current = os.path.join(current, subs[s_idx])
                else:
                    print("❌ Số không hợp lệ")
            except ValueError:
                print("❌ Lựa chọn không hợp lệ")


def select_output_config(mode, custom_name):
    """Step 3: Ask user for output folder, filename (merge_all), and format."""
    print_header("STEP 3: SELECT OUTPUT")

    # --- Output folder ---
    folders = [
        ("output/done",         "✅ output/done  (mặc định)"),
        ("output",              "📂 output"),
        ("output/intermediate", "⏳ output/intermediate"),
        ("output/new",          "🆕 output/new"),
        ("BROWSE",              "📁 Duyệt thư mục (Browse)"),
    ]
    print("\n📁 Chọn thư mục OUTPUT:")
    for i, (path, desc) in enumerate(folders, 1):
        suffix = "" if path == "BROWSE" else (" [Exists]" if os.path.exists(path) else " [Not Found]")
        print(f"  [{i}] {desc:<45}{suffix}")

    folder_choice = input("\n👉 Chọn folder output (1-5, mặc định 1): ").strip() or "1"
    output_dir = "output/done"

    # If user types a path directly instead of a number, use it as-is
    raw = folder_choice.replace('"', '').replace("'", "")
    if os.sep in raw or (len(raw) > 2 and raw[1:3] in (':\\', ':/')):  # looks like a path
        output_dir = os.path.normpath(os.path.expanduser(raw))
    else:
        try:
            idx = int(folder_choice) - 1
            if 0 <= idx < len(folders):
                chosen = folders[idx][0]
                if chosen == "BROWSE":
                    output_dir = _browse_output_folder("output")
                else:
                    output_dir = chosen
        except ValueError:
            pass

    # --- Output filename (for merge_all / custom) ---
    output_name = None
    if mode in ("merge_all", "custom"):
        default_name = "MERGED_all_data" if mode == "merge_all" else (custom_name or "MERGED_custom")
        print(f"\n📝 Tên file output (không cần đuôi):")
        print(f"   Mặc định: {default_name}")
        name = input("👉 Tên file (Enter để dùng mặc định): ").strip()
        output_name = name if name else default_name

    # --- Output format ---
    print("\n📄 Định dạng file output:")
    print("  [1] xlsx  (mặc định - mở được bằng Excel)")
    print("  [2] csv   (nhẹ hơn, dễ xử lý tiếp)")
    fmt_choice = input("\n👉 Chọn (1/2, mặc định 1): ").strip() or "1"
    output_fmt = "csv" if fmt_choice == "2" else "xlsx"

    return output_dir, output_name, output_fmt


def _save_df(df, path, fmt):
    """Save DataFrame to xlsx or csv."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if fmt == 'csv':
        df.to_csv(path, index=False, encoding='utf-8-sig')
    else:
        df.to_excel(path, index=False, engine='openpyxl')


def preview_output(mode, custom_name, selected_files, output_dir="output/done", output_name=None, output_fmt="xlsx"):
    print("\n📋 OUTPUT PREVIEW:")
    print("-" * 70)
    ext = f".{output_fmt}"
    if mode == "individual":
        print(f"   Will create {len(selected_files)} files (final_*{ext})")
        print(f"   Output folder: {output_dir}")
    elif mode == "merge_all":
        name = output_name or "MERGED_all_data"
        print(f"   → {os.path.join(output_dir, name + ext)}")
    elif mode == "custom":
        name = output_name or custom_name
        print(f"   → {os.path.join(output_dir, name + ext)}")
    elif mode == "by_company":
        print(f"   Will create files per company: MERGED_<company>_all{ext}")
        print(f"   Output folder: {output_dir}")
    elif mode == "by_type":
        print(f"   Will create files per type: MERGED_all_<import/export>{ext}")
        print(f"   Output folder: {output_dir}")

def execute_processing(mode, custom_name, selected_files, output_dir="output/done", output_name=None, output_fmt="xlsx"):
    print_header("🚀 PROCESSING")
    
    # Ensure output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"📁 Created directory: {output_dir}\n")
    
    ext = f".{output_fmt}"
    groups = detect_file_groups(selected_files)
    
    if mode == "individual":
        for f in selected_files:
            df = process_single_file(f, "5")
            df = sort_by_date(df)
            stem = os.path.splitext(os.path.basename(f))[0]
            out_path = os.path.join(output_dir, f"final_{stem}{ext}")
            _save_df(df, out_path, output_fmt)
            print(f"   ✅ Saved: {out_path}")
            
    elif mode == "merge_all":
        name = output_name or "MERGED_all_data"
        df = merge_files(selected_files, name)
        df = map_and_merge_columns(df)
        consolidate_columns(df)
        df = clean_duplicate_rows(df)
        df = clean_empty_columns(df)
        df = reorder_columns(df)
        df = sort_by_date(df)
        out_path = os.path.join(output_dir, f"{name}{ext}")
        _save_df(df, out_path, output_fmt)
        print(f"   ✅ Saved: {out_path}")
        
    elif mode == "custom":
        name = output_name or custom_name
        df = merge_files(selected_files, name)
        df = map_and_merge_columns(df)
        consolidate_columns(df)
        df = clean_duplicate_rows(df)
        df = clean_empty_columns(df)
        df = reorder_columns(df)
        df = sort_by_date(df)
        out_path = os.path.join(output_dir, f"{name}{ext}")
        _save_df(df, out_path, output_fmt)
        print(f"   ✅ Saved: {out_path}")
        
    elif mode == "by_company":
        for company, files in groups['by_company'].items():
            print(f"\n🏢 Company: {company}")
            df = merge_files(files, company)
            df = map_and_merge_columns(df)
            consolidate_columns(df)
            df = clean_duplicate_rows(df)
            df = clean_empty_columns(df)
            df = reorder_columns(df)
            df = sort_by_date(df)
            out_path = os.path.join(output_dir, f"MERGED_{company}_all{ext}")
            _save_df(df, out_path, output_fmt)
            print(f"   ✅ Saved: {out_path}")
            
    elif mode == "by_type":
        for trade_type, files in groups['by_type'].items():
            if not files: continue
            print(f"\n📦 Type: {trade_type}")
            df = merge_files(files, trade_type)
            df = map_and_merge_columns(df)
            consolidate_columns(df)
            df = clean_duplicate_rows(df)
            df = clean_empty_columns(df)
            df = reorder_columns(df)
            df = sort_by_date(df)
            out_path = os.path.join(output_dir, f"MERGED_all_{trade_type}{ext}")
            _save_df(df, out_path, output_fmt)
            print(f"   ✅ Saved: {out_path}")

def main():
    print("\n" + "="*70)
    print("💎 PRO 2026 DATA FINALIZER - SIMPLIFIED v6.0".center(70))
    print("="*70)
    
    # Step 0: Select Folder
    target_dir, is_custom = select_folder()
    
    # Step 1: List Files
    all_files = list_files(target_dir, skip_filter=is_custom)
    if not all_files: 
        print(f"\n❌ No CSV/Excel files found in '{target_dir or 'ALL'}'.")
        return
    
    # Step 2: Select Files from the list
    selected_files = select_files(all_files)
    if not selected_files: return
    
    mode, custom_name = select_mode(selected_files)
    if not mode: return

    output_dir, output_name, output_fmt = select_output_config(mode, custom_name)

    preview_output(mode, custom_name, selected_files, output_dir, output_name, output_fmt)
    
    if input("\n✅ Start? (Y/n): ").strip().lower() == 'n': return
    
    execute_processing(mode, custom_name, selected_files, output_dir, output_name, output_fmt)
    print("\n✅ DONE")

if __name__ == "__main__":
    main()
