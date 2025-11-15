import os
import shutil
import subprocess
import argparse
import concurrent.futures
import csv
import json
import datetime
from typing import Dict, List, Any

# --- USER CONFIGURATION ---
# File extensions that you want to scan
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}

FFPROBE_PATH = shutil.which('ffprobe')

def get_video_duration(file_path: str) -> float:
    try:
        if FFPROBE_PATH:
            command = [
                FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", file_path
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return float(result.stdout)
        else:
            from moviepy import VideoFileClip 
            with VideoFileClip(file_path) as clip:
                return clip.duration if clip.duration else 0.0
    except Exception as e:
        print(f"Warning: Could not process file '{os.path.basename(file_path)}'. Error: {e}")
        return 0.0

def format_seconds_hms(seconds: float) -> str:
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def scan_videos_concurrently(root_folder: str, excluded_set: set, num_workers: int) -> Dict[str, Any]:
    tasks = []
    print("Finding video files...")
    for dirpath, dirs, filenames in os.walk(root_folder):
        dirs[:] = [d for d in dirs if d not in excluded_set]
        
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS:
                tasks.append(os.path.join(dirpath, filename))

    if not tasks:
        return {}

    print(f"Found {len(tasks)} video files. Processing with {num_workers} workers...")
    
    folder_data: Dict[str, Any] = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_path = {executor.submit(get_video_duration, path): path for path in tasks}
        
        for i, future in enumerate(concurrent.futures.as_completed(future_to_path)):
            path = future_to_path[future]
            duration = future.result()
            
            progress = (i + 1) / len(tasks)
            bar = '█' * int(progress * 40)
            print(f'\rProgress: [{bar:<40}] {int(progress*100)}%', end="")

            if duration > 0:
                dirpath = os.path.dirname(path)
                filename = os.path.basename(path)
                
                if dirpath not in folder_data:
                    folder_data[dirpath] = {'files': []}
                
                folder_data[dirpath]['files'].append({'name': filename, 'duration': duration})

    for info in folder_data.values():
        info['total_seconds'] = sum(f['duration'] for f in info['files'])
        info['video_count'] = len(info['files'])
    
    print("\nProcessing complete.")
    return folder_data

def generate_summary_report(data: Dict[str, Any]) -> List[str]:
    lines = [
        "Video Duration (Summary)", 
        "=" * 40,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_videos = 0

    for folder_path, info in sorted(data.items()):
        folder_name = os.path.basename(folder_path)
        if not folder_name:
            folder_name = os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")
        lines.append(f"  -> Videos: {info['video_count']} | Duration: {format_seconds_hms(info['total_seconds'])}")
        lines.append("-" * 40)
        
        grand_total_seconds += info['total_seconds']
        grand_total_videos += info['video_count']
    
    lines.extend([
        "\nTOTALS",
        f"  -> Total Folders: {len(data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}",
        "=" * 40
    ])
    return lines

def generate_detailed_report(data: Dict[str, Any]) -> List[str]:
    lines = [
        "Video Duration (Detailed)", 
        "=" * 60,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_videos = 0

    for folder_path, info in sorted(data.items()):
        folder_name = os.path.basename(folder_path)
        if not folder_name:
            folder_name = os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")
        lines.append(f"  [Subtotal: {format_seconds_hms(info['total_seconds'])} | {info['video_count']} videos]")
        
        sorted_files = sorted(info['files'], key=lambda x: x['name'])
        for file_info in sorted_files:
            lines.append(f"    - {file_info['name']} ({format_seconds_hms(file_info['duration'])})")
            
        lines.append("-" * 60)
        
        grand_total_seconds += info['total_seconds']
        grand_total_videos += info['video_count']
    
    lines.extend([
        "\nGRAND TOTAL",
        f"  -> Total Folders: {len(data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}",
        "=" * 60
    ])
    return lines

def write_csv_report(data: Dict[str, Any], output_path: str, root_folder: str):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Folder Path', 'Relative Path', 'File Name', 'Duration (Seconds)', 'Duration (Formatted)'])
        
        for folder_path, info in sorted(data.items()):
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

def write_json_report(data: Dict[str, Any], output_path: str):
    total_seconds = sum(info['total_seconds'] for info in data.values())
    total_videos = sum(len(info['files']) for info in data.values())

    report_structure = {
        "summary": {
            "total_folders": len(data),
            "total_videos": total_videos,
            "total_duration_seconds": round(total_seconds, 2),
            "total_duration_formatted": format_seconds_hms(total_seconds),
            "generated_at": datetime.datetime.now().isoformat()
        },
        "data": data
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report_structure, f, indent=4)

def main():
    parser = argparse.ArgumentParser(
        description="A high performance tool to calculate total video duration across nested directories."
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
        help="The output format for the report (default: txt).")
    parser.add_argument(
        "-t", "--template", 
        choices=['summary', 'detailed'], 
        default='summary',
        help="The output template for the text report (default: summary)."
    )
    args = parser.parse_args()

    root_folder = args.folder_path
    excluded_set = set(args.exclude)

    print(f"Scanning folder: {root_folder}")
    if excluded_set:
        print(f"Excluding folders: {', '.join(excluded_set)}")

    if not os.path.isdir(root_folder):
        print(f"Error: The path '{root_folder}' is not a valid directory.")
        return
    
    if FFPROBE_PATH:
        print("Using ffprobe for scanning.")
    else:
        print("ffprobe not found in system PATH. Checking for moviepy...")
        try:
            from moviepy import VideoFileClip
            print("Using moviepy (slower).")
        except ImportError:
            print("\n--- ERROR: ffprobe or moviepy not found ---")
            print("This script requires either FFmpeg or the moviepy library to work.")
            print("\nOption 1 (Recommended for best performance):")
            print("  Install FFmpeg from https://ffmpeg.org/download.html and add it to your system's PATH.")
            print("\nOption 2 (Easy to setup but slower):")
            print("  Install moviepy: pip install moviepy~=2.2")
            return

    folder_durations = scan_videos_concurrently(root_folder, excluded_set, args.workers)

    if not folder_durations:
        print(f"\nNo video files found with the configured extensions: {', '.join(sorted(list(VIDEO_EXTENSIONS)))}")
        print("To include other formats, please add them to the VIDEO_EXTENSIONS at the top of the script.")
        return

    if args.template == 'detailed':
        report_lines = generate_detailed_report(folder_durations)
    else:
        report_lines = generate_summary_report(folder_durations)

    folder_name = os.path.basename(os.path.normpath(root_folder))
    output_filename = f"{folder_name} - Video Duration.{args.format}"
    output_path = os.path.join(root_folder, output_filename)
    
    try:
        if args.format == 'csv':
            write_csv_report(folder_durations, output_path, root_folder)
            print(f"\nSuccess! CSV file saved to:\n{output_path}")
            
        elif args.format == 'json':
            write_json_report(folder_durations, output_path)
            print(f"\nSuccess! JSON file saved to:\n{output_path}")
            
        else:
            if args.template == 'detailed':
                report_lines = generate_detailed_report(folder_durations)
            else:
                report_lines = generate_summary_report(folder_durations)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(report_lines))
            print(f"\nSuccess! Text file saved to:\n{output_path}")

    except Exception as e:
        print(f"\nError: Could not save the file. Reason: {e}")

if __name__ == "__main__":
    main()