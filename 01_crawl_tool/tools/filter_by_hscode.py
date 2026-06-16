"""
filter_by_hscode.py
-------------------
Filter CSV/XLSX files by HS Code prefix(es).

Supports:
- Interactive folder selection (same UI as finalize_pro_detail.py)
- Multiple HS Code prefixes (e.g. "61", "6109", "610910")
- Merge matched rows across files OR keep separate output per file
- Custom output filename
- Both CSV and XLSX input/output

Usage:
    python tools/filter_by_hscode.py
"""

import os
import re
import pandas as pd

# ============================================================
# CONSTANTS
# ============================================================
HS_COLUMNS = [
    'HS Code', 'hs', 'hs_code', 'hscode', 'HS', 'Hscode',
]  # Candidates – first match wins

# ============================================================
# HELPERS
# ============================================================

def print_header(text: str) -> None:
    line = "=" * 70
    print(f"\n{line}")
    print(text.center(70))
    print(line)


def find_hs_column(df: pd.DataFrame) -> str | None:
    """Return the name of the HS Code column in *df*, or None if not found."""
    for candidate in HS_COLUMNS:
        if candidate in df.columns:
            return candidate
    # Fallback: case-insensitive scan
    for col in df.columns:
        if re.fullmatch(r'hs[_ ]?code?', col.strip(), re.IGNORECASE):
            return col
    return None


def load_file(filepath: str) -> pd.DataFrame:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.csv':
        return pd.read_csv(filepath, encoding='utf-8-sig', low_memory=False, dtype=str)
    return pd.read_excel(filepath, dtype=str, engine='openpyxl')


def save_file(df: pd.DataFrame, out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    ext = os.path.splitext(out_path)[1].lower()
    if ext == '.csv':
        df.to_csv(out_path, index=False, encoding='utf-8-sig')
    else:
        df.to_excel(out_path, index=False, engine='openpyxl')


def filter_by_hs(df: pd.DataFrame, hs_col: str, prefixes: list[str]) -> pd.DataFrame:
    """Keep rows whose HS Code starts with ANY of *prefixes*."""
    # Normalise: strip spaces, keep only digits
    normalised = df[hs_col].astype(str).str.replace(r'\s+', '', regex=True).str.strip()
    mask = normalised.apply(
        lambda v: any(v.startswith(p) for p in prefixes)
    )
    return df[mask].copy()


def collect_files(directory: str) -> list[str]:
    files = []
    for f in os.listdir(directory):
        if f.lower().endswith(('.csv', '.xlsx')) and not f.startswith('~'):
            files.append(os.path.join(directory, f))
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return files

# ============================================================
# INTERACTIVE UI – mirrors finalize_pro_detail.py style
# ============================================================

def browse_folder(start: str = "output") -> str:
    """Interactive directory browser. Returns the selected path."""
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
            manual = input("   📝 Nhập đường dẫn: ").strip().strip('"').strip("'")
            manual = os.path.normpath(os.path.expanduser(manual))
            if os.path.isdir(manual):
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


def select_folder() -> str:
    print_header("STEP 1: SELECT SOURCE FOLDER")

    folders = [
        ("output",               "📂 Main Output"),
        ("output/done",          "✅ Done"),
        ("output/intermediate",  "⏳ Intermediate"),
        ("output/new",           "🆕 New"),
        (".",                    "🏠 Root Directory"),
        ("BROWSE",               "📁 Duyệt thư mục (Browse)"),
    ]

    for i, (path, desc) in enumerate(folders, 1):
        suffix = "" if path == "BROWSE" else (" [Exists]" if os.path.exists(path) else " [Not Found]")
        print(f"  [{i}] {desc:<45}{suffix}")

    choice = input("\n👉 Chọn folder (1-6, mặc định 1): ").strip() or "1"

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(folders):
            folder_path = folders[idx][0]
            if folder_path == "BROWSE":
                return browse_folder("output")
            return folder_path
    except ValueError:
        pass

    return "output"


def select_files(all_files: list[str]) -> list[str] | None:
    print_header("STEP 2: SELECT INPUT FILES")
    print(f"\n📂 Tìm thấy {len(all_files)} file(s):\n")
    for i, path in enumerate(all_files, 1):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"  [{i:2d}] {os.path.basename(path):<55} {size_mb:6.2f} MB")

    print("\n💡 Chọn: 'ALL', '1,3,5', '1-5'")
    selection = input("\n👉 Lựa chọn: ").strip().upper()

    if selection == 'ALL':
        return all_files

    try:
        indices: set[int] = set()
        for part in selection.replace(' ', '').split(','):
            if '-' in part:
                a, b = map(int, part.split('-', 1))
                indices.update(range(a, b + 1))
            else:
                indices.add(int(part))
        selected = [all_files[i - 1] for i in sorted(indices) if 1 <= i <= len(all_files)]
        if not selected:
            print("❌ Không có file hợp lệ nào được chọn.")
            return None
        return selected
    except (ValueError, IndexError):
        print("❌ Định dạng không hợp lệ.")
        return None


def enter_hs_prefixes() -> list[str]:
    print_header("STEP 3: ENTER HS CODE PREFIX(ES)")
    print("   Nhập 1 hoặc nhiều mã HS (phân tách bởi dấu phẩy hoặc khoảng trắng).")
    print("   Ví dụ: 61  /  6109  /  610910  /  61, 62, 63\n")

    raw = input("👉 HS Code(s): ").strip()
    # Split on commas or whitespace, keep only digit strings
    parts = re.split(r'[,\s]+', raw)
    prefixes = [p.strip() for p in parts if re.fullmatch(r'\d+', p.strip())]

    if not prefixes:
        print("❌ Không nhập được mã HS hợp lệ.")
        return []

    print(f"\n   ✅ Sẽ lọc theo prefix: {prefixes}")
    return prefixes


def choose_output_format() -> str:
    print("\n📄 Định dạng output:")
    print("  [1] xlsx  (mặc định)")
    print("  [2] csv")
    fmt = input("👉 Chọn (1/2, mặc định 1): ").strip() or "1"
    return 'csv' if fmt == '2' else 'xlsx'


def choose_merge_mode(n_files: int) -> str:
    if n_files == 1:
        return 'individual'  # Only 1 file → no merge option needed
    print_header("STEP 4: OUTPUT MODE")
    print("  [1] 🔗 MERGE  – Gộp tất cả kết quả vào 1 file")
    print("  [2] 📄 SEPARATE – Giữ riêng từng file")
    choice = input("\n👉 Chọn (1/2, mặc định 1): ").strip() or "1"
    return 'merge' if choice != '2' else 'individual'


def choose_output_name(prefixes: list[str], merge_mode: str, fmt: str) -> str:
    default_stem = "filtered_hs" + "_".join(prefixes)
    print(f"\n📝 Tên file output (không cần đuôi .{fmt}):")
    print(f"   Mặc định: {default_stem}")
    name = input("👉 Tên file (Enter để dùng mặc định): ").strip()
    if not name:
        name = default_stem
    # Sanitise
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    return name


def sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Sort rows by Transaction Date ascending (oldest first, newest last)."""
    DATE_COL = 'Transaction Date'
    if DATE_COL not in df.columns:
        return df
    print(f"  📅 Sorting by '{DATE_COL}'...")
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], dayfirst=False, errors='coerce')
    df = df.sort_values(DATE_COL, ascending=True, na_position='last').reset_index(drop=True)
    df[DATE_COL] = df[DATE_COL].dt.strftime('%Y-%m-%d').where(df[DATE_COL].notna(), other='')
    return df


def select_output_folder() -> str:
    print_header("SELECT OUTPUT FOLDER")
    folders = [
        ("output/done",          "✅ output/done  (mặc định)"),
        ("output",               "📂 output"),
        ("output/intermediate",  "⏳ output/intermediate"),
        ("output/new",           "🆕 output/new"),
        ("BROWSE",               "📁 Duyệt thư mục (Browse)"),
    ]
    for i, (path, desc) in enumerate(folders, 1):
        suffix = "" if path == "BROWSE" else (" [Exists]" if os.path.exists(path) else " [Not Found]")
        print(f"  [{i}] {desc:<45}{suffix}")

    choice = input("\n👉 Chọn folder output (1-5, mặc định 1): ").strip() or "1"

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(folders):
            folder_path = folders[idx][0]
            if folder_path == "BROWSE":
                return browse_folder("output")
            return folder_path
    except ValueError:
        pass

    return "output/done"

# ============================================================
# CORE PROCESSING
# ============================================================

def process(
    selected_files: list[str],
    prefixes: list[str],
    merge_mode: str,
    output_dir: str,
    output_name: str,
    fmt: str,
) -> None:
    print_header("🚀 PROCESSING")

    os.makedirs(output_dir, exist_ok=True)

    results: list[pd.DataFrame] = []
    total_in = total_out = 0

    for fp in selected_files:
        basename = os.path.basename(fp)
        try:
            df = load_file(fp)
        except Exception as e:
            print(f"  ❌ Không đọc được {basename}: {e}")
            continue

        hs_col = find_hs_column(df)
        if hs_col is None:
            print(f"  ⚠️  Không tìm thấy cột HS Code trong {basename} – bỏ qua.")
            continue

        filtered = filter_by_hs(df, hs_col, prefixes)
        n_in, n_out = len(df), len(filtered)
        total_in += n_in
        total_out += n_out

        status = f"{n_in:>8,} rows → {n_out:>7,} matched"

        if n_out == 0:
            print(f"  [NONE ] {basename:<50}  {status}")
            continue

        if merge_mode == 'individual':
            stem = os.path.splitext(basename)[0]
            hs_tag = "_hs" + "_".join(prefixes)
            out_path = os.path.join(output_dir, f"{output_name or stem + hs_tag}.{fmt}")
            # If multiple individual files, append hs_tag to original stem
            if len(selected_files) > 1:
                out_path = os.path.join(output_dir, f"{stem}{hs_tag}.{fmt}")
            filtered = sort_by_date(filtered)
            save_file(filtered, out_path)
            print(f"  [SAVED] {basename:<50}  {status}  →  {os.path.basename(out_path)}")
        else:
            filtered['source_file'] = basename
            results.append(filtered)
            print(f"  [OK   ] {basename:<50}  {status}")

    if merge_mode == 'merge' and results:
        merged = pd.concat(results, ignore_index=True)
        merged = sort_by_date(merged)
        out_path = os.path.join(output_dir, f"{output_name}.{fmt}")
        save_file(merged, out_path)
        print(f"\n  ✅ Đã gộp {len(results)} file(s) → {out_path}")
        print(f"     Tổng: {total_out:,} / {total_in:,} dòng khớp")
    elif merge_mode == 'merge' and not results:
        print("\n  ⚠️  Không có dòng nào khớp với HS Code đã chọn.")
    else:
        print(f"\n  ✅ Hoàn tất. Tổng: {total_out:,} / {total_in:,} dòng khớp.")

# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("\n" + "=" * 70)
    print("🔍  HS CODE FILTER TOOL  v1.0".center(70))
    print("=" * 70)

    # Step 1 – Source folder
    source_dir = select_folder()
    if not os.path.isdir(source_dir):
        print(f"\n❌ Folder không tồn tại: {source_dir}")
        return

    all_files = collect_files(source_dir)
    if not all_files:
        print(f"\n❌ Không tìm thấy file CSV/XLSX nào trong '{source_dir}'.")
        return

    # Step 2 – File selection
    selected_files = select_files(all_files)
    if not selected_files:
        return

    # Step 3 – HS Code prefix(es)
    prefixes = enter_hs_prefixes()
    if not prefixes:
        return

    # Step 4 – Merge or separate
    merge_mode = choose_merge_mode(len(selected_files))

    # Step 5 – Output format
    fmt = choose_output_format()

    # Step 6 – Output filename
    output_name = choose_output_name(prefixes, merge_mode, fmt)

    # Step 7 – Output folder
    output_dir = select_output_folder()

    # Preview
    print("\n📋 TÓM TẮT:")
    print(f"   Source      : {source_dir}  ({len(selected_files)} file(s))")
    print(f"   HS Prefixes : {prefixes}")
    print(f"   Mode        : {'Merge → 1 file' if merge_mode == 'merge' else 'Separate files'}")
    print(f"   Output      : {output_dir}/{output_name}.{fmt}")

    confirm = input("\n✅ Bắt đầu? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("   Đã huỷ.")
        return

    process(selected_files, prefixes, merge_mode, output_dir, output_name, fmt)
    print("\n✅ DONE\n")


if __name__ == "__main__":
    main()
