# vidscan

Recursively scan media libraries and generate per-folder and per-file reports of duration and size in txt, csv, or json - powered by ffprobe.

## Requirements

- Python 3.7+
- FFmpeg ([ffmpeg.org/download.html](https://ffmpeg.org/download.html))

FFmpeg must be installed and available in your system PATH. vidscan calls ffprobe (included with FFmpeg) to read media metadata. If ffprobe is not found, vidscan will not run.

## Installation

```bash
pip install vidscan
```

No additional packages are installed. vidscan has zero pip dependencies. It's safe to install globally without any virtual environment.

## Quick Start

Provide the folder path. It scans it and all subfolders recursively, and generates report in the same folder.

Windows

```powershell
vidscan "D:\Media\Projects"
```

macOS / Linux

```bash
vidscan /media/projects
```

Report is saved in the scanned folder. If any files fail, a separate failed files report is saved alongside it. The default output is summary txt. Run `vidscan --help` to see all options.

## Output Example (default txt summary)

Default summary txt report grouped by subfolders:

```txt
Video Duration (Summary)
============================================================

Folder: Commercials
  -> Videos:   8 | Duration: 02:14:33
------------------------------------------------------------
Folder: Documentaries
  -> Videos:  23 | Duration: 07:45:12
------------------------------------------------------------
Folder: Raw Footage
  -> Videos:  41 | Duration: 14:22:08
------------------------------------------------------------

TOTALS
  -> Total Folders: 3
  -> Total Videos: 72
  -> Total Duration: 24:21:53
============================================================
Generated on: 2026-04-29 14:52:07

---
[!] NOTE: Scanning failed for 2 videos and are excluded from this report.
```

Failed files are caught, with the reason for failure, and a separate report is generated alongside the main one. They are never silently dropped.

## Why vidscan

Four things were kept at the center of how vidscan was built.

### Coverage

Scans any folder structure recursively to any depth. The traversal is stack based, not recursive, so deeply nested libraries do not hit Python's call stack limit. Works on local drives, external drives, and network drives.

`--extensions` defines exactly which file types are included, `--exclude` defines which folders are skipped entirely. The default covers common video formats, but since ffprobe supports virtually any media format, vidscan can be used on audio libraries, mixed media archives, or broadcast formats such as MXF by specifying extensions.

### Performance

Files are processed concurrently using multiple threads. vidscan has two built-in defaults - one for HDD, one for SSD. Both are dynamic based on system's CPU count. HDD default is used unless `-w ssd` is specified. Thread count can be set manually with `-w <n>`.

For network drives, `--fast-start` skips the initial directory count and begins processing immediately, avoiding the latency before starting.

### Reliability

ffprobe is the foundation - the industry standard for media metadata, it's the same engine used in professional media tools. Duration results are not estimated or inferred from file headers. They are read directly by ffprobe.

Failed files are caught individually. Each failure is recorded with its path, specific error reason and file size. A separate failed files report is generated alongside the main report.

`--ffprobe-timeout` prevents the tool from hanging on corrupt, partially written, or network stalled files. A file that exceeds the timeout is marked as failed and the scan continues.

If a scan is interrupted, results processed up to that point are preserved and written. The scan does not need to complete for the output to be useful.

Windows long paths beyond MAX_PATH are handled automatically. Symbolic links to directories are not followed, preventing symlink loops.

Terminal output adapts automatically to the environment - color, progress bar, and unicode characters adjust based on terminal capabilities. `NO_COLOR` ([no-color.org](https://no-color.org)), `FORCE_COLOR`, and `CLICOLOR_FORCE` are respected. When output is piped or redirected, formatting is stripped automatically.

Zero pip dependencies means no version conflicts and no risk of affecting an existing Python environment. vidscan is safe to install globally without any virtual environment.

### Flexibility

Three output formats: `txt`, `csv`, and `json`. Use `--format all` to generate all three in a single scan. The txt format has two templates: `summary` for folder level totals and `detailed` for a per-file breakdown for each folder. File size can be included in txt reports with `--include-size-txt`.

Folders can be sorted by name, duration, file count, size, or date of the most recently modified file within the folder. Sort order is ascending by default and can be descending with `--sort-order desc`.

## Flags

| Flag                 | Default          | Description                                                                                                                                  |
| -------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `folder_path`        | required         | Path to the folder to scan                                                                                                                   |
| `-e, --exclude`      | none             | Folder names to skip, space separated, case sensitive                                                                                        |
| `-ext, --extensions` | see below        | File extensions to scan, space separated, e.g. `mp4 mkv mov`                                                                                 |
| `-w, --workers`      | system dependent | Parallel thread count. Default is for HDD, `-w ssd` for SSD default, `-w <n>` for specific count                                             |
| `-f, --format`       | `txt`            | Output format: `txt`, `csv`, `json`, or `all`                                                                                                |
| `-t, --template`     | `summary`        | Txt report template: `summary` or `detailed`                                                                                                 |
| `--include-size-txt` | off              | Include file size in txt reports                                                                                                             |
| `-sb, --sort-by`     | `name`           | Sort folders by: `name`, `duration`, `videos`, `size`, or `date`                                                                             |
| `-so, --sort-order`  | `asc`            | Sort order: `asc` or `desc`                                                                                                                  |
| `--fast-start`       | off              | Skip pre-scan file count and begin processing immediately. Displays processed count instead of progress bar. Recommended for network drives. |
| `--ffprobe-timeout`  | `15.0`           | Seconds to wait for ffprobe on a single file before marking it as failed                                                                     |

**Default extensions:** `.mp4 .mkv .webm .mov .m4v .avi .wmv .flv .mpg .mpeg`

### Examples

Detailed txt report sorted by duration, longest duration folders first:

```bash
vidscan "D:\Media" -t detailed -sb duration -so desc
```

Scan with 16 threads, skip cache and temp folders, generate all formats:

```bash
vidscan /media/archive -w 16 -e cache temp -f all
```

Scan only MXF and MOV files on a network drive with 30 sec ffprobe timeout:

```bash
vidscan /mnt/nas/footage -ext mxf mov --fast-start --ffprobe-timeout 30
```

Include file sizes in a summary report sorted by total folder size:

```bash
vidscan "D:\Projects" --include-size-txt -sb size -so desc
```

## Output Formats

### txt - summary (default)

One entry per-folder showing video count and total duration, with an optional size column. Totals at the end cover all folders combined. Readable as-is without any additional tooling.

### txt - detailed (`-t detailed`)

Each folder lists every individual file with its duration and optional size. Useful when you need to audit specific files rather than just folder level totals.

```txt
Video Duration (Detailed)
===========================================================================

Folder: Commercials
  [ Videos:   8 | Subtotal Duration: 02:14:33 | Subtotal Size: 1.24 GB ]
    - brand_spot_v3_final.mp4 (00:00:30 | 187.32 MB)
    - corporate_intro_2024.mov (00:01:15 | 312.45 MB)
    - product_launch_cut.mp4 (00:00:45 | 156.18 MB)
    ...

Folder: Documentaries
  [ Videos:  23 | Subtotal Duration: 07:45:12 | Subtotal Size: 48.67 GB ]
    - chapter_01_rough.mkv (00:18:44 | 8.92 GB)
    - chapter_02_rough.mkv (00:22:31 | 10.14 GB)
    ...

---------------------------------------------------------------------------

GRAND TOTAL
  -> Total Folders: 3
  -> Total Videos: 72
  -> Total Duration: 24:21:53
  -> Total Videos Size: 87.43 GB
===========================================================================
Generated on: 2026-04-29 14:53:39
```

Shown with `--include-size-txt`. Without this, size columns are omitted.

### csv (`-f csv`)

One row per-file with columns: folder path, relative path, file name, duration in seconds, duration formatted, size in bytes, size formatted. Failed files appear as rows with `FAILED` in the duration column and the error reason in the formatted duration column. A summary block is appended at the bottom of the file. Opens directly in Excel or Google Sheets.

### json (`-f json`)

A structured object with three top-level keys:

- `summary` - total folders, video count, duration, and size across the full scan
- `details` - array of folder objects, each containing its video count, total duration, total size, and an array of individual video entries
- `failed_videos` - array of files that could not be read, each with path, error reason, and size

### all (`-f all`)

Generates txt (detailed template), csv, and json in a single scan.

## License

MIT

## Issues

Report bugs or request features [here](https://github.com/ompatel100/vidscan/issues)
