import os
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = "VidScan_Benchmark_Data"
MAX_DEPTH = 4
TOTAL_FILES = 1000
FFMPEG_CHECK = "ffmpeg -version"

FORMAT_WEIGHTS = ['.mp4']

def check_ffmpeg():
    try:
        subprocess.run(FFMPEG_CHECK, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def create_dummy_video(file_info):
    path, duration_sec = file_info
    
    cmd = (
        f'ffmpeg -y -f lavfi -i color=c=black:s=16x16:r=1 '
        f'-t {duration_sec} -c:v libx264 -preset ultrafast -crf 51 "{path}"'
    )
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def generate_structure():
    if not check_ffmpeg():
        print("Error: ffmpeg not installed or not in path")
        return

    if os.path.exists(ROOT_DIR):
        print(f"Directory '{ROOT_DIR}' already exists")
        return

    print(f"Generating {TOTAL_FILES} videos...")

    os.makedirs(ROOT_DIR)
    folders = [ROOT_DIR]

    current_depth_folders = [ROOT_DIR]
    for depth in range(1, MAX_DEPTH + 1):
        next_depth_folders = []
        for parent in current_depth_folders:
            for i in range(random.randint(2, 4)):
                folder_name = f"Folder_{depth}_{i+1}"
                path = os.path.join(parent, folder_name)
                os.makedirs(path, exist_ok=True)
                folders.append(path)
                next_depth_folders.append(path)
        current_depth_folders = next_depth_folders

    jobs = []
    for i in range(1, TOTAL_FILES + 1):
        target_folder = random.choice(folders)
        ext = random.choice(FORMAT_WEIGHTS)
        file_name = f"Bench_Video_{i}{ext}"
        full_path = os.path.join(target_folder, file_name)
        duration = random.randint(10, 120)
        jobs.append((full_path, duration))

    completed = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        for _ in executor.map(create_dummy_video, jobs):
            completed += 1
            if completed % 100 == 0:
                print(f"Generated {completed}/{TOTAL_FILES} files")

    print(f"\nCreated '{ROOT_DIR}' with {TOTAL_FILES} videos")

if __name__ == "__main__":
    generate_structure()