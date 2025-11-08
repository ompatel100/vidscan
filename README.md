# VidScan

A high performance command line tool to analyze video libraries, calculate total durations across nested directories and generate text reports.

---

## Features

- **High Performance:** Uses concurrency to scan large folders much faster by processing multiple video files at the same time.
- **CLI:** You can change everything through command line. Give folder path, folders to exclude, number of parallel threads in the CLI itself.
- **Recursive Scanning:** Automatically scans all subfolders.
- **Text Report:** Generates a clean, readable text file that contains the total duration and video count for each folder, and the total duration for the root folder.

---

## Installation

This tool can read video durations in two different ways. You only need to follow **one** of the two options below.

- **For the fastest performance,** choose **Option 1**. This is the recommended method, it requires you to be comfortable installing FFmpeg and adding it to your system's PATH.
- **For the simplest setup,** choose **Option 2**. This method is a good alternative if you only plan to scan smaller folders and prefer a single `pip install` command.

The script will **automatically detect** which method you have installed. If it finds `ffprobe` (Option 1), it will use it. If not, it will look for `moviepy` (Option 2).

---

### **Option 1: Using ffprobe (Recommended)**

1. **Install Python (3.8+)** from [python.org](https://www.python.org/downloads/).
2. **Install FFmpeg** from the [official website](https://ffmpeg.org/download.html).
3. **Add the FFmpeg `bin` folder** (which contains `ffprobe.exe`) to your **system's PATH**.

You do not need to install any Python packages from `requirements.txt` if you use this method.

### **Option 2: Using moviepy (Slower)**

1. **Install Python (3.8+)** from [python.org](https://www.python.org/downloads/).
2. **Create a Virtual Environment (Optional but Recommended):**

    ```bash
    cd /Path/To/Project/Folder
    python -m venv venv
    ./venv/Scripts/activate
    ```

3. **Install Dependencies:**
    Run this command to install `moviepy`:

    ```bash
    pip install -r requirements.txt
    ```

---

## Usage

You can run the script from your terminal. The only required argument is the path to the folder you want to scan.

### Default Scan

To scan a folder, simply provide the full path. If the path contains spaces, make sure to enclose it in quotes.

```bash
python vidscan.py "D:\Path\To\Your\Folder"
```

The script will scan the folder, using the defaults, and save the report inside that same directory.

### Excluding Folders

Use the `-e` or `--exclude` flag to ignore one or more folders.

```bash
python vidscan.py "D:\Path\To\Your\Folder" -e "Folder 1" "Folder 2"
```

This will skip folders "Folder 1", "Folder 2"

### Setting Worker Threads

Manually set the number of parallel threads with the `--workers` (or `-w`) flag.

```bash
python vidscan.py "D:\Path\To\Your\Folder" -w 16
```

Run the scan using a maximum of 16 threads

### Help

You can see the full list of options by running the script with the `-h` or `--help` flag:

```bash
python vidscan.py --help
```

This will display the following:

```
usage: vidscan.py [-h] [-w WORKERS] [-e EXCLUDE [EXCLUDE ...]] folder_path

A script to calculate video durations across nested directories.

positional arguments:
  folder_path           The full path to the main folder you want to scan.

options:
  -h, --help            show this help message and exit
  -w, --workers WORKERS
                        Number of parallel threads to use. (default:
                        dynamically calculated for your system)
  -e, --exclude EXCLUDE [EXCLUDE ...]
                        A space separated list of folder names to exclude
                        from the scan (case sensitive).
```

---

## Example Output

The generated report file will look like this:

```text
Video Duration
========================================
Folder: Folder Name 1
  -> Videos: 7 | Duration: 01:11:28
----------------------------------------
Folder: Folder Name 2
  -> Videos: 5 | Duration: 00:54:47
----------------------------------------
                   .
                   .
                   .
----------------------------------------
Folder: Folder Name 67
  -> Videos: 12 | Duration: 02:08:15
----------------------------------------
Folder: Folder Name 68
  -> Videos: 10 | Duration: 01:45:21
----------------------------------------
TOTALS
  -> Total Folders: 68
  -> Total Videos: 493
  -> Total Duration: 98:37:44
========================================
```
