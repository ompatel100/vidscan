import os
import shutil
import subprocess
import argparse
import concurrent.futures
import time
import csv
import json
import datetime
from typing import Dict, Iterator, List, Any, Tuple

# --- USER CONFIGURATION ---
# File extensions that you want to scan
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}

FFPROBE_PATH = shutil.which('ffprobe')

def get_video_duration(file_path: str) -> float:
    try:
        command = [
            FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return float(result.stdout)
    except Exception as e:
        print(f"Warning: Could not process file '{os.path.basename(file_path)}'. Error: {e}")
        return 0.0

def format_seconds_hms(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}"

def stream_video_files(root_folder: str, excluded_set: set) -> Iterator[Tuple[str, float]]:
    stack = [root_folder]
    while stack:
        current_dir = stack.pop()
        with os.scandir(current_dir) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in excluded_set:
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in VIDEO_EXTENSIONS:
                        yield entry.path, entry.stat().st_mtime

def scan_videos_concurrently(root_folder: str, excluded_set: set, num_workers: int) -> Dict[str, Any]:
    folder_data: Dict[str, Any] = {}
    
    print("Scanning directory structure...")
    start_time = time.time()
    total_files = sum(1 for _ in stream_video_files(root_folder, excluded_set))
    
    if total_files == 0:
        return folder_data

    print(f"Found {total_files} video files. Processing with {num_workers} workers...")
    
    files_processed = 0
    last_print_time = 0.0
    update_interval = 0.1
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_file = {}

        for file_path, mtime in stream_video_files(root_folder, excluded_set):
            future = executor.submit(get_video_duration, file_path)
            future_to_file[future] = (file_path, mtime)

        for future in concurrent.futures.as_completed(future_to_file):
            file_path, mtime = future_to_file[future]
            duration = future.result()
            
            files_processed += 1

            if duration > 0:
                dirpath = os.path.dirname(file_path)
                filename = os.path.basename(file_path)
                
                if dirpath not in folder_data:
                    folder_data[dirpath] = {'files': []}
                
                folder_data[dirpath]['files'].append({
                    'name': filename, 
                    'duration': duration, 
                    'mtime': mtime
                })

            current_time = time.time()
            
            if current_time - last_print_time >= update_interval or files_processed == total_files:
                progress = files_processed / total_files
                bar_length = 40
                filled = int(bar_length * progress)
                bar = '█' * filled + '-' * (bar_length - filled)
                percent = int(progress * 100)

                print(f'\rProgress: [{bar}] {percent}% ({files_processed}/{total_files})', end="", flush=True)
                last_print_time = current_time

    print(f"\nProcessing complete in {time.time() - start_time:.2f} seconds.")

    for info in folder_data.values():
        info['total_seconds'] = sum(f['duration'] for f in info['files'])
        info['video_count'] = len(info['files'])
        info['last_modified'] = max(f['mtime'] for f in info['files'])
        
    return folder_data

def generate_summary_report(sorted_data: List[tuple]) -> List[str]:
    lines = [
        "Video Duration (Summary)", 
        "=" * 40,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_videos = 0

    for folder_path, info in sorted_data:
        folder_name = os.path.basename(folder_path) or os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")
        lines.append(f"  -> Videos: {info['video_count']:>3} | Duration: {format_seconds_hms(info['total_seconds'])}")
        lines.append("-" * 40)
        
        grand_total_seconds += info['total_seconds']
        grand_total_videos += info['video_count']
    
    lines.extend([
        "\nTOTALS",
        f"  -> Total Folders: {len(sorted_data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}",
        "=" * 40
    ])
    return lines

def generate_detailed_report(sorted_data: List[tuple]) -> List[str]:
    lines = [
        "Video Duration (Detailed)", 
        "=" * 40,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_videos = 0

    for folder_path, info in sorted_data:
        folder_name = os.path.basename(folder_path) or os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")
        lines.append(f"  [ Videos: {info['video_count']:>3} | Subtotal: {format_seconds_hms(info['total_seconds'])} ]")
        
        sorted_files = sorted(info['files'], key=lambda x: x['name'])
        for file_info in sorted_files:
            lines.append(f"    - {file_info['name']} ({format_seconds_hms(file_info['duration'])})")
            
        lines.append("-" * 40)
        
        grand_total_seconds += info['total_seconds']
        grand_total_videos += info['video_count']
    
    lines.extend([
        "\nGRAND TOTAL",
        f"  -> Total Folders: {len(sorted_data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}",
        "=" * 40
    ])
    return lines

def write_csv_report(sorted_data: List[tuple], output_path: str, root_folder: str):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Folder Path', 'Relative Path', 'File Name', 'Duration (Seconds)', 'Duration (Formatted)'])
        
        for folder_path, info in sorted_data:
            relative_path = os.path.relpath(folder_path, root_folder)
            
            sorted_files = sorted(info['files'], key=lambda x: x['name'])
            
            for file_info in sorted_files:
                writer.writerow([
                    folder_path,
                    relative_path,
                    file_info['name'],
                    f"{file_info['duration']:.2f}",
                    format_seconds_hms(file_info['duration'])
                ])

def write_json_report(sorted_data: List[tuple], output_path: str):
    total_seconds = sum(info['total_seconds'] for _, info in sorted_data)
    total_videos = sum(info['video_count'] for _, info in sorted_data)

    details_list = []
    for folder_path, info in sorted_data:
        details_list.append({
            "folder_path": folder_path,
            "video_count": info['video_count'],
            "total_seconds": info['total_seconds'],
            "last_modified_timestamp": info['last_modified'],
            "last_modified_human": datetime.datetime.fromtimestamp(info['last_modified']).isoformat(),
            "files": sorted(info['files'], key=lambda x: x['name'])
        })

    report_structure = {
        "summary": {
            "total_folders": len(sorted_data),
            "total_videos": total_videos,
            "total_duration_seconds": round(total_seconds, 2),
            "total_duration_formatted": format_seconds_hms(total_seconds),
            "generated_at": datetime.datetime.now().isoformat()
        },
        "details": details_list
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report_structure, f, indent=4)

def main():
    parser = argparse.ArgumentParser(
        description="A high performance tool to calculate total video duration across nested directories.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "folder_path",
        help="The full path to the main folder you want to scan."
    )
    parser.add_argument(
        "-e", "--exclude",
        nargs='+',
        default=[],
        help="A space separated list of folder names to exclude from the scan (case sensitive)."
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=min(32, (os.cpu_count() or 1) + 4),
        help="Number of parallel threads to use.\n(default: dynamically calculated for your system)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=['txt', 'csv', 'json'],
        default='txt',
        help="Output file format (default: txt).")
    parser.add_argument(
        "-t", "--template", 
        choices=['summary', 'detailed'], 
        default='summary',
        help="Text report template (default: summary)."
    )
    parser.add_argument(
        "-sb", "--sort-by",
        choices=['name', 'duration', 'videos', 'date'],
        default='name',
        help="Sort folders by (default: name)."
    )
    parser.add_argument(
        "-so", "--sort-order",
        choices=['asc', 'desc'],
        default='asc',
        help="Sort order (default: asc)."
    )
    args = parser.parse_args()

    if not FFPROBE_PATH:
        print("\n--- ERROR: ffprobe not found in system PATH ---")
        print("This script requires FFmpeg to work.")
        print("Install FFmpeg from https://ffmpeg.org/download.html and add it to your system's PATH.")
        return

    root_folder = args.folder_path
    excluded_set = set(args.exclude)

    if not os.path.isdir(root_folder):
        print(f"Error: The path '{root_folder}' is not a valid directory.")
        return

    print(f"Scanning folder: {root_folder}")
    if excluded_set:
        print(f"Excluding folders: {', '.join(excluded_set)}")

    folder_durations = scan_videos_concurrently(root_folder, excluded_set, args.workers)

    if not folder_durations:
        print(f"\nNo video files found with the configured extensions: {', '.join(sorted(list(VIDEO_EXTENSIONS)))}")
        print("To include other formats, please add them to the VIDEO_EXTENSIONS at the top of the script.")
        return

    sort_key_func = {
        'name': lambda item: os.path.basename(item[0]),
        'duration': lambda item: item[1]['total_seconds'],
        'videos': lambda item: item[1]['video_count'],
        'date': lambda item: item[1]['last_modified']
    }[args.sort_by]

    is_descending = (args.sort_order == 'desc')

    sorted_data = sorted(
        folder_durations.items(),
        key=sort_key_func,
        reverse=is_descending
    )
    
    folder_name = os.path.basename(os.path.normpath(root_folder))
    output_filename = f"{folder_name} - Video Duration.{args.format}"
    output_path = os.path.join(root_folder, output_filename)
    
    try:
        if args.format == 'csv':
            write_csv_report(sorted_data, output_path, root_folder)
            print(f"\nSuccess! CSV file saved to:\n{output_path}")
            
        elif args.format == 'json':
            write_json_report(sorted_data, output_path)
            print(f"\nSuccess! JSON file saved to:\n{output_path}")
            
        else:
            if args.template == 'detailed':
                report_lines = generate_detailed_report(sorted_data)
            else:
                report_lines = generate_summary_report(sorted_data)
            
            timestamp = f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            report_lines.append(timestamp)
            report_content = "\n".join(report_lines)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_content)
                    
            print("\n--- File Preview ---")
            print(report_content)

            print(f"\nSuccess! Text file saved to:\n{output_path}")

    except Exception as e:
        print(f"\nError: Could not save the file. Reason: {e}")

if __name__ == "__main__":
    main()