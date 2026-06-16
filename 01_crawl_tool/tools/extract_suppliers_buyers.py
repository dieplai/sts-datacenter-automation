import pandas as pd
import os
import argparse

def extract_suppliers_buyers(input_path, output_path):
    print(f"Reading file: {input_path}")
    if not os.path.exists(input_path):
        print(f"❌ File not found: {input_path}")
        return

    try:
        print("Reading file into DataFrame...")
        if input_path.endswith('.csv'):
            df = pd.read_csv(input_path, low_memory=False)
        else:
            df = pd.read_excel(input_path)
        print(f"File read successfully. Shape: {df.shape}")
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return

    print("Identifying columns...")
    # Chuẩn hóa tên cột về chữ thường để dễ tìm
    cols_lower = df.columns.astype(str).str.lower()
    
    # Tìm các cột nghi ngờ chứa tên công ty (chỉ lấy tên, loại trừ địa chỉ, sđt)
    supplier_cols = []
    buyer_cols = []
    
    for orig_col, lower_col in zip(df.columns, cols_lower):
        # Bỏ qua các cột thông tin phụ (address, tel, zip, id, code...)
        if any(skip in lower_col for skip in ['address', 'tel', 'phone', 'zip', 'id', 'code', 'country', 'port']):
            continue
            
        if 'supplier' in lower_col or 'exporter' in lower_col or 'seller' in lower_col:
            supplier_cols.append(orig_col)
            
        if 'buyer' in lower_col or 'importer' in lower_col or 'purchaser' in lower_col:
            buyer_cols.append(orig_col)

    print(f"🛠️  Identified Supplier columns: {supplier_cols}")
    print(f"🛠️  Identified Buyer columns: {buyer_cols}")

    def get_unique_values(df, candiate_cols):
        all_vals = set()
        for col in candiate_cols:
            # Lấy giá trị, loại bỏ nan và khoảng trắng
            vals = df[col].dropna().astype(str).str.strip().unique()
            for v in vals:
                # Bỏ qua các chuỗi rỗng hoặc rác
                if v and v.lower() not in ['nan', 'none', '-', '']:
                    all_vals.add(v)
        return sorted(list(all_vals))

    suppliers = get_unique_values(df, supplier_cols)
    buyers = get_unique_values(df, buyer_cols)

    print(f"📊 Found {len(suppliers)} unique suppliers.")
    print(f"📊 Found {len(buyers)} unique buyers.")

    # Đảm bảo thư mục output tồn tại
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"FILE: {os.path.basename(input_path)}\n")
        f.write(f"TOTAL UNIQUE SUPPLIERS: {len(suppliers)}\n")
        f.write(f"TOTAL UNIQUE BUYERS: {len(buyers)}\n")
        f.write("="*50 + "\n\n")
        
        f.write("=== SUPPLIERS (EXPORTERS) ===\n")
        for i, s in enumerate(suppliers, 1):
            f.write(f"{i}. {s}\n")
        
        f.write("\n\n")
        
        f.write("=== BUYERS (IMPORTERS) ===\n")
        for i, b in enumerate(buyers, 1):
            f.write(f"{i}. {b}\n")
    
    print(f"✅ Extracted list saved successfully to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract a clean list of Suppliers and Buyers from an Excel/CSV file")
    parser.add_argument("--input", "-i", default=r"output\done\Vietnam_im_7001_2010_2026.xlsx", help="Input excel/csv file path")
    parser.add_argument("--output", "-o", default=r"output\suppliers_buyers_list.txt", help="Output txt file path")
    args = parser.parse_args()
    
    extract_suppliers_buyers(args.input, args.output)
