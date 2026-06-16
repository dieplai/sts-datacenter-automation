
import pandas as pd
import os
import sys

# Define Field Mapping (Reduced to known conflict areas for efficiency, or full list)
FIELD_MAPPING = {
    'bill_id': 'Bill of Lading ID',
    'bill_no': 'Declaration No',
    'customs_branch_code_1': 'Customs Br Code',
    'exporter_country_name': 'Supply Country',
    'buyer': 'Buyer',
    'exporter_country': 'Supply Country',
}

def normalize(s):
    if pd.isna(s): return ""
    return str(s).strip().lower()

def inspect_conflicts(directory="."):
    report_file = "conflict_debug_report.txt"
    
    # Files identified from the previous log
    target_files = [
        "inter_export_52_all_buyers_latest.xlsx",
        "detail_Vietnam_import_hs53.xlsx",
        "inter_import_52_all_buyers_latest.xlsx",
        "inter_import_51_all_buyers_latest.xlsx",
        "inter_export_52_latest.xlsx"
    ]
    
    found_files = []
    # Search for files
    search_dirs = [".", "output", "output/intermediate"]
    for fname in target_files:
        for d in search_dirs:
            path = os.path.join(d, fname)
            if os.path.exists(path):
                found_files.append(path)
                break
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("=== CONFLICT INSPECTION REPORT ===\n\n")
        
        for filepath in found_files:
            print(f"Inspecting {filepath}...")
            f.write(f"FILE: {filepath}\n")
            f.write("-" * 50 + "\n")
            
            try:
                if filepath.endswith('.csv'):
                    df = pd.read_csv(filepath, low_memory=False)
                else:
                    df = pd.read_excel(filepath, engine='openpyxl')
                
                # Check for conflicts
                for col in df.columns:
                    norm_col = col.lower()
                    canonical = None
                    
                    # Simple lookup
                    if col in FIELD_MAPPING:
                        canonical = FIELD_MAPPING[col]
                    # Lowercase lookup
                    elif norm_col in FIELD_MAPPING:
                        canonical = FIELD_MAPPING[norm_col]
                        
                    if canonical and canonical in df.columns and col != canonical:
                        # Found potentially conflicting columns
                        
                        # Compare values
                        mask = df[col].notna() & df[canonical].notna()
                        if not mask.any():
                            continue
                            
                        # Extract differing rows
                        conflicts = []
                        for idx, row in df[mask].iterrows():
                            val1 = str(row[col]).strip()
                            val2 = str(row[canonical]).strip()
                            
                            # Skip if essentially same (case insensitive)
                            if val1.lower() == val2.lower():
                                continue
                                
                            # Skip if subset
                            if val1.lower() in val2.lower() or val2.lower() in val1.lower():
                                continue

                            conflicts.append((idx, val1, val2))
                            if len(conflicts) >= 20: # Limit sample
                                break
                        
                        if conflicts:
                            f.write(f"  CONFLICT: '{col}' vs '{canonical}'\n")
                            f.write(f"  First 20 mismatches:\n")
                            f.write(f"    {'Row':<6} | {col:<30} | {canonical:<30}\n")
                            f.write(f"    {'-'*6} | {'-'*30} | {'-'*30}\n")
                            for idx, v1, v2 in conflicts:
                                v1_disp = (v1[:27] + '..') if len(v1) > 27 else v1
                                v2_disp = (v2[:27] + '..') if len(v2) > 27 else v2
                                f.write(f"    {idx:<6} | {v1_disp:<30} | {v2_disp:<30}\n")
                            f.write("\n")
                            
            except Exception as e:
                f.write(f"  ERROR reading file: {str(e)}\n")
            f.write("\n")

    print(f"Report written to {report_file}")

if __name__ == "__main__":
    inspect_conflicts()
