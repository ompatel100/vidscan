# VidScan

A high performance command line tool to analyze video libraries, calculate total durations across nested directories and generate flexible reports in text, csv, or json formats.

---

## Features

- **High Performance:** Uses concurrency to scan large folders much faster by processing multiple video files at the same time.
- **CLI:** You can change everything through command line. Give folder path, folders to exclude, number of parallel threads, report format and template, sort and order in the CLI itself.
- **Recursive Scanning:** Automatically scans all nested subfolders.
- **Flexible Output Formats:** Generate reports in `.txt`, `.csv` and `.json` formats.
- **Report Templates:** You can choose `summary` (folder totals only) or a `detailed` (file by file) template for text reports.
- **Sorting and Ordering:** Sort the results by folder `name`, `duration`, `videos` (count), or `date` (last modified), in ascending or descending order.

---

## Installation

1. **Install Python (3.8+)** from [python.org](https://www.python.org/downloads/).
2. **Get the Script:** Download the ZIP or clone the repository:

```bash
git clone https://github.com/ompatel100/vidscan.git
```

3. **Install FFmpeg** from [ffmpeg.org](https://ffmpeg.org/download.html).
4. **Add the FFmpeg `bin` folder** (which contains `ffprobe.exe`) to your **system's PATH**.

---

## Usage

You can run the script from your terminal. The only required argument is the path to the folder you want to scan.

### Default Scan

To scan a folder, simply provide the full path. If the path contains spaces, make sure to enclose it in quotes.

```bash
python vidscan.py "D:\Path\To\Your\Folder"
```

This command uses all the built in defaults for report:

- **Format:** `txt`
- **Template:** `summary`
- **Sort By:** `name`
- **Sort Order:** `asc`

The script will save the report `Folder Name - Video Duration.txt` inside that same directory.

### Excluding Folders

Use the `-e` or `--exclude` flag to ignore one or more folders.

Example: To skip folders "Folder 1", "Folder 2"

```bash
python vidscan.py "D:\Path\To\Your\Folder" -e "Folder 1" "Folder 2"
```

### Setting Worker Threads

Manually set the number of parallel threads with the `-w` or `--workers` flag. The default is dynamically calculated for your system

Example: To use a maximum of 16 threads

```bash
python vidscan.py "D:\Path\To\Your\Folder" -w 16
```

### Changing Output Format

Use the `-f` or `--format` flag. The default is `txt`.

```bash
python vidscan.py "D:\Path\To\Your\Folder" -f csv
```

```bash
python vidscan.py "D:\Path\To\Your\Folder" -f json
```

### Changing Report Template

Use the `-t` or `--template` flag to change the template for `txt` reports. The default is `summary`.

To set template to detailed

```bash
python vidscan.py "D:\Path\To\Your\Folder" -t detailed
```

### Sorting the Report

Use the `-sb` or `--sort-by` flag to sort the results and `-so` or `--sort-order` flag for sort order. The default is sorting by `name` in `asc` (ascending) order.

Example: Sort by the longest duration first

```bash
python vidscan.py "D:\Path\To\Your\Folder" -sb duration -so desc
```

Example: Sort by the highest video count first

```bash
python vidscan.py "D:\Path\To\Your\Folder" -sb videos -so desc
```

Example: Sort by the most recently modified folders first

```bash
python vidscan.py "D:\Path\To\Your\Folder" -sb date -so desc
```

### Help

You can see the full list of options by running the script with the `-h` or `--help` flag:

```bash
python vidscan.py --help
```

This will display the following:

```
usage: vidscan.py [-h] [-e EXCLUDE [EXCLUDE ...]] [-w WORKERS] [-f {txt,csv,json}] [-t {summary,detailed}]
                  [-sb {name,duration,videos,date}] [-so {asc,desc}]
                  folder_path

A high performance tool to calculate total video duration across nested directories.

positional arguments:
  folder_path           The full path to the main folder you want to scan.

options:
  -h, --help            show this help message and exit
  -e, --exclude EXCLUDE [EXCLUDE ...]
                        A space separated list of folder names to exclude from the scan (case sensitive).
  -w, --workers WORKERS
                        Number of parallel threads to use.
                        (default: dynamically calculated for your system)
  -f, --format {txt,csv,json}
                        Output file format (default: txt).
  -t, --template {summary,detailed}
                        Text report template (default: summary).
  -sb, --sort-by {name,duration,videos,date}
                        Sort folders by (default: name).
  -so, --sort-order {asc,desc}
                        Sort order (default: asc).
```

---

## Example Output

### Summary Report (Default)

The generated report file will look like this:

```text
Video Duration (Summary)
========================================
Folder: Folder Name 1
  -> Videos:   7 | Duration: 01:11:28
----------------------------------------
Folder: Folder Name 2
  -> Videos:   5 | Duration: 00:54:47
----------------------------------------
                 .
                 .
                 .
----------------------------------------
Folder: Folder Name 67
  -> Videos:  12 | Duration: 02:08:15
----------------------------------------
Folder: Folder Name 68
  -> Videos:  10 | Duration: 01:45:21
----------------------------------------

TOTALS
  -> Total Folders: 68
  -> Total Videos: 493
  -> Total Duration: 98:37:44
========================================
Generated on: 1991-08-25 20:57:08
```

### Detailed Report (`-t detailed`)

The detailed report shows every file within each folder:

```text
Video Duration (Detailed)
========================================
Folder: Folder Name 1
  [ Videos:   2 | Subtotal: 0:36:31 ]
    - Video Name 1.mp4 (0:14:52)
    - Video Name 2.mp4 (0:22:39)
----------------------------------------
Folder: Folder Name 2
  [ Videos:   3 | Subtotal: 0:48:19 ]
    - Video Name 3.mp4 (0:11:43)
    - Video Name 4.mp4 (0:20:09)
    - Video Name 5.mp4 (0:16:27)
----------------------------------------

GRAND TOTAL
  -> Total Folders: 2
  -> Total Videos: 5
  -> Total Duration: 1:24:50
========================================
Generated on: 1991-08-25 20:57:08
```
