const mediainfoWorker = new Worker("./mediainfo-worker.js");

export async function runQueue(files, concurrencyLimit, processCallback) {
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

export function getNativeDuration(file) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "metadata";

    const objectUrl = URL.createObjectURL(file);

    const cleanup = () => {
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(objectUrl);
    };

    video.onloadedmetadata = () => {
      const duration = video.duration;
      cleanup();
      resolve(duration);
    };

    video.onerror = () => {
      cleanup();
      reject(new Error(`Failed for native file: ${file.name}`));
    };

    video.src = objectUrl;
  });
}

export function getWasmDuration(file) {
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

export async function getFiles(items) {
  let files = [];

  if (!items[0].getAsFileSystemHandle) {
    return null;
  }

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
