import pandas as pd
import os
import glob
import sys
from datetime import datetime

# Setup path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src import config
except ImportError:
    config = None

def print_header(text):
    line = "=" * 70
    print(f"\n{line}")
    print(text.center(70))
    print(line)

def select_folder():
    """Step 0: Select which directory to scan for files."""
    print_header("SELECT SOURCE FOLDER")
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
        if d and os.path.exists(d):
            files = [os.path.join(d, f) for f in os.listdir(d) 
                     if f.lower().endswith(('.csv', '.xlsx'))]
            all_files.extend(files)
            
    # Sort by modification time (newest first)
    all_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return all_files

def select_files(all_files):
    print_header("SELECT FILES TO CONVERT")
    if not all_files:
        print("❌ No CSV or XLSX files found.")
        return None
        
    print(f"\n📂 Found {len(all_files)} files (sorted by newest):")
    for i, path in enumerate(all_files, 1):
        size = os.path.getsize(path) / (1024*1024)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
        print(f"  [{i:2d}] {os.path.basename(path):<55} {size:6.2f}MB  ({mtime})")
    
    print("\n💡 Options: 'ALL', '1,3,5', '1-5'")
    selection = input("\n👉 Your selection: ").strip().upper()
    
    if selection == 'ALL': return all_files
    
    try:
        indices = set()
        for part in selection.replace(' ', '').split(','):
            if '-' in part:
                parts = part.split('-')
                if len(parts) == 2:
                    start, end = map(int, parts)
                    indices.update(range(start, end + 1))
            else:
                indices.add(int(part))
        selected = [all_files[i-1] for i in sorted(indices) if 1 <= i <= len(all_files)]
        if not selected: 
            print("❌ Valid files not selected")
            return None
        return selected
    except Exception as e:
        print(f"❌ Invalid format: {e}")
        return None

def convert_files(selected_files):
    if not selected_files:
        return
        
    print_header(f"🚀 CONVERTING {len(selected_files)} FILES")
    
    for input_path in selected_files:
        try:
            filename = os.path.basename(input_path)
            ext = os.path.splitext(input_path)[1].lower()
            
            if ext == '.csv':
                target_ext = '.xlsx'
                target_format = 'Excel'
            else:
                target_ext = '.csv'
                target_format = 'CSV'
                
            output_path = os.path.splitext(input_path)[0] + target_ext
            
            print(f"\n⏳ Processing: {filename}")
            print(f"   Mode: {ext.upper()} → {target_ext.upper()}")
            
            # Read
            if ext == '.csv':
                try:
                    df = pd.read_csv(input_path, encoding='utf-8-sig', low_memory=False)
                except:
                    df = pd.read_csv(input_path, encoding='utf-8', errors='replace', low_memory=False)
            else:
                df = pd.read_excel(input_path, engine='openpyxl')
            
            print(f"   Rows: {len(df):,}")
            
            # Save
            if target_ext == '.csv':
                df.to_csv(output_path, index=False, encoding='utf-8-sig')
            else:
                df.to_excel(output_path, index=False, engine='openpyxl')
                
            print(f"✅ Success! Saved to: {os.path.basename(output_path)}")
            
        except Exception as e:
            print(f"❌ Error converting {os.path.basename(input_path)}: {e}")

def main():
    try:
        # 1. Select Folder
        target_dir = select_folder()
        
        # 2. List Files
        all_files = list_files(target_dir)
        
        # 3. Select Files
        selected = select_files(all_files)
        
        # 4. Execute
        if selected:
            convert_files(selected)
            print("\n" + "="*70)
            print("✨ All selected conversions completed.")
            print("="*70)
            
    except KeyboardInterrupt:
        print("\n\n👋 Operation cancelled by user.")
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
