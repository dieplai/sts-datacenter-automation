"""
Daily Data Merger Tool for Pro 2026
===================================
Automatically scans output/daily directories recursively, finds daily chunks, and merges them.
Utilizes the finalize_pro_detail.py pipeline for data mapping, cleaning, and consolidating.
"""

import os
import sys
import pandas as pd
from datetime import datetime

# Load the finalizer module safely
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import finalize_pro_detail as finalizer
except ImportError:
    print("❌ Cannot find finalize_pro_detail.py. Please run from the project root or ensure it exists.")
    sys.exit(1)

def print_header(text):
    finalizer.print_header(text)

def find_files_recursive(directory):
    """Find all CSV and XLSX files recursively."""
    all_files = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(('.csv', '.xlsx')) and not f.startswith(('FINAL_', 'final_', 'MERGED_', 'CLEANED_')):
                all_files.append(os.path.join(root, f))
    # Sort files
    all_files.sort()
    return all_files

def select_daily_folder():
    """Interactive loop to select a folder starting from output/daily"""
    print_header("📂 STEP 1: SELECT DAILY DIRECTORY")
    
    current_nav = os.path.join("output", "daily")
    if not os.path.exists(current_nav):
        print(f"⚠️ Thư mục '{current_nav}' chưa được tạo. Sẽ bắt đầu từ thư mục 'output'.")
        current_nav = "output"
        
    while True:
        print_header(f"📂 ĐANG Ở: {current_nav}")
        try:
            subs = [d for d in os.listdir(current_nav) if os.path.isdir(os.path.join(current_nav, d)) and not d.startswith('.')]
        except Exception as e:
            print(f"   ❌ Lỗi đọc thư mục: {e}")
            break
            
        print(f"  [0] 📂 CHỌN THƯ MỤC NÀY VÀ MERGE TẤT CẢ ({current_nav})")
        for i, d in enumerate(subs, 1):
            print(f"  [{i}] 📁 {d}")
        print(f"  [B] 🔙 Quay lại (Back)")
        print(f"  [Q] 🚪 Thoát")
        
        nav_choice = input(f"\n👉 Chọn thư mục con (0-{len(subs)}, B, Q): ").strip().upper()
        
        if nav_choice == "Q":
            return None
        elif nav_choice == "0":
            return current_nav
        elif nav_choice == "B":
            parent = os.path.dirname(current_nav)
            current_nav = parent if parent else "."
        else:
            try:
                idx = int(nav_choice) - 1
                if 0 <= idx < len(subs):
                    current_nav = os.path.join(current_nav, subs[idx])
                else:
                    print("❌ Lựa chọn không hợp lệ")
            except ValueError:
                print("❌ Lựa chọn không hợp lệ")

def main():
    print_header("PRO 2026 DAILY MERGER TOOL")
    
    target_dir = select_daily_folder()
    if not target_dir:
        print("Đã hủy.")
        return
        
    print(f"\n🔎 Scanning '{target_dir}' recursively...")
    files = find_files_recursive(target_dir)
    
    if not files:
        print("❌ Không tìm thấy file dữ liệu nào trong thư mục này.")
        return
        
    print(f"\n📂 Đã tìm thấy {len(files)} files:")
    for f in files[:10]:
        print(f"  📄 {os.path.relpath(f, target_dir)}")
    if len(files) > 10:
        print(f"  ... và {len(files) - 10} files khác.")
        
    confirm = input(f"\n👉 Bạn có muốn merge tất cả {len(files)} files này? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("Đã hủy.")
        return
        
    # Create group name based on path hierarchy
    rel_path = os.path.relpath(target_dir, "output")
    if rel_path == "." or rel_path.startswith(".."):
        group_name = "daily_all"
    else:
        group_name = rel_path.replace("\\", "_").replace("/", "_")
         
    # Merge files using finalizer logic
    merged_df = finalizer.merge_files(files, group_name=group_name)
    
    if merged_df.empty:
        print("❌ Dữ liệu rỗng sau khi merge.")
        return
        
    print("\n⚙️ XỬ LÝ LÀM SẠCH (FINALIZATION PIPELINE)?")
    print("  [1] Chạy đầy đủ (Chuẩn hóa cột, gộp cột trùng, xóa trùng dòng, sắp xếp)")
    print("  [2] Chỉ lưu file raw đã merge (Không xử lý)")
    choice = input("\n👉 Lựa chọn (Mặc định: 1): ").strip()
    
    if choice != "2":
        merged_df = finalizer.map_and_merge_columns(merged_df)
        finalizer.consolidate_columns(merged_df)
        merged_df = finalizer.clean_duplicate_rows(merged_df)
        merged_df = finalizer.clean_empty_columns(merged_df)
        merged_df = finalizer.reorder_columns(merged_df)
        merged_df = finalizer.sort_by_date(merged_df)
        
    # Save the output
    out_dir = os.path.join("output", "done")
    os.makedirs(out_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"FINAL_{group_name}_{timestamp}.csv"
    out_path = os.path.join(out_dir, out_name)
    
    print(f"\n💾 Đang lưu CSV vào: {out_path}...")
    merged_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    
    xls_path = out_path.replace('.csv', '.xlsx')
    print(f"💾 Đang lưu Excel vào: {xls_path}...")
    try:
        merged_df.to_excel(xls_path, index=False, engine='openpyxl')
        print(f"   ✅ Đã lưu Excel thành công.")
    except Exception as e:
        print(f"   ⚠️ Lỗi khi lưu Excel: {e}")
    
    print("\n🎉 HOÀN TẤT MERGE DAILY!")

if __name__ == "__main__":
    main()
