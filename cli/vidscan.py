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

def get_video_duration(video_path: str, ffprobe_timeout: float) -> Tuple[float, str]:
    try:
        command = [
            FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
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
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def format_bytes(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

    size_units = size_bytes
    unit_idx = 0
    while size_units >= 1024 and unit_idx < len(units) - 1:
        size_units /= 1024.0
        unit_idx += 1

    return f"{size_units:.2f} {units[unit_idx]}"

def stream_video_files(root_folder: str, excluded_set: set) -> Iterator[Tuple[str, float, int]]:
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
                        yield entry.path, entry.stat().st_mtime, entry.stat().st_size

def scan_videos_concurrently(root_folder: str, excluded_set: set, num_workers: int, ffprobe_timeout:float, fast_start_mode:bool, ui: Dict[str, Any]) -> Tuple[Dict[str, Any], int, int, List[Dict[str, Any]]]:
    folder_data: Dict[str, Any] = {}
    total_videos = 0

    start_time = time.time()

    if not fast_start_mode:
        print(f"{ui['yellow']}Scanning directory structure...{ui['reset']}")
        total_videos = sum(1 for _ in stream_video_files(root_folder, excluded_set))

        if total_videos == 0:
            return folder_data, 0, 0, []
        
        print(f"Found {ui['cyan']}{total_videos}{ui['reset']} video files.", end=" ")

    print(f"Processing with {num_workers} workers...")
    
    videos_processed = 0
    success_count = 0
    failed_videos_data = []

    last_print_time = 0.0
    update_interval = 0.1
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_video = {}

        for video_path, mtime, size in stream_video_files(root_folder, excluded_set):
            future = executor.submit(get_video_duration, video_path, ffprobe_timeout)
            future_to_video[future] = (video_path, mtime, size)

        for future in concurrent.futures.as_completed(future_to_video):
            video_path, mtime, size = future_to_video[future]
            duration, error_msg = future.result()
            
            videos_processed += 1

            if duration > 0:
                success_count += 1
                dirpath = os.path.dirname(video_path)
                filename = os.path.basename(video_path)
                
                if dirpath not in folder_data:
                    folder_data[dirpath] = {'videos': []}
                
                folder_data[dirpath]['videos'].append({
                    'name': filename, 
                    'duration': duration, 
                    'mtime': mtime,
                    'size': size
                })
            else:
                failed_videos_data.append({
                    'path': video_path, 
                    'error': error_msg,
                    'size': size
                })

            if ui['is_terminal']:
                current_time = time.time()
                if current_time - last_print_time >= update_interval or videos_processed == total_videos:
                    if fast_start_mode:
                        spinner = next(ui['spinner'])
                        print(f"\r[{spinner}] Videos processed: {ui['cyan']}{videos_processed}{ui['reset']}", end="", flush=True)
                    else:
                        progress = videos_processed / total_videos
                        bar_length = 40
                        filled = int(bar_length * progress)
                        
                        bar = (ui['bar_fill'] * filled) + (ui['bar_empty'] * (bar_length - filled))
                        percent = int(progress * 100)

                        print(f"\rProgress: [{bar}] {percent}% ({videos_processed}/{total_videos})", end="", flush=True)

                    last_print_time = current_time

    print(f"\nProcessing complete in {time.time() - start_time:.2f} seconds.")

    for info in folder_data.values():
        info['total_seconds'] = sum(vid['duration'] for vid in info['videos'])
        info['total_size'] = sum(vid['size'] for vid in info['videos'])
        info['video_count'] = len(info['videos'])
        info['last_modified'] = max(vid['mtime'] for vid in info['videos'])

    if fast_start_mode:
        total_videos = videos_processed 

    return folder_data, total_videos, success_count, failed_videos_data

def get_txt_report_summary_lines(sorted_data: List[tuple], failed_count: int, include_size: bool) -> List[str]:
    divide_line_length = 60 if include_size else 45

    lines = [
        "Video Duration (Summary)", 
        "=" * divide_line_length,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_vid_size = 0
    grand_total_videos = 0

    for folder_path, info in sorted_data:
        folder_name = os.path.basename(folder_path) or os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")

        size_str = f" | Size: {format_bytes(info['total_size'])}" if include_size else ""
        lines.append(f"  -> Videos: {info['video_count']:>3} | Duration: {format_seconds_hms(info['total_seconds'])}{size_str}")
        lines.append("-" * divide_line_length)
        
        grand_total_seconds += info['total_seconds']
        grand_total_vid_size += info['total_size']
        grand_total_videos += info['video_count']
    
    totals_lines = [
        "\nTOTALS",
        f"  -> Total Folders: {len(sorted_data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}"
    ]
    
    if include_size:
        totals_lines.append(f"  -> Total Videos Size: {format_bytes(grand_total_vid_size)}")
        
    totals_lines.append("=" * divide_line_length)
    lines.extend(totals_lines)

    if failed_count > 0:
        lines.extend([
            "",
            "---",
            f"[!] NOTE: Scanning failed for {failed_count} videos and are excluded from this report."
        ])

    return lines

def get_txt_report_detailed_lines(sorted_data: List[tuple], failed_count: int, include_size: bool) -> List[str]:
    divide_line_length = 75 if include_size else 60

    lines = [
        "Video Duration (Detailed)", 
        "=" * divide_line_length,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_vid_size = 0
    grand_total_videos = 0

    for folder_path, info in sorted_data:
        folder_name = os.path.basename(folder_path) or os.path.basename(os.path.normpath(folder_path))

        lines.append(f"Folder: {folder_name}")
        
        sub_total_size_str = f" | Subtotal Size: {format_bytes(info['total_size'])}" if include_size else ""
        lines.append(f"  [ Videos: {info['video_count']:>3} | Subtotal Duration: {format_seconds_hms(info['total_seconds'])}{sub_total_size_str} ]")
        
        sorted_videos = sorted(info['videos'], key=lambda x: x['name'])
        for vid_info in sorted_videos:
            size_str = f" | {format_bytes(vid_info['size'])}" if include_size else ""
            lines.append(f"    - {vid_info['name']} ({format_seconds_hms(vid_info['duration'])}{size_str})")
            
        lines.append("-" * divide_line_length)
        
        grand_total_seconds += info['total_seconds']
        grand_total_vid_size += info['total_size']
        grand_total_videos += info['video_count']
    
    totals_lines = [
        "\nGRAND TOTAL",
        f"  -> Total Folders: {len(sorted_data)}",
        f"  -> Total Videos: {grand_total_videos}",
        f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}"
    ]
    
    if include_size:
        totals_lines.append(f"  -> Total Videos Size: {format_bytes(grand_total_vid_size)}")
    
    totals_lines.append("=" * divide_line_length)
    lines.extend(totals_lines)

    if failed_count > 0:
        lines.extend([
            "",
            "---",
            f"[!] Note: Scanning failed for {failed_count} videos and are excluded from this report."
        ])

    return lines

def get_failed_videos_report_lines(failed_videos_data: List[Dict[str, Any]]) -> List[str]:
    divide_line_length = 60

    lines = [
        "FAILED VIDEO FILES",
        "=" * divide_line_length,
        "These videos could not be read by ffprobe.",
        ""
    ]

    total_failed_vid_size = 0

    for failed_video in sorted(failed_videos_data, key=lambda x: x['path']):
        lines.append(f"- {failed_video['path']}")
        lines.append(f"  Reason: {failed_video['error']}")
        lines.append(f"  Size: {format_bytes(failed_video['size'])}\n")

        total_failed_vid_size += failed_video['size']

    totals_lines = [
        "\nTOTALS",
        f"  -> Total Failed Videos: {len(failed_videos_data)}",
        f"  -> Total Size: {format_bytes(total_failed_vid_size)}"
    ]

    totals_lines.append("=" * divide_line_length)
    lines.extend(totals_lines)
    
    return lines

def write_txt_and_failed_videos_report(sorted_data: List[tuple], output_path: str, template: str, failed_videos_data: List[Dict[str, Any]], failed_videos_report_path: str, timestamp: datetime.datetime, include_size: bool) -> Tuple[str, str]:
    failed_count = len(failed_videos_data)

    timestamp_str = f"Generated on: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    
    if template == 'detailed':
        report_lines = get_txt_report_detailed_lines(sorted_data, failed_count, include_size)
    else:
        report_lines = get_txt_report_summary_lines(sorted_data, failed_count, include_size)

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

def write_csv_report(sorted_data: List[tuple], output_path: str, root_folder: str, total_videos: int, success_count: int, failed_videos_data: List[Dict[str, Any]], timestamp: datetime.datetime):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Folder Path', 'Relative Path', 'File Name', 'Duration (Seconds)', 'Duration (Formatted)', 'Size (Bytes)', 'Size (Formatted)'])
        
        total_vid_size_successful = 0
        for folder_path, info in sorted_data:
            try:
                relative_path = os.path.relpath(folder_path, root_folder)
            except ValueError:
                relative_path = folder_path
                
            sorted_videos = sorted(info['videos'], key=lambda x: x['name'])
            
            for vid_info in sorted_videos:
                writer.writerow([
                    folder_path,
                    relative_path,
                    vid_info['name'],
                    f"{vid_info['duration']:.2f}",
                    format_seconds_hms(vid_info['duration']),
                    vid_info['size'],
                    format_bytes(vid_info['size'])
                ])

            total_vid_size_successful += info['total_size']

        total_vid_size_failed = 0
        if failed_videos_data:
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
                    failed_video['error'],
                    failed_video['size'],
                    format_bytes(failed_video['size'])
                ])

                total_vid_size_failed += failed_video['size']

        writer.writerow([])
        writer.writerow(['--- SCAN SUMMARY ---', '', '', '', '', '', ''])
        writer.writerow(['Total Videos Discovered', total_videos, '', '', '', '', ''])
        writer.writerow(['Successful', success_count, '', '', '', '', ''])
        writer.writerow(['Failed', len(failed_videos_data), '', '', '', '', ''])
        writer.writerow(['Total Size (Successful Videos)', total_vid_size_successful, format_bytes(total_vid_size_successful), '', '', '', ''])
        writer.writerow(['Total Size (Failed Videos)', total_vid_size_failed, format_bytes(total_vid_size_failed), '', '', '', ''])
        writer.writerow(['Total Size (All Videos)', total_vid_size_successful + total_vid_size_failed, format_bytes(total_vid_size_successful + total_vid_size_failed), '', '', '', ''])
        writer.writerow(['Report Generated At', timestamp.strftime('%Y-%m-%d %H:%M:%S'), '', '', '', '', ''])

def write_json_report(sorted_data: List[tuple], output_path: str, total_videos: int, success_count: int, failed_videos_data: List[Dict[str, Any]], timestamp: datetime.datetime):
    total_vid_size_successful = 0
    total_seconds = 0
    details_list = []
    for folder_path, info in sorted_data:
        videos_formatted = []
        for video_data in sorted(info['videos'], key=lambda x: x['name']):
            video_data_copy = dict(video_data)
            video_data_copy['size_formatted'] = format_bytes(video_data['size'])
            video_data_copy['duration_formatted'] = format_seconds_hms(video_data['duration'])
            videos_formatted.append(video_data_copy)
        
        total_seconds += info['total_seconds']
        total_vid_size_successful += info['total_size']

        details_list.append({
            "folder_path": folder_path,
            "video_count": info['video_count'],
            "total_seconds": info['total_seconds'],
            "total_duration_formatted": format_seconds_hms(info['total_seconds']),
            "total_videos_size_bytes": info['total_size'],
            "total_videos_size_formatted": format_bytes(info['total_size']),
            "last_modified_timestamp": info['last_modified'],
            "last_modified_human": datetime.datetime.fromtimestamp(info['last_modified']).isoformat(),
            "videos": videos_formatted
        })
    
    total_vid_size_failed = 0
    failed_videos_formatted = []
    for failed_video in sorted(failed_videos_data, key=lambda x: x['path']):
        failed_video_copy = dict(failed_video)
        failed_video_copy['size_formatted'] = format_bytes(failed_video['size'])
        failed_videos_formatted.append(failed_video_copy)
        
        total_vid_size_failed += failed_video['size']

    report_structure = {
        "summary": {
            "total_folders": len(sorted_data),
            "total_videos_discovered": total_videos,
            "successful_videos": success_count,
            "failed_videos_count": len(failed_videos_data),
            "total_duration_seconds": round(total_seconds, 2),
            "total_duration_formatted": format_seconds_hms(total_seconds),
            "total_successful_videos_size_bytes": total_vid_size_successful,
            "total_successful_videos_size_formatted": format_bytes(total_vid_size_successful),
            "total_failed_videos_size_bytes": total_vid_size_failed,
            "total_failed_videos_size_formatted": format_bytes(total_vid_size_failed),
            "total_videos_size_bytes": total_vid_size_successful + total_vid_size_failed,
            "total_videos_size_formatted": format_bytes(total_vid_size_successful + total_vid_size_failed),
            "generated_at": timestamp.isoformat()
        },
        "details": details_list,
        "failed_videos": failed_videos_formatted,
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
        choices=['txt', 'csv', 'json', 'all'],
        default='txt',
        help="Output file format (default: txt).")
    parser.add_argument(
        "-t", "--template", 
        choices=['summary', 'detailed'], 
        default='summary',
        help="Text report template (default: summary)."
    )
    parser.add_argument(
        "--include-size-txt",
        action="store_true",
        help="Include video size in the txt reports."
    )
    parser.add_argument(
        "-sb", "--sort-by",
        choices=['name', 'duration', 'videos', 'size', 'date'],
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
        'size': lambda item: item[1]['total_size'],
        'date': lambda item: item[1]['last_modified']
    }[args.sort_by]

    is_descending = (args.sort_order == 'desc')

    sorted_data = sorted(
        folder_durations.items(),
        key=sort_key_func,
        reverse=is_descending
    )
    
    folder_name = os.path.basename(os.path.normpath(root_folder))
    timestamp = datetime.datetime.now()
    report_format = args.format

    try:
        if report_format in ['csv', 'all']:
            csv_output_filename = f"{folder_name}_video_duration.csv"
            csv_output_path = os.path.join(root_folder, csv_output_filename)

            write_csv_report(sorted_data, csv_output_path, root_folder, total_videos, success_count, failed_videos_data, timestamp)
            print(f"\n{ui['green']}Success! CSV file saved to:{ui['reset']}\n{ui['cyan']}{csv_output_path}{ui['reset']}")
            
            if failed_count > 0 and report_format != 'all':
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos. Check the 'FAILED' rows in the CSV.{ui['reset']}")

        if report_format in ['json', 'all']:
            json_output_filename = f"{folder_name}_video_duration.json"
            json_output_path = os.path.join(root_folder, json_output_filename)

            write_json_report(sorted_data, json_output_path, total_videos, success_count, failed_videos_data, timestamp)
            print(f"\n{ui['green']}Success! JSON file saved to:{ui['reset']}\n{ui['cyan']}{json_output_path}{ui['reset']}")
            
            if failed_count > 0 and report_format != 'all':
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos. Check the 'failed_files' array in the JSON.{ui['reset']}")
            
        if report_format in ['txt', 'all']:
            txt_output_filename = f"{folder_name} - Video Duration.txt"
            txt_output_path = os.path.join(root_folder, txt_output_filename)

            failed_videos_report_filename = f"{folder_name} - Failed Videos.txt"
            failed_videos_report_path = os.path.join(root_folder, failed_videos_report_filename)

            txt_report_template = 'detailed' if report_format == 'all' else args.template

            report_content, failed_videos_report_content = write_txt_and_failed_videos_report(
                sorted_data,
                txt_output_path,
                txt_report_template,
                failed_videos_data,
                failed_videos_report_path,
                timestamp,
                args.include_size_txt
            )

            print(f"\n{ui['yellow']}--- File Preview ---{ui['reset']}")
            print(report_content)
            print(f"\n{ui['green']}Success! Text file saved to:{ui['reset']}\n{ui['cyan']}{txt_output_path}{ui['reset']}")

            if failed_count > 0:
                print(f"\n{ui['yellow']}[!] NOTE: Scanning failed for {failed_count} videos.{ui['reset']}")
                print(f"\n{ui['yellow']}--- Failed Videos File Preview ---{ui['reset']}")
                print(failed_videos_report_content)
                print(f"\n{ui['yellow']}Failed videos file has been saved to:\n{ui['cyan']}{failed_videos_report_path}{ui['reset']}")

                if report_format == 'all':
                    print(f"\n{ui['yellow']}Failed videos and error messages can be found here in csv, json:{ui['reset']}")
                    print(f"{ui['yellow']}-'FAILED' rows in CSV.{ui['reset']}")
                    print(f"{ui['yellow']}-'failed_videos' array in JSON.{ui['reset']}")

    except Exception as e:
        print(f"\n{ui['red']}ERROR: Could not save the file. Reason: {e}{ui['reset']}")

if __name__ == "__main__":
    main()