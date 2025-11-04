import os
import shutil
import subprocess
import argparse
from typing import Dict, Any

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

def main():
    parser = argparse.ArgumentParser(
        description="A script to calculate video durations across nested directories."
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
        print("ffprobe not found in system PATH. Using moviepy (slower).")
        print("For faster performance, install FFmpeg and add it to your system's PATH.")

    folder_durations: Dict[str, Any] = {}

    for dirpath, dirs, filenames in os.walk(root_folder):
        dirs[:] = [d for d in dirs if d not in excluded_set]

        current_folder_seconds = 0.0
        video_count_in_folder = 0
        
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS:
                video_count_in_folder += 1
                full_path = os.path.join(dirpath, filename)
                duration = get_video_duration(full_path)
                
                current_folder_seconds += duration
        
        if video_count_in_folder > 0:
            folder_durations[dirpath] = (current_folder_seconds, video_count_in_folder)

    if not folder_durations:
        print(f"\nNo video files found with the configured extensions: {', '.join(sorted(list(VIDEO_EXTENSIONS)))}")
        print("To include other formats, please add them to the VIDEO_EXTENSIONS at the top of the script.")
        return

    report_lines = ["Video Duration", "=" * 40]
    grand_total_seconds = 0.0
    grand_total_videos = 0

    for folder, (total_seconds, video_count) in sorted(folder_durations.items()):
        folder_name = os.path.basename(folder)
        if not folder_name:
            folder_name = os.path.basename(os.path.normpath(folder))

        report_lines.append(f"Folder: {folder_name}")
        report_lines.append(f"  -> Videos: {video_count} | Duration: {format_seconds_hms(total_seconds)}")
        report_lines.append("-" * 40)
        
        grand_total_seconds += total_seconds
        grand_total_videos += video_count
    
    report_lines.append("TOTALS")
    report_lines.append(f"  -> Total Folders: {len(folder_durations)}")
    report_lines.append(f"  -> Total Videos: {grand_total_videos}")
    report_lines.append(f"  -> Total Duration: {format_seconds_hms(grand_total_seconds)}")
    report_lines.append("=" * 40)

    folder_name = os.path.basename(os.path.normpath(root_folder))
    output_filename = f"{folder_name} - Video Duration.txt"
    output_path = os.path.join(root_folder, output_filename)
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        print(f"\nSuccess! Text file saved to:\n{output_path}")
    except Exception as e:
        print(f"\nError: Could not save the file. Reason: {e}")

if __name__ == "__main__":
    main()