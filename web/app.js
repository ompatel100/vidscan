const state = {
  folderMap: new Map(),
  total: { duration: 0, count: 0, size: 0 },
  isScanning: false,
};

const els = {
  landing: document.getElementById("landing"),
  dashboard: document.getElementById("dashboard"),
  dropZone: document.getElementById("drop-zone"),
  input: document.getElementById("folder-input"),
  tableBody: document.getElementById("table-body"),
  status: document.getElementById("status"),
  totalDur: document.getElementById("total-duration"),
  totalCount: document.getElementById("total-count"),
  totalSize: document.getElementById("total-size"),
  resetBtn: document.getElementById("reset-btn"),
};

const mediainfoWorker = new Worker("./mediainfo-worker.js");

["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
  els.dropZone.addEventListener(
    eventName,
    (e) => {
      e.preventDefault();
      e.stopPropagation();
    },
    false,
  );
});

els.dropZone.addEventListener("dragover", () =>
  els.dropZone.classList.add("dragover"),
);
els.dropZone.addEventListener("dragleave", () =>
  els.dropZone.classList.remove("dragover"),
);

els.dropZone.addEventListener("drop", async (e) => {
  els.dropZone.classList.remove("dragover");

  const items = e.dataTransfer.items;
  if (!items || items.length === 0) return;

  els.landing.classList.add("hidden");
  els.dashboard.classList.remove("hidden");
  els.status.innerText = "> Initializing scan...";

  const files = await getFiles(items);
  if (files.length > 0) {
    handleFiles(files);
  }
});

els.input.addEventListener("change", (e) => {
  if (e.target.files.length > 0) {
    els.landing.classList.add("hidden");
    els.dashboard.classList.remove("hidden");
    els.status.innerText = "> Processing file structure...";
    handleFiles(Array.from(e.target.files));
  }
});

els.resetBtn.addEventListener("click", () => location.reload());

async function getFiles(items) {
  let files = [];

  if (items[0].getAsFileSystemHandle) {
    for (const item of items) {
      try {
        const handle = await item.getAsFileSystemHandle();
        if (handle) {
          if (handle.kind === "directory") {
            const dirFiles = await walkDirHandle(handle);
            files.push(...dirFiles);
          } else {
            const file = await handle.getFile();
            file.fullPath = handle.name;
            files.push(file);
          }
        }
      } catch (err) {
        console.warn("Scan error:", err);
      }
    }
    return files;
  }

  alert(
    "Drag and drop for folders is not supported in your browser. Please use the browse folder button instead.",
  );
  els.landing.classList.remove("hidden");
  els.dashboard.classList.add("hidden");
  return [];
}

async function walkDirHandle(dirHandle, path = "") {
  const files = [];
  const currentPath = path ? `${path}/${dirHandle.name}` : dirHandle.name;

  try {
    for await (const entry of dirHandle.values()) {
      if (entry.kind === "file") {
        const file = await entry.getFile();
        file.fullPath = `${currentPath}/${entry.name}`;
        files.push(file);
      } else if (entry.kind === "directory") {
        const subFiles = await walkDirHandle(entry, currentPath);
        files.push(...subFiles);
      }
    }
  } catch (err) {
    console.warn(`Error reading folder: ${dirHandle.name}`, err);
  }
  return files;
}

function handleFiles(rawFiles) {
  const videoFiles = rawFiles.filter(isVideo);
  initializeFolders(videoFiles);
  processFiles(videoFiles);
}

function isVideo(file) {
  return file.name.match(/\.(mp4|webm|mov|mkv|avi|flv|wmv|m4v)$/i);
}

function getFolderName(file) {
  let fullPath = file.webkitRelativePath || file.fullPath || file.name;
  if (fullPath.startsWith("/")) fullPath = fullPath.substring(1);

  const pathParts = fullPath.split("/");
  if (pathParts.length > 1) {
    pathParts.pop();
  } else {
    return "Main Directory";
  }

  return pathParts.join("/");
}

function initializeFolders(files) {
  state.folderMap.clear();
  els.tableBody.innerHTML = "";

  files.forEach((file) => {
    const folderName = getFolderName(file);

    if (!state.folderMap.has(folderName)) {
      const rowId = `row-${Math.random().toString(36).substring(2, 11)}`;
      state.folderMap.set(folderName, {
        count: 0,
        duration: 0,
        size: 0,
        rowId: rowId,
      });
      createTableRow(folderName, rowId);
    }

    const folderData = state.folderMap.get(folderName);
    folderData.size += file.size;
    folderData.count++;
  });

  state.folderMap.forEach((data, name) => updateFolderRow(name));
  updateTotalStats();
}

async function runQueue(files, concurrencyLimit, processCallback) {
  let index = 0;

  const worker = async () => {
    while (index < files.length) {
      const currentIndex = index++;
      await processCallback(files[currentIndex]);
    }
  };

  const workers = [];
  for (let i = 0; i < concurrencyLimit; i++) {
    workers.push(worker());
  }

  await Promise.all(workers);
}

async function processFiles(files) {
  state.isScanning = true;
  let processedCount = 0;

  const updateProgress = (fileName) => {
    processedCount++;
    els.status.innerText = `> Processed ${processedCount} of ${files.length}... (${fileName})`;
  };

  const nativeFiles = [];
  const wasmFiles = [];

  files.forEach((file) => {
    if (file.name.match(/\.(mp4|webm|mov|m4v)$/i)) {
      nativeFiles.push(file);
    } else {
      wasmFiles.push(file);
    }
  });

  const processNativeFile = async (file) => {
    try {
      let duration = 0;
      try {
        duration = await getNativeDuration(file);
      } catch (err) {
        duration = await getWasmDuration(file);
      }
      saveDurationToState(file, duration);
    } catch (e) {
      console.warn(`Failed both native and wasm for: ${file.name}`);
    } finally {
      updateProgress(file.name);
    }
  };

  const processWasmFile = async (file) => {
    try {
      const duration = await getWasmDuration(file);
      saveDurationToState(file, duration);
    } catch (e) {
      console.warn(`Failed wasm for: ${file.name}`);
    } finally {
      updateProgress(file.name);
    }
  };

  await Promise.all([
    runQueue(nativeFiles, 1, processNativeFile),
    runQueue(wasmFiles, 1, processWasmFile),
  ]);

  els.status.innerText = "> Scan Complete.";
  state.isScanning = false;
}

function getNativeDuration(file) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "metadata";

    const objectUrl = URL.createObjectURL(file);
    video.src = objectUrl;

    video.onloadedmetadata = () => {
      resolve(video.duration);

      setTimeout(() => {
        URL.revokeObjectURL(objectUrl);
        video.src = "";
        video.remove();
      }, 100);
    };

    video.onerror = () => {
      reject();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
    };
  });
}

function getWasmDuration(file) {
  return new Promise((resolve, reject) => {
    const listener = (e) => {
      const { success, fileName, duration, error } = e.data;

      if (fileName === file.name) {
        mediainfoWorker.removeEventListener("message", listener);
        if (success) {
          resolve(duration);
        } else {
          reject(new Error(error));
        }
      }
    };

    mediainfoWorker.addEventListener("message", listener);
    mediainfoWorker.postMessage(file);
  });
}

function saveDurationToState(file, duration) {
  if (duration <= 0) return;

  const folderName = getFolderName(file);
  const folder = state.folderMap.get(folderName);

  if (folder) {
    folder.duration += duration;
    state.total.duration += duration;
    updateFolderRow(folderName);
    updateTotalStats();
  }
}

function createTableRow(folderName, rowId) {
  const row = document.createElement("tr");
  row.id = rowId;
  row.innerHTML = `<td class="folder-path">${folderName}</td><td class="col-count">0</td><td class="col-dur">00:00:00</td><td class="col-size">0 MB</td>`;
  els.tableBody.appendChild(row);
}

function updateFolderRow(folderName) {
  const data = state.folderMap.get(folderName);
  const row = document.getElementById(data.rowId);
  if (!row) return;
  row.querySelector(".col-count").innerText = data.count;
  row.querySelector(".col-dur").innerText = formatDuration(data.duration);
  row.querySelector(".col-size").innerText = formatSize(data.size);
}

function updateTotalStats() {
  let totalFiles = 0;
  let totalSize = 0;
  state.folderMap.forEach((d) => {
    totalFiles += d.count;
    totalSize += d.size;
  });
  els.totalCount.innerText = totalFiles;
  els.totalSize.innerText = formatSize(totalSize);
  els.totalDur.innerText = formatDuration(state.total.duration);
}

function formatDuration(sec) {
  if (!sec) return "00:00:00";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatSize(bytes) {
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}
