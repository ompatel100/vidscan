import os
import shutil
import subprocess
import argparse
import concurrent.futures
import itertools
import sys
import time
import csv
import json
import datetime
from typing import Dict, Iterator, List, Any, Tuple

# --- USER CONFIGURATION ---
# File extensions that you want to scan
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'}

FFPROBE_PATH = shutil.which('ffprobe')

DEFAULT_W = min(4, os.cpu_count() or 1)
DEFAULT_W_SSD = min(32, os.cpu_count() or 1)
MAX_W = 128

def get_ui() -> Dict[str, Any]:
    stdout_encoding = getattr(sys.stdout, 'encoding', '')
    is_utf8 = stdout_encoding and stdout_encoding.lower() in ['utf-8', 'utf8']

    if is_utf8:
        bar_fill = '█'
        bar_empty = '░'
        spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    else:
        bar_fill = '='
        bar_empty = '-'
        spinner = ['|', '/', '-', '\\']

    is_terminal = sys.stdout.isatty()

    color = False

    if 'FORCE_COLOR' in os.environ or 'CLICOLOR_FORCE' in os.environ:
        color = True
    elif 'NO_COLOR' in os.environ:
        color = False
    elif is_terminal and enable_ansi_windows():
        color = True

    if color:
        red = '\033[91m'
        yellow = '\033[93m'
        green = '\033[92m'
        cyan = '\033[96m'
        reset = '\033[0m'
    else:
        red = yellow = green = cyan = reset = ''

    return {
        'is_terminal': is_terminal,
        'bar_fill': bar_fill,
        'bar_empty': bar_empty,
        'spinner': itertools.cycle(spinner),
        'red': red,
        'yellow': yellow,
        'green': green,
        'cyan': cyan,
        'reset': reset
    }

def enable_ansi_windows() -> bool:
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()

        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        
        if not kernel32.SetConsoleMode(handle, mode.value | 0x0004):
            return False 
        
        return True
    except Exception:
        return False

def get_video_duration(file_path: str, ffprobe_timeout: float) -> Tuple[float, str]:
    try:
        command = [
            FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]

        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=True, 
            timeout=ffprobe_timeout
        )
        return float(result.stdout), ""
        
    except subprocess.TimeoutExpired:
        return 0.0, f"Process timed out after {ffprobe_timeout} seconds"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Corrupted or unreadable file"
        return 0.0, error_msg
    except Exception as e:
        return 0.0, str(e)

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

def scan_videos_concurrently(root_folder: str, excluded_set: set, num_workers: int, ffprobe_timeout:float, fast_start_mode:bool, ui: Dict[str, Any]) -> Tuple[Dict[str, Any], int, int, List[Dict[str, str]]]:
    folder_data: Dict[str, Any] = {}
    total_files = 0

    start_time = time.time()

    if not fast_start_mode:
        print(f"{ui['yellow']}Scanning directory structure...{ui['reset']}")
        total_files = sum(1 for _ in stream_video_files(root_folder, excluded_set))

        if total_files == 0:
            return folder_data, 0, 0, []
        
        print(f"Found {ui['cyan']}{total_files}{ui['reset']} video files.", end=" ")

    print(f"Processing with {num_workers} workers...")
    
    files_processed = 0
    success_count = 0
    failed_videos_data = []

    last_print_time = 0.0
    update_interval = 0.1
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_file = {}

        for file_path, mtime in stream_video_files(root_folder, excluded_set):
            future = executor.submit(get_video_duration, file_path, ffprobe_timeout)
            future_to_file[future] = (file_path, mtime)

        for future in concurrent.futures.as_completed(future_to_file):
            file_path, mtime = future_to_file[future]
            duration, error_msg = future.result()
            
            files_processed += 1

            if duration > 0:
                success_count += 1
                dirpath = os.path.dirname(file_path)
                filename = os.path.basename(file_path)
                
                if dirpath not in folder_data:
                    folder_data[dirpath] = {'files': []}
                
                folder_data[dirpath]['files'].append({
                    'name': filename, 
                    'duration': duration, 
                    'mtime': mtime
                })
            else:
                failed_videos_data.append({
                    'path': file_path, 
                    'error': error_msg
                })

            if ui['is_terminal']:
                current_time = time.time()
                if current_time - last_print_time >= update_interval or files_processed == total_files:
                    if fast_start_mode:
                        spinner = next(ui['spinner'])
                        print(f"\r[{spinner}] Files processed: {ui['cyan']}{files_processed}{ui['reset']}", end="", flush=True)
                    else:
                        progress = files_processed / total_files
                        bar_length = 40
                        filled = int(bar_length * progress)
                        
                        bar = (ui['bar_fill'] * filled) + (ui['bar_empty'] * (bar_length - filled))
                        percent = int(progress * 100)

                        print(f"\rProgress: [{bar}] {percent}% ({files_processed}/{total_files})", end="", flush=True)

                    last_print_time = current_time

    print(f"\nProcessing complete in {time.time() - start_time:.2f} seconds.")

    for info in folder_data.values():
        info['total_seconds'] = sum(f['duration'] for f in info['files'])
        info['video_count'] = len(info['files'])
        info['last_modified'] = max(f['mtime'] for f in info['files'])

    if fast_start_mode:
        total_files = files_processed 

    return folder_data, total_files, success_count, failed_videos_data

def get_txt_report_summary_lines(sorted_data: List[tuple], failed_count: int) -> List[str]:
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

    if failed_count > 0:
        lines.extend([
            "",
            "---",
            f"[!] NOTE: Scanning failed for {failed_count} videos and are excluded from this report."
        ])

    return lines

def get_txt_report_detailed_lines(sorted_data: List[tuple], failed_count: int) -> List[str]:
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

    if failed_count > 0:
        lines.extend([
            "",
            "---",
            f"[!] Note: Scanning failed for {failed_count} videos and are excluded from this report."
        ])

    return lines

def get_failed_videos_report_lines(failed_videos_data: List[Dict[str, str]]) -> List[str]:
    lines = [
        "FAILED VIDEO FILES",
        "=" * 40,
        "These videos could not be read by ffprobe.",
        ""
    ]
    for failed_video in sorted(failed_videos_data, key=lambda x: x['path']):
        lines.append(f"- {failed_video['path']}")
        lines.append(f"  Reason: {failed_video['error']}\n")
    
    return lines

def write_txt_and_failed_videos_report(sorted_data: List[tuple], output_path: str, template: str, failed_videos_data: List[Dict[str, str]], failed_videos_report_path: str, timestamp: datetime.datetime) -> Tuple[str, str]:
    failed_count = len(failed_videos_data)

    timestamp_str = f"Generated on: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    
    if template == 'detailed':
        report_lines = get_txt_report_detailed_lines(sorted_data, failed_count)
    else:
        report_lines = get_txt_report_summary_lines(sorted_data, failed_count)

    report_lines.append(timestamp_str)
    report_content = "\n".join(report_lines)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    failed_videos_report_content = ""

    if failed_count > 0:
        failed_videos_report_lines = get_failed_videos_report_lines(failed_videos_data)
        failed_videos_report_lines.append(timestamp_str)
        failed_videos_report_content = "\n".join(failed_videos_report_lines)
        
        with open(failed_videos_report_path, 'w', encoding='utf-8') as f:
            f.write(failed_videos_report_content)

    return report_content, failed_videos_report_content

def write_csv_report(sorted_data: List[tuple], output_path: str, root_folder: str, total_videos: int, success_count: int, failed_videos_data: List[Dict[str, str]], timestamp: datetime.datetime):
    failed_count = len(failed_videos_data)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Folder Path', 'Relative Path', 'File Name', 'Duration (Seconds)', 'Duration (Formatted)'])
        
        for folder_path, info in sorted_data:
            try:
                relative_path = os.path.relpath(folder_path, root_folder)
            except ValueError:
                relative_path = folder_path
                
            sorted_files = sorted(info['files'], key=lambda x: x['name'])
            
            for file_info in sorted_files:
                writer.writerow([
                    folder_path,
                    relative_path,
                    file_info['name'],
                    f"{file_info['duration']:.2f}",
                    format_seconds_hms(file_info['duration'])
                ])

        if failed_count > 0:
            for failed_video in sorted(failed_videos_data, key=lambda x: x['path']):
                folder_path = os.path.dirname(failed_video['path'])
                try:
                    relative_path = os.path.relpath(folder_path, root_folder)
                except ValueError:
                    relative_path = folder_path
                file_name = os.path.basename(failed_video['path'])
                
                writer.writerow([
                    folder_path,
                    relative_path,
                    file_name,
                    'FAILED',
                    failed_video['error']
                ])

        writer.writerow([])
        writer.writerow(['--- SCAN SUMMARY ---', '', '', '', ''])
        writer.writerow(['Total Videos Discovered', total_videos, '', '', ''])
        writer.writerow(['Successful', success_count, '', '', ''])
        writer.writerow(['Failed', failed_count, '', '', ''])
        writer.writerow(['Report Generated At', timestamp.strftime('%Y-%m-%d %H:%M:%S')])

def write_json_report(sorted_data: List[tuple], output_path: str, total_videos: int, success_count: int, failed_videos_data: List[Dict[str, str]], timestamp: datetime.datetime):
    total_seconds = sum(info['total_seconds'] for _, info in sorted_data)
    
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
            "total_videos_discovered": total_videos,
            "successful_videos": success_count,
            "failed_videos_count": len(failed_videos_data),
            "total_duration_seconds": round(total_seconds, 2),
            "total_duration_formatted": format_seconds_hms(total_seconds),
            "generated_at": timestamp.isoformat()
        },
        "details": details_list,
        "failed_videos": sorted(failed_videos_data, key=lambda x: x['path']),
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report_structure, f, indent=4)

def parse_w_flag(value: str) -> int:
    try:
        w = int(value)
        if w <= 0:
            raise argparse.ArgumentTypeError("--workers must be atleast 1")
        
        return min(w, MAX_W)
        
    except ValueError:
        if value.strip().lower() == 'ssd':
            return DEFAULT_W_SSD
        
        return DEFAULT_W

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
        type=parse_w_flag,
        default=DEFAULT_W,
        help=(
            f"Number of parallel threads to use (default: {DEFAULT_W} for your system)\n"
            f"-w ssd : Uses an optimal {DEFAULT_W_SSD} for your system, provide it if you have an SSD\n"
            "-w <n> : Manually provide threads (e.g. -w 6)\n"
            "Anything else will fall back to default"
        )
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
    parser.add_argument(
        "--fast-start",
        action="store_true",
        help="Directly start processing (Recommended for network drives).\n"
            "Note: Only processed count will be displayed, not progress bar."
    )
    parser.add_argument(
        "--ffprobe-timeout",
        type=float,
        default=15.0,
        help="Maximum seconds to wait for a video before marking as failed (default: 15.0).\n"
            "Increase this for slow network drives."
    )
    args = parser.parse_args()

    ui = get_ui()

    if not FFPROBE_PATH:
        print(f"\n{ui['red']}ERROR: ffprobe not found in system PATH{ui['reset']}")
        print("This script requires FFmpeg to work.")
        print("Install FFmpeg from https://ffmpeg.org/download.html and add it to your system's PATH.")
        sys.exit(1)

    try:
        subprocess.run(
            [FFPROBE_PATH, "-version"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            check=True
        )
    except Exception as e:
        print(f"{ui['red']}ERROR: ffprobe was found, but failed to execute. {e}{ui['reset']}")
        sys.exit(1)

    root_folder = args.folder_path
    excluded_set = set(args.exclude)

    if not os.path.isdir(root_folder):
        print(f"{ui['red']}ERROR: The path '{root_folder}' is not a valid directory.{ui['reset']}")
        sys.exit(1)

    print(f"Scanning folder: {ui['cyan']}{root_folder}{ui['reset']}")
    if excluded_set:
        print(f"Excluding folders: {ui['cyan']}{', '.join(excluded_set)}{ui['reset']}")

    folder_durations, total_videos, success_count, failed_videos_data = scan_videos_concurrently(
        root_folder,
        excluded_set,
        args.workers,
        args.ffprobe_timeout,
        args.fast_start,
        ui
    )

    failed_count = len(failed_videos_data)

    if not folder_durations:
        if failed_count > 0:
            print(f"\n{ui['yellow']}[!] NOTE: Found {failed_count} videos, but all of them failed.{ui['reset']}")
        else:
            print(f"\nNo video files found with the configured extensions: {', '.join(sorted(list(VIDEO_EXTENSIONS)))}")
            print("To include other formats, please add them to the VIDEO_EXTENSIONS at the top of the script.")
        sys.exit(0)

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
    
    timestamp = datetime.datetime.now()

    try:
        if args.format == 'csv':
            write_csv_report(sorted_data, output_path, root_folder, total_videos, success_count, failed_videos_data, timestamp)
            print(f"\n{ui['green']}Success! CSV file saved to:{ui['reset']}\n{ui['cyan']}{output_path}{ui['reset']}")
            
            if failed_count > 0:
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos. Check the 'FAILED' rows in the CSV.{ui['reset']}")

        elif args.format == 'json':
            write_json_report(sorted_data, output_path, total_videos, success_count, failed_videos_data, timestamp)
            print(f"\n{ui['green']}Success! JSON file saved to:{ui['reset']}\n{ui['cyan']}{output_path}{ui['reset']}")
            
            if failed_count > 0:
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos. Check the 'failed_files' array in the JSON.{ui['reset']}")
            
        else:
            failed_videos_report_filename = f"{folder_name} - Failed Videos.txt"
            failed_videos_report_path = os.path.join(root_folder, failed_videos_report_filename)

            report_content, failed_videos_report_content = write_txt_and_failed_videos_report(
                sorted_data,
                output_path,
                args.template,
                failed_videos_data,
                failed_videos_report_path,
                timestamp
            )

            print(f"\n{ui['yellow']}--- File Preview ---{ui['reset']}")
            print(report_content)
            print(f"\n{ui['green']}Success! Text file saved to:{ui['reset']}\n{ui['cyan']}{output_path}{ui['reset']}")

            if failed_count > 0:
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos.{ui['reset']}")
                print(f"\n{ui['yellow']}--- Failed Videos File Preview ---{ui['reset']}")
                print(failed_videos_report_content)
                print(f"\n{ui['yellow']}Failed videos file has been saved to:\n{ui['cyan']}{failed_videos_report_path}{ui['reset']}")

    except Exception as e:
        print(f"\n{ui['red']}ERROR: Could not save the file. Reason: {e}{ui['reset']}")

if __name__ == "__main__":
    main()