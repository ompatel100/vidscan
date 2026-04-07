import os
import random
import subprocess
import argparse
import shutil
import math
import sys

FFMPEG_PATH = shutil.which('ffmpeg')
FFPROBE_PATH = shutil.which("ffprobe")

FORMATS = ["mp4_start", "mp4_end", "mkv"]

def parse_formats(format_str):
    formats = []
    weights = []
    
    if ':' not in format_str:
        raw_formats = format_str.split(',')
        formats = [f.strip().lower() for f in raw_formats]
        weights = [100.0 / len(formats)] * len(formats)
        return formats, weights

    parts = format_str.split(',')
    for part in parts:
        if ':' not in part:
            print(f"ERROR: Invalid syntax '{part}'. Provide 'format:weight'.")
            sys.exit(1)
        fmt, weight = part.split(':')
        formats.append(fmt.strip().lower())
        weights.append(float(weight))
        
    return formats, weights

def generate_seed_video(output_path, target_size_mb, format):
    if format not in FORMATS:
        print(f"ERROR: Format not supported '{format}'")
        print(f"Supported: {FORMATS}")
        sys.exit(1)

    ext = ".mp4" if "mp4" in format else ".mkv"
    
    movflags = []
    if format == "mp4_start":
        movflags = ["-movflags", "+faststart"]        

    print(f"Generating Seed Video ({format}): Target ~{target_size_mb} MB")
    
    if target_size_mb <= 50:
        duration_sec = str(max(1, round(target_size_mb / 0.25)))
        
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "nullsrc=s=640x360:r=30",
            "-vf", "noise=alls=100:allf=t+u",
            "-t", duration_sec,
            "-c:v", "libx264",
            "-b:v", "2M", "-maxrate", "2M", "-bufsize", "1M"
        ]
        cmd.extend(movflags)
        cmd.append(output_path)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    else:
        temp_video = f"temp_video{ext}"
        
        if not os.path.exists(temp_video):
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=640x360:r=30",
                "-vf", "noise=alls=100:allf=t+u", "-t", "10",
                "-c:v", "libx264", "-b:v", "2M", "-maxrate", "2M", "-bufsize", "1M",
                temp_video
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        temp_video_size_mb = os.path.getsize(temp_video) / (1024 * 1024)
        loop_count = max(0, round(target_size_mb / temp_video_size_mb) - 1)

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", temp_video,
            "-c", "copy"
        ]
        cmd.extend(movflags)
        cmd.append(output_path)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(output_path):
        print(f"ERROR: Failed to generate for {output_path}")
        sys.exit(1)

def verify_seed_video(video_path):
    cmd = [
        FFPROBE_PATH, 
        "-v", "error", 
        "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        video_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            return False
            
        duration = float(result.stdout.strip())
        if duration > 0:
            return True
        return False
    except Exception:
        return False

def manual_copy(src_path, dest_path, chunk_size=1024*1024*8):
    with open(src_path, 'rb') as fsrc:
        with open(dest_path, 'wb') as fdest:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdest.write(chunk)

def build_directory_tree(root_dir, max_depth, max_branch):    
    folders = [root_dir]
    current_depth_folders = [root_dir]
    
    if max_depth == 0:
        return folders
        
    for depth in range(1, max_depth + 1):
        next_depth_folders = []
        for parent in current_depth_folders:
            for i in range(random.randint(1, max_branch)):
                folder_name = f"Folder_{depth}_{i}"
                path = os.path.join(parent, folder_name)
                os.makedirs(path, exist_ok=True)
                folders.append(path)
                next_depth_folders.append(path)
        current_depth_folders = next_depth_folders
        
    return folders

def main():
    parser = argparse.ArgumentParser(
        description="VidScan Benchmark Data Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-c', '--count',
        type=int,
        default=100,
        help="Number of videos per copy"
    )
    parser.add_argument(
        '-s', '--size',
        type=float,
        default=50.0,
        help="Size in MB per video"
    )
    parser.add_argument(
        '-f', '--formats',
        type=str,
        default="mp4_start:40,mp4_end:40,mkv:20", 
        help=f"Formats with weights"
    )
    parser.add_argument(
        '--max-depth',
        type=int,
        default=3,
        help="Maximum nesting depth for folder"
    )
    parser.add_argument(
        '--max-branch',
        type=int,
        default=3,
        help="Maximum number of subfolders per folder"
    )
    parser.add_argument(
        '--copies',
        type=int,
        default=1,
        help="Number of copies to generate of benchmark data folder"
    )
    parser.add_argument(
        '-d', '--dest',
        type=str,
        default="VidScan_Benchmark_Data",
        help="Destination folder name"
    )
    args = parser.parse_args()

    if not FFMPEG_PATH or not FFPROBE_PATH:
        print("\n--- ERROR: FFmpeg not found in system PATH ---")
        print("Install FFmpeg from https://ffmpeg.org/download.html and add it to your system's PATH.")
        sys.exit(1)
    
    try:
        subprocess.run(
            [FFMPEG_PATH, "-version"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            check=True
        )
        subprocess.run(
            [FFPROBE_PATH, "-version"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            check=True
        )
    except Exception as e:
        print(f"ERROR: FFmpeg and ffprobe were found, but failed to execute. {e}")
        sys.exit(1)

    formats, weights = parse_formats(args.formats)
    total_weight = sum(weights)

    if not math.isclose(total_weight, 100.0, rel_tol=1e-4):
        print(f"ERROR: Invalid weights. Must add up to 100. Input weights: '{args.formats}'")
        sys.exit(1)

    print("------------- CONFIGURATION -------------")
    print(f"Videos per copy : {args.count}")
    print(f"Size per video  : ~{args.size} MB/file")
    print(f"Formats         : {list(zip(formats, weights))}")
    print(f"Max Depth       : {args.max_depth}")
    print(f"Max Branch      : {args.max_branch}")
    print(f"Total Copies    : {args.copies}")
    print("-----------------------------------------")

    required_mb = args.count * args.size * args.copies
    required_bytes = required_mb * 1024 * 1024 
    required_gb = required_mb / 1024

    _, _, free = shutil.disk_usage(os.getcwd())
    free_gb = free / (1024 * 1024 * 1024)

    print(f"\n-------- DISK SPACE --------")
    print(f"Required Space: ~{required_gb:.2f} GB")
    print(f"Available Space: {free_gb:.2f} GB")
    print(f"-----------------------------\n")

    if required_bytes > free:
        print(f"\nERROR: Insufficient disk space!")
        print(f"Need ~{required_gb:.2f} GB, but have {free_gb:.2f} GB available.")
        sys.exit(1)

    prompt = input(f"WARNING: This will generate ~{required_gb:.2f} GB of data. Continue? [y/N]: ")
    if prompt.lower() not in ['y', 'yes']:
        print("No files were created. Aborting... ")
        sys.exit(0)
    
    target_path = os.path.abspath(os.path.expanduser(args.dest))

    system_root = os.path.abspath(os.sep)
    home_dir = os.path.abspath(os.path.expanduser('~'))
    current_dir = os.path.abspath(os.getcwd())

    restrict_paths = [system_root, home_dir, current_dir]
    
    if target_path in restrict_paths:
        print(f"\n[!]'{target_path}' is a system or working directory.")
        print("Aborting...")
        sys.exit(1)

    if os.path.exists(target_path):
        if os.path.isdir(target_path) and len(os.listdir(target_path)) > 0:
            print(f"\nWARNING: The destination '{target_path}' already exists and contains files.")
            print("Continuing will PERMANENTLY DELETE everything inside it.")
            prompt = input("Are you absolutely sure you want to delete this folder? [y/N]: ")
            if prompt.lower() not in ['y', 'yes']:
                print("Not deleted. Aborting...")
                sys.exit(0)
            
            shutil.rmtree(target_path)
    
    os.makedirs(target_path, exist_ok=True)

    seed_videos = {}

    try:
        print("\nGenerating Seed Videos...\n")
        for fmt in formats:
            seed_video_path = f"seed_video_{fmt}{'.mp4' if 'mp4' in fmt else '.mkv'}"
            generate_seed_video(seed_video_path, args.size, fmt)
            seed_videos[fmt] = seed_video_path

        print("\nValidating Seed Videos...")
        for fmt, seed_video_path in seed_videos.items():
            if not os.path.exists(seed_video_path):
                print(f"ERROR: Failed to generate '{seed_video_path}'")
                sys.exit(1)
            
            if not verify_seed_video(seed_video_path):
                print(f"ERROR: '{seed_video_path}' generated, but container is corrupted!")
                print("FFmpeg failed to write valid video headers. Aborting...")
                sys.exit(1)
            
        print("\nBuilding Directory Tree and Copies...")
        bytes_written = 0

        for copy_idx in range(1, args.copies + 1):
            run_dir = os.path.join(target_path, f"Run_{copy_idx}")
            
            folders = build_directory_tree(run_dir, args.max_depth, args.max_branch)
            
            print(f"\nGenerating Folder: {run_dir}")
            for i in range(1, args.count + 1):
                target_folder = random.choice(folders)
                chosen_format = random.choices(formats, weights=weights, k=1)[0]

                ext = ".mp4" if "mp4" in chosen_format else ".mkv"
                file_name = f"Vid_{i:04d}_{chosen_format}{ext}"
                video_dest_path = os.path.join(target_folder, file_name)
                video_src_path = seed_videos[chosen_format]

                manual_copy(video_src_path, video_dest_path)
                bytes_written += os.path.getsize(video_dest_path)
                
                sys.stdout.write(f"\rProgress: [{i}/{args.count}] files.")
                sys.stdout.flush()

        print(f"\n\nSUCCESS! Generated {args.copies} data folders.")
        print(f"Total size on disk: {(bytes_written / (1024 * 1024 * 1024)):.2f} GB.")

    finally:
        print("\nDeleting seed videos...")
        for file in list(seed_videos.values()):
            if os.path.exists(file):
                os.remove(file)
        for ext in ['.mp4', '.mkv']:
            temp_file = f"temp_video{ext}"
            if os.path.exists(temp_file):
                os.remove(temp_file)

if __name__ == "__main__":
    main()