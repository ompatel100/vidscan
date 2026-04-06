import os
import sys
import subprocess
import time
import csv
import json
import random
import argparse
import datetime

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(CURR_DIR, "..", ".."))

DEFAULT_VIDSCAN_PATH = os.path.join(ROOT_DIR, "cli", "vidscan.py") 
DEFAULT_BENCHMARK_DATA_DIR = os.path.join(ROOT_DIR, "VidScan_Benchmark_Data")

OUTPUT_CSV  = os.path.join(CURR_DIR, "cli_benchmark.csv")

def main():
    parser = argparse.ArgumentParser(
        description="VidScan CLI Benchmark",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-w", "--workers", 
        nargs="+", 
        type=int, 
        default=[1, 2, 4, 8, 16, 32, 64],
        help="Space separated list of workers (e.g., -w 1 2 4)"
    )
    parser.add_argument(
        "-v", "--videos", 
        type=int, 
        default=100,
        help="Number of videos per Run folder"
    )
    parser.add_argument(
        "-c", "--cooldown", 
        type=int, 
        default=5,
        help="Cooldown in seconds between benchmark runs"
    )
    parser.add_argument(
        "--bench-dir",
        type=str,
        default=DEFAULT_BENCHMARK_DATA_DIR,
        help="Path to benchmark data folder")
    parser.add_argument(
        "--vidscan",
        type=str,
        default=DEFAULT_VIDSCAN_PATH,
        help="Path to vidscan.py"
    )
    args = parser.parse_args()

    CLI_COMMAND = [sys.executable, args.vidscan]

    workers_shuffled = args.workers.copy()
    random.shuffle(workers_shuffled)

    print("=" * 60)
    print("VIDSCAN CLI BENCHMARK")
    print("=" * 60)
    print(f"CPU Logical Cores: {os.cpu_count()}")

    if not os.path.exists(args.vidscan):
        print(f"\nERROR: Could not find '{args.vidscan}'.")
        print("Check the location for vidscan.py")
        sys.exit(1)

    if not os.path.exists(args.bench_dir):
        print(f"\nERROR: Benchmark folder '{args.bench_dir}' not found.")
        print("Please generate benchmark folder using generate_benchmark.py first.")
        sys.exit(1)

    for i in range(1, len(workers_shuffled) + 1):
        run_folder = os.path.join(args.bench_dir, f"Run_{i}")
        if not os.path.exists(run_folder):
            print(f"\nERROR: Folder '{run_folder}' not found in benchmark data folder.")
            print("Please provide correct --workers or generate desired benchmark data first.")
            sys.exit(1)

    print("-" * 60)
    print(f"{'RUN':<5} | {'FOLDER':<8} | {'THREADS':<8} | {'TIME':<8} | {'STATUS'}")
    print("-" * 60)

    results = []

    for i, workers in enumerate(workers_shuffled, 1):
        bench_data_folder = os.path.join(args.bench_dir, f"Run_{i}")
        folder_name = os.path.basename(bench_data_folder)
        
        cmd = CLI_COMMAND + ["-w", str(workers), "-f", "json", bench_data_folder]
        
        print(f"{i:<5} | Run_{i:<4} | -w {workers:<5} | ", end="", flush=True)

        start_time = time.perf_counter()
        
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        
        end_time = time.perf_counter()
        duration = end_time - start_time

        if result.returncode != 0:
            print(f"{'---':<8} | FAILED (Exit {result.returncode})")
            results.append((workers, "FAILED", 0, 0, 0))
        else:
            output_json_name = f"{folder_name} - Video Duration.json"
            json_path = os.path.join(bench_data_folder, output_json_name)
            
            if not os.path.exists(json_path):
                print(f"{'---':<8} | FAILED (JSON Report Not Found)")
                results.append((workers, "FAILED_NO_JSON", 0, 0, 0))
            else:
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    summary = data.get("summary", {})
                    discovered = summary.get("total_videos_discovered", 0)
                    success = summary.get("successful_videos", 0)
                    failed = summary.get("failed_videos", 0)
                    
                    time_str = f"{duration:.2f}s"
                    print(f"{time_str:<8} | ", end="")

                    if discovered != args.videos:
                        print(f"WARNING: Found {discovered}/{args.videos} videos")
                    elif failed > 0:
                        print(f"WARNING: Failed for {failed} videos")
                    else:
                        print(f"Success ({success}/{args.videos})")
                        
                    results.append((discovered, success, failed, workers, round(duration, 3), round(success/duration, 3),))
                    
                except Exception:
                    print(f"{'---':<8} | FAILED (JSON parse error)")
                    results.append((workers, "FAILED_JSON_PARSE", 0, 0, 0))

        if i < len(workers_shuffled):
            time.sleep(args.cooldown)

    print("-" * 60)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    csv_exists = os.path.isfile(OUTPUT_CSV)

    results.sort(key=lambda x: x[0])

    print(f"\nExporting data to {OUTPUT_CSV}...")
    try:
        with open(OUTPUT_CSV, mode='a', newline='') as file:
            writer = csv.writer(file)
            if csv_exists:
                writer.writerow([])
            else:
                writer.writerow(["Timestamp", "Total_Discovered", "Successful", "Failed", "Threads", "Time_Seconds", "Successful_Per_Sec"])
            for row in results:
                writer.writerow([timestamp] + list(row))
        print(f"Export complete.")
    except Exception as e:
        print(f"Failed to write CSV: {e}")

if __name__ == "__main__":
    main()