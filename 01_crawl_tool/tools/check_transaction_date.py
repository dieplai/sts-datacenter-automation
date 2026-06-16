import pandas as pd
import os
import glob
from pathlib import Path

def check_date_order(filepath):
    print(f"Checking {filepath}...")
    try:
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath, low_memory=False)
        else:
            df = pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        print(f"Error reading file {filepath}: {e}")
        return

    # Look for a date column
    date_col = None
    possible_cols = ['Transaction Date', 'transaction_date', 'Date', 'date']
    for col in possible_cols:
        if col in df.columns:
            date_col = col
            break
            
    if date_col is None:
        print(f"No date column found in {filepath}. Columns available: {df.columns.tolist()[:10]}...")
        return

    print(f"Found date column: '{date_col}'")
    
    # Drop rows where date is missing
    df_clean = df.dropna(subset=[date_col]).copy()
    if df_clean.empty:
        print("Date column is empty.")
        return
        
    # Convert to datetime
    try:
        # handle multiple date formats if necessary
        df_clean['_parsed_date'] = pd.to_datetime(df_clean[date_col], format="%Y-%m-%d", errors='coerce')
        # if too many NaT, try without specific format
        if df_clean['_parsed_date'].isna().mean() > 0.5:
             df_clean['_parsed_date'] = pd.to_datetime(df_clean[date_col], errors='coerce')
    except Exception as e:
         print(f"Error parsing dates: {e}")
         df_clean['_parsed_date'] = pd.to_datetime(df_clean[date_col], errors='coerce')

    df_clean = df_clean.dropna(subset=['_parsed_date'])
    
    if df_clean.empty:
        print("Could not parse dates correctly.")
        return

    # Analyze order (should be descending, so current date <= previous date)
    # This means dates[i] <= dates[i-1]
    # We will find where dates[i] > dates[i-1], which is a forward jump.
    dates = df_clean['_parsed_date'].reset_index(drop=True)
    original_indices = df_clean.index.tolist()
    original_dates = df_clean[date_col].tolist()
    
    jumps = []
    for i in range(1, len(dates)):
        # If the date is strictly strictly newer than the previous row, there is a jump
        if dates[i] > dates[i-1]:
            jumps.append({
                'row_index': original_indices[i],
                'previous_date': original_dates[i-1],
                'current_date': original_dates[i]
            })

    if not jumps:
        print(f"✅ Success: No sorting jumps found. The '{date_col}' column is sorted descending correctly.\n")
    else:
        print(f"❌ Warning: Found {len(jumps)} jumps where the date increased instead of decreasing/staying the same.")
        print("First few jumps:")
        for idx, jump in enumerate(jumps[:20]):
            print(f"  Jump {idx+1}: Row {jump['row_index']} - Date jumped from {jump['previous_date']} to {jump['current_date']}")
        print("\n")


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
        (None, "🔍 ALL DIRECTORIES (Scan everywhere)")
    ]
    
    for i, (path, desc) in enumerate(folders, 1):
        exists = " [Exists]" if path is None or os.path.exists(path) else " [Not Found]"
        print(f"  [{i}] {desc:<40}{exists}")
        
    choice = input("\n👉 Choose folder (1-5, default: 1): ").strip() or "1"
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(folders):
            return folders[idx][0]
    except:
        pass
    
    return "output" # Default to output if invalid

def list_files(target_dir=None):
    """List all CSV/XLSX files in targeted or default directories."""
    if target_dir:
        search_dirs = [target_dir]
    else:
        search_dirs = ["output/done", "output", "output/intermediate", "."]
        
    all_files = []
    for d in search_dirs:
        if os.path.exists(d):
            files = [os.path.join(d, f) for f in os.listdir(d) 
                     if f.endswith(('.csv', '.xlsx'))]
            all_files.extend(files)
            
    # Sort by modification time (newest first)
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return all_files

def select_files(all_files):
    print_header("STEP 1: SELECT FILES")
    print(f"\n📂 Found {len(all_files)} files:")
    for i, path in enumerate(all_files, 1):
        try:
            size = os.path.getsize(path) / (1024*1024)
            print(f"  [{i:2d}] {os.path.basename(path):<55} {size:6.2f}MB")
        except:
             print(f"  [{i:2d}] {os.path.basename(path):<55} (Error getting size)")
    
    print("\n💡 Options: 'ALL', '1,3,5', '1-5'")
    selection = input("\n👉 Your selection (default: ALL): ").strip().upper() or "ALL"
    
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

def main():
    print("\n" + "="*70)
    print("📅 TRANSACTION DATE CHECKER".center(70))
    print("="*70)
    
    # Step 0: Select Folder
    target_dir = select_folder()
    
    # Step 1: List Files
    all_files = list_files(target_dir)
    if not all_files: 
        print(f"\n❌ No CSV/Excel files found in '{target_dir or 'ALL'}'.")
        return
    
    # Step 2: Select Files from the list
    selected_files = select_files(all_files)
    if not selected_files: return
    
    print(f"\n🚀 Checking {len(selected_files)} files for date sorting consistency...\n")
    print("-" * 70)
    for f in selected_files:
        check_date_order(f)
        print("-" * 70)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Check specific file if provided directly
        check_date_order(sys.argv[1])
    else:
        main()

