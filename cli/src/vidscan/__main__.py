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
from dataclasses import dataclass, asdict
from typing import Dict, Iterator, List, Any, Tuple, Set, no_type_check

# ==================================================================================
# CONSTANTS
# ==================================================================================

DEFAULT_VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.wmv', '.flv', '.mpg', '.mpeg'}

DEFAULT_W = min(4, os.cpu_count() or 1)

DEFAULT_W_SSD = min(32, os.cpu_count() or 1)

MAX_W = 128

FFPROBE_PATH = shutil.which('ffprobe') or ""

# ==================================================================================
# UTILS
# ==================================================================================

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

def format_windows_max_path(path: str) -> str:
    if os.name != 'nt':
        return os.path.abspath(path)

    path = os.path.abspath(path)
    
    # Path is safe if < 260 (Windows MAX_PATH)
    if len(path) < 260:
        return path

    # Add extended length prefix for long path
    if not path.startswith('\\\\?\\'):
        if path.startswith('\\\\'):
            # Network/UNC path
            path = f"\\\\?\\UNC\\{path[2:]}"
        else:
            # Local/Mapped Path
            path = f"\\\\?\\{path}"
            
    return path

# ==================================================================================
# UI
# ==================================================================================

@dataclass(frozen=True)
class UI:
    __slots__ = (
        'is_terminal', 'bar_fill', 'bar_empty', 'spinner',
        'color_red', 'color_yellow', 'color_green', 'color_cyan', 'color_reset'
    )
    
    is_terminal: bool
    bar_fill: str
    bar_empty: str
    spinner: Iterator[str]
    color_red: str
    color_yellow: str
    color_green: str
    color_cyan: str
    color_reset: str

    def error(self, text: Any) -> str:
        return f"{self.color_red}{text}{self.color_reset}"

    def warning(self, text: Any) -> str:
        return f"{self.color_yellow}{text}{self.color_reset}"

    def success(self, text: Any) -> str:
        return f"{self.color_green}{text}{self.color_reset}"

    def info(self, text: Any) -> str:
        return f"{self.color_cyan}{text}{self.color_reset}"
    
def get_ui() -> UI:
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

    return UI(
        is_terminal=is_terminal,
        bar_fill=bar_fill,
        bar_empty=bar_empty,
        spinner=itertools.cycle(spinner),
        color_red=red,
        color_yellow=yellow,
        color_green=green,
        color_cyan=cyan,
        color_reset=reset
    )

# ==================================================================================
# MODELS
# ==================================================================================

@dataclass(frozen=True)
class VideoFile:
    __slots__ = ('name', 'duration', 'mtime', 'size')

    name: str
    duration: float
    mtime: float
    size: int

@dataclass(frozen=True)
class FailedVideo:
    __slots__ = ('path', 'error', 'size')
    
    path: str
    error: str
    size: int

@dataclass(frozen=True)
class DiscoveredFile:
    __slots__ = ('path', 'dirpath', 'name', 'mtime', 'size', 'error')

    path: str
    dirpath: str
    name: str
    mtime: float
    size: int
    error: str

@dataclass
class FolderData:
    __slots__ = ('path', 'videos', 'total_seconds', 'total_size', 'video_count', 'last_modified')
    
    path: str
    videos: List[VideoFile]
    total_seconds: float
    total_size: int
    video_count: int
    last_modified: float
    
@dataclass(frozen=True)
class ScanResult:
    folders: List[FolderData]
    total_videos: int
    success_count: int
    failed_videos_data: List[FailedVideo]
    
# ==================================================================================
# SCANNER
# ==================================================================================

def stream_video_files(root_folder: str, video_extensions: Set[str], excluded_folders: Set[str]) -> Iterator[DiscoveredFile]:
    stack = [root_folder]
    while stack:
        current_dir = stack.pop()

        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in excluded_folders:
                            stack.append(entry.path)
                    
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in video_extensions:
                            try:
                                yield DiscoveredFile(
                                    path=entry.path, 
                                    dirpath=current_dir, 
                                    name=entry.name, 
                                    mtime=entry.stat().st_mtime, 
                                    size=entry.stat().st_size,
                                    error=""
                                )
                                
                            except OSError as e:
                                yield DiscoveredFile(
                                    path=entry.path, 
                                    dirpath=current_dir, 
                                    name=entry.name, 
                                    mtime=0.0, 
                                    size=0, 
                                    error=f"OS Error: {str(e)}"
                                )
        except OSError:
            continue

def get_video_duration(video_path: str, ffprobe_timeout_sec: float) -> Tuple[float, str]:
    try:
        command = [ # type: ignore
            FFPROBE_PATH, 
            "-v", "error", 
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", 
            video_path
        ]
        
        run_kwargs = { # type: ignore
            "capture_output": True,
            "text": True,
            "check": True,
            "timeout": ffprobe_timeout_sec
        }

        if os.name == 'nt':
            run_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(command, **run_kwargs) # type: ignore
        
        return float(result.stdout), "" # type: ignore
        
    except subprocess.TimeoutExpired:
        return 0.0, f"Process timed out after {ffprobe_timeout_sec} seconds"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Corrupted or unreadable file"
        return 0.0, error_msg
    except Exception as e:
        return 0.0, str(e)

def scan_videos_concurrently(
    root_folder: str,
    video_extensions: Set[str],
    excluded_folders: Set[str],
    num_workers: int,
    ffprobe_timeout_sec:float,
    fast_start_mode:bool,
    ui: UI
) -> ScanResult:

    folder_data: Dict[str, FolderData] = {}
    total_videos = 0

    start_time = time.time()

    if not fast_start_mode:
        print(ui.warning("Scanning directory structure..."))
        total_videos = sum(1 for _ in stream_video_files(root_folder, video_extensions, excluded_folders))

        if total_videos == 0:
            return ScanResult(
            folders=list(folder_data.values()),
            total_videos=0,
            success_count=0,
            failed_videos_data=[]
        )
        
        print(f"Found {ui.info(total_videos)} video files.", end=" ")

    print(f"Processing with {num_workers} workers...")
    
    videos_processed = 0
    failed_videos_data: List[FailedVideo] = []

    last_print_time = 0.0
    progress_update_interval = 0.1

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=num_workers)
    future_to_video: Dict[concurrent.futures.Future[Tuple[float, str]], DiscoveredFile] = {}

    try:
        for file_metadata in stream_video_files(root_folder, video_extensions, excluded_folders):
            
            if file_metadata.error:
                failed_videos_data.append(
                    FailedVideo(
                        path=file_metadata.path, 
                        error=file_metadata.error,
                        size=file_metadata.size
                    )
                )
                continue
                
            future = executor.submit(get_video_duration, file_metadata.path, ffprobe_timeout_sec)
            future_to_video[future] = file_metadata

        for future in concurrent.futures.as_completed(future_to_video):
            file_metadata = future_to_video[future]
            duration, error_msg = future.result()
            
            videos_processed += 1

            if duration > 0:
                if file_metadata.dirpath not in folder_data:
                    folder_data[file_metadata.dirpath] = FolderData(
                        path=file_metadata.dirpath,
                        videos=[],
                        total_seconds=0.0,
                        total_size=0,
                        video_count=0,
                        last_modified=0.0
                    )
                
                folder_data[file_metadata.dirpath].videos.append(
                    VideoFile(
                        name=file_metadata.name, 
                        duration=duration, 
                        mtime=file_metadata.mtime, 
                        size=file_metadata.size
                    )
                )
            else:
                failed_videos_data.append(
                    FailedVideo(
                        path=file_metadata.path, 
                        error=error_msg,
                        size=file_metadata.size
                    )
                )

            if ui.is_terminal:
                current_time = time.time()
                if current_time - last_print_time >= progress_update_interval or videos_processed == total_videos:
                    if fast_start_mode:
                        print(f"\r[{next(ui.spinner)}] Videos processed: {ui.info(videos_processed)}", end="", flush=True)
                    else:
                        progress = videos_processed / total_videos
                        bar_length = 40
                        filled = int(bar_length * progress)
                        
                        bar = (ui.bar_fill * filled) + (ui.bar_empty * (bar_length - filled))
                        percent = int(progress * 100)

                        print(f"\rProgress: [{bar}] {percent}% ({videos_processed}/{total_videos})", end="", flush=True)

                    last_print_time = current_time

    except KeyboardInterrupt:
        print(ui.warning("\n\n[!] Exiting gracefully"))
        print(ui.info("Cancelling and saving partial data..."))

    finally:
        if sys.version_info >= (3, 9):
            executor.shutdown(wait=False, cancel_futures=True)
            
        else:
            for future in future_to_video:
                future.cancel()
            executor.shutdown(wait=False)

    print(f"\nProcessing complete in {time.time() - start_time:.2f} seconds.")

    success_count = 0
    for folder_stats in folder_data.values():
        total_seconds, total_size, m_time = 0.0, 0, 0.0
        
        for video in folder_stats.videos:
            total_seconds += video.duration
            total_size += video.size
            if video.mtime > m_time:
                m_time = video.mtime

        folder_stats.total_seconds = total_seconds
        folder_stats.total_size = total_size
        folder_stats.last_modified = m_time
        folder_stats.video_count = len(folder_stats.videos)
        success_count += folder_stats.video_count

    if fast_start_mode:
        total_videos = videos_processed

    return ScanResult(
        folders=list(folder_data.values()),
        total_videos=total_videos,
        success_count=success_count,
        failed_videos_data=failed_videos_data
    )

# ==================================================================================
# REPORTS
# ==================================================================================

@no_type_check
def get_sorted_data(folders: List[FolderData], sort_by: str, reverse: bool) -> List[FolderData]:
    sort_keys = {
        'name':     lambda f: os.path.basename(f.path).lower(),
        'duration': lambda f: f.total_seconds,
        'videos':   lambda f: f.video_count,
        'size':     lambda f: f.total_size,
        'date':     lambda f: f.last_modified
    }

    key_func = sort_keys.get(sort_by, lambda f: f.path)
    
    return sorted(folders, key=key_func, reverse=reverse)

def get_txt_report_summary_lines(sorted_data: List[FolderData], failed_count: int, include_size: bool) -> List[str]:
    divide_line_length = 60 if include_size else 45

    lines = [
        "Video Duration (Summary)", 
        "=" * divide_line_length,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_vid_size = 0
    grand_total_videos = 0

    for folder in sorted_data:
        folder_name = os.path.basename(folder.path) or os.path.basename(os.path.normpath(folder.path))

        lines.append(f"Folder: {folder_name}")

        size_str = f" | Size: {format_bytes(folder.total_size)}" if include_size else ""
        lines.append(f"  -> Videos: {folder.video_count:>3} | Duration: {format_seconds_hms(folder.total_seconds)}{size_str}")
        lines.append("-" * divide_line_length)
        
        grand_total_seconds += folder.total_seconds
        grand_total_vid_size += folder.total_size
        grand_total_videos += folder.video_count
    
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

def get_txt_report_detailed_lines(sorted_data: List[FolderData], failed_count: int, include_size: bool) -> List[str]:
    divide_line_length = 75 if include_size else 60

    lines = [
        "Video Duration (Detailed)", 
        "=" * divide_line_length,
        ""
    ]
    
    grand_total_seconds = 0.0
    grand_total_vid_size = 0
    grand_total_videos = 0

    for folder in sorted_data:
        folder_name = os.path.basename(folder.path) or os.path.basename(os.path.normpath(folder.path))

        lines.append(f"Folder: {folder_name}")
        
        sub_total_size_str = f" | Subtotal Size: {format_bytes(folder.total_size)}" if include_size else ""
        lines.append(f"  [ Videos: {folder.video_count:>3} | Subtotal Duration: {format_seconds_hms(folder.total_seconds)}{sub_total_size_str} ]")
        
        sorted_videos = sorted(folder.videos, key=lambda x: x.name)
        for vid_info in sorted_videos:
            size_str = f" | {format_bytes(vid_info.size)}" if include_size else ""
            lines.append(f"    - {vid_info.name} ({format_seconds_hms(vid_info.duration)}{size_str})")
            
        lines.append("-" * divide_line_length)
        
        grand_total_seconds += folder.total_seconds
        grand_total_vid_size += folder.total_size
        grand_total_videos += folder.video_count
    
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

def get_failed_videos_report_lines(failed_videos_data: List["FailedVideo"]) -> List[str]:
    divide_line_length = 60

    lines = [
        "FAILED VIDEO FILES",
        "=" * divide_line_length,
        "These videos could not be read by ffprobe.",
        ""
    ]

    total_failed_vid_size = 0

    for failed_video in sorted(failed_videos_data, key=lambda x: x.path):
        lines.append(f"- {failed_video.path}")
        lines.append(f"  Reason: {failed_video.error}")
        lines.append(f"  Size: {format_bytes(failed_video.size)}\n")

        total_failed_vid_size += failed_video.size

    totals_lines = [
        "\nTOTALS",
        f"  -> Total Failed Videos: {len(failed_videos_data)}",
        f"  -> Total Size: {format_bytes(total_failed_vid_size)}"
    ]

    totals_lines.append("=" * divide_line_length)
    lines.extend(totals_lines)
    
    return lines

def write_txt_and_failed_videos_report(
    sorted_data: List[FolderData], 
    output_path: str, 
    template: str, 
    failed_videos_data: List["FailedVideo"], 
    failed_videos_report_path: str, 
    timestamp: datetime.datetime, 
    include_size: bool
) -> Tuple[str, str]:
    
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

def write_csv_report(
    sorted_data: List[FolderData], 
    output_path: str, 
    root_folder: str, 
    total_videos: int, 
    success_count: int, 
    failed_videos_data: List[FailedVideo], 
    timestamp: datetime.datetime
):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Folder Path', 'Relative Path', 'File Name', 'Duration (Seconds)', 'Duration (Formatted)', 'Size (Bytes)', 'Size (Formatted)'])
        
        total_vid_size_successful = 0
        for folder in sorted_data:
            try:
                relative_path = os.path.relpath(folder.path, root_folder)
            except ValueError:
                relative_path = folder.path
                
            sorted_videos = sorted(folder.videos, key=lambda x: x.name)
            
            for vid_info in sorted_videos:
                writer.writerow([
                    folder.path,
                    relative_path,
                    vid_info.name,
                    f"{vid_info.duration:.2f}",
                    format_seconds_hms(vid_info.duration),
                    vid_info.size,
                    format_bytes(vid_info.size)
                ])

            total_vid_size_successful += folder.total_size

        total_vid_size_failed = 0
        if failed_videos_data:
            for failed_video in sorted(failed_videos_data, key=lambda x: x.path):
                folder_path = os.path.dirname(failed_video.path)
                try:
                    relative_path = os.path.relpath(folder_path, root_folder)
                except ValueError:
                    relative_path = folder_path
                file_name = os.path.basename(failed_video.path)
                
                writer.writerow([
                    folder_path,
                    relative_path,
                    file_name,
                    'FAILED',
                    failed_video.error,
                    failed_video.size,
                    format_bytes(failed_video.size)
                ])

                total_vid_size_failed += failed_video.size

        writer.writerow([])
        writer.writerow(['--- SCAN SUMMARY ---', '', '', '', '', '', ''])
        writer.writerow(['Total Videos Discovered', total_videos, '', '', '', '', ''])
        writer.writerow(['Successful', success_count, '', '', '', '', ''])
        writer.writerow(['Failed', len(failed_videos_data), '', '', '', '', ''])
        writer.writerow(['Total Size (Successful Videos)', total_vid_size_successful, format_bytes(total_vid_size_successful), '', '', '', ''])
        writer.writerow(['Total Size (Failed Videos)', total_vid_size_failed, format_bytes(total_vid_size_failed), '', '', '', ''])
        writer.writerow(['Total Size (All Videos)', total_vid_size_successful + total_vid_size_failed, format_bytes(total_vid_size_successful + total_vid_size_failed), '', '', '', ''])
        writer.writerow(['Report Generated At', timestamp.strftime('%Y-%m-%d %H:%M:%S'), '', '', '', '', ''])

def write_json_report(
    sorted_data: List[FolderData], 
    output_path: str, 
    total_videos: int, 
    success_count: int, 
    failed_videos_data: List[FailedVideo], 
    timestamp: datetime.datetime
):
    total_vid_size_successful = 0
    total_seconds = 0
    details_list: List[Dict[str, Any]] = []
    
    for folder in sorted_data:
        videos_formatted: List[Dict[str, Any]] = []
        for video_data in sorted(folder.videos, key=lambda x: x.name):
            video_data_copy = asdict(video_data)
            video_data_copy['size_formatted'] = format_bytes(video_data.size)
            video_data_copy['duration_formatted'] = format_seconds_hms(video_data.duration)
            videos_formatted.append(video_data_copy)
        
        total_seconds += folder.total_seconds
        total_vid_size_successful += folder.total_size

        details_list.append({
            "folder_path": folder.path,
            "video_count": folder.video_count,
            "total_seconds": folder.total_seconds,
            "total_duration_formatted": format_seconds_hms(folder.total_seconds),
            "total_videos_size_bytes": folder.total_size,
            "total_videos_size_formatted": format_bytes(folder.total_size),
            "last_modified_timestamp": folder.last_modified,
            "last_modified_human": datetime.datetime.fromtimestamp(folder.last_modified).isoformat(),
            "videos": videos_formatted
        })
    
    total_vid_size_failed = 0
    failed_videos_formatted: List[Dict[str, Any]] = []
    
    for failed_video in sorted(failed_videos_data, key=lambda x: x.path):
        failed_video_copy = asdict(failed_video)
        failed_video_copy['size_formatted'] = format_bytes(failed_video.size)
        failed_videos_formatted.append(failed_video_copy)
        
        total_vid_size_failed += failed_video.size

    report_structure: Dict[str, Any] = {
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

# ==================================================================================
# CLI
# ==================================================================================

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
    try:
        parser = argparse.ArgumentParser(
            description="Scan media libraries across nested folders and generate reports.",
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
            help="Space separated list of folder names to exclude from the scan (case sensitive)."
        )
        parser.add_argument(
            "-ext", "--extensions",
            nargs='+',
            help=(
                "Space separated list of file extensions to scan (e.g. mp4 mkv webm).\n"
                f"(default: {DEFAULT_VIDEO_EXTENSIONS})."
            )
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
            print(ui.error("\nERROR: ffprobe not found in system PATH"))
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
            print(ui.error(f"ERROR: ffprobe was found, but failed to execute. {e}"))
            sys.exit(1)

        root_folder = format_windows_max_path(args.folder_path)

        if not os.path.isdir(root_folder):
            print(ui.error(f"ERROR: The path '{root_folder}' is not a valid directory."))
            sys.exit(1)

        excluded_folders = set(args.exclude)

        if args.extensions:
            video_extensions = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in args.extensions}
        else:
            video_extensions = DEFAULT_VIDEO_EXTENSIONS

        print(f"Scanning folder: {ui.info(root_folder)}")
        if excluded_folders:
            print(f"Excluding folders: {ui.info(', '.join(excluded_folders))}")

        scan_result = scan_videos_concurrently(
            root_folder,
            video_extensions,
            excluded_folders,
            args.workers,
            args.ffprobe_timeout,
            args.fast_start,
            ui
        )

        failed_count = len(scan_result.failed_videos_data)

        if not scan_result.folders:
            if failed_count > 0:
                print(ui.warning(f"\n[!] NOTE: Found {failed_count} videos, but all of them failed."))
            else:
                print(ui.warning("\nNo video files found with the default extensions:"))
                print(ui.info(', '.join(sorted(DEFAULT_VIDEO_EXTENSIONS))))
                print(f"To include other formats, or scan for specific formats only, please provide them in {ui.info('--extensions')} flag.")
                print(f"You can also change {ui.info('DEFAULT_VIDEO_EXTENSIONS')} at the top of the script permanently.")
            sys.exit(0)

        sorted_data: List[FolderData] = get_sorted_data(
        folders=scan_result.folders,
        sort_by=args.sort_by,
        reverse=(args.sort_order == 'desc')
        )
        
        folder_name = os.path.basename(os.path.normpath(root_folder))
        timestamp = datetime.datetime.now()
        report_format = args.format

        try:
            if report_format in ['csv', 'all']:
                csv_output_filename = f"{folder_name}_video_duration.csv"
                csv_output_path = os.path.join(root_folder, csv_output_filename)

                write_csv_report(
                    sorted_data,
                    csv_output_path,
                    root_folder,
                    scan_result.total_videos,
                    scan_result.success_count,
                    scan_result.failed_videos_data,
                    timestamp
                )
                print(ui.success("\nSuccess! CSV file saved to:"))
                print(ui.info(csv_output_path))
                
                if failed_count > 0 and report_format != 'all':
                    print(ui.warning(f"\n[!] NOTE: Scanning failed for {failed_count} videos. Check the 'FAILED' rows in the CSV."))

            if report_format in ['json', 'all']:
                json_output_filename = f"{folder_name}_video_duration.json"
                json_output_path = os.path.join(root_folder, json_output_filename)

                write_json_report(
                    sorted_data,
                    json_output_path,
                    scan_result.total_videos,
                    scan_result.success_count,
                    scan_result.failed_videos_data,
                    timestamp
                )
                print(ui.success(f"\nSuccess! JSON file saved to:"))
                print(ui.info(json_output_path))
                
                if failed_count > 0 and report_format != 'all':
                    print(ui.warning(f"\n[!] NOTE: Scanning failed for {failed_count} videos. Check the 'failed_files' array in the JSON."))
                
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
                    scan_result.failed_videos_data,
                    failed_videos_report_path,
                    timestamp,
                    args.include_size_txt
                )

                print(ui.warning("\n--- File Preview ---"))
                print(report_content)
                print(ui.success("\nSuccess! Text file saved to:"))
                print(ui.info(txt_output_path))

                if failed_count > 0:
                    print(ui.warning(f"\n[!] NOTE: Scanning failed for {failed_count} videos."))
                    print(ui.warning("\n--- Failed Videos File Preview ---"))
                    print(failed_videos_report_content)
                    print(ui.warning("\nFailed videos file has been saved to:"))
                    print(ui.info(failed_videos_report_path))

                    if report_format == 'all':
                        print(ui.warning("\nFailed videos and error messages can be found here in csv, json:"))
                        print(ui.warning("-'FAILED' rows in CSV."))
                        print(ui.warning("-'failed_videos' array in JSON."))

        except Exception as e:
            print(ui.error(f"\nERROR: Could not save the file. Reason: {e}"))

    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user")
        sys.exit(130)

if __name__ == "__main__":
    main()