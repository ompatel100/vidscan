importScripts("./mediainfo.js/index.min.js");

let mediainfoInstance = null;

self.onmessage = async (e) => {
  const file = e.data;

  try {
    if (!mediainfoInstance) {
      mediainfoInstance = await MediaInfo.mediaInfoFactory({
        format: "object",
        locateFile: () => "./mediainfo.js/MediaInfoModule.wasm",
      });
    }

    const readChunk = async (chunkSize, offset) => {
      const buffer = await file.slice(offset, offset + chunkSize).arrayBuffer();
      return new Uint8Array(buffer);
    };

    const result = await mediainfoInstance.analyzeData(file.size, readChunk);

    const generalTrack = result.media.track.find(
      (t) => t["@type"] === "General",
    );
    const durationSec =
      generalTrack && generalTrack.Duration
        ? parseFloat(generalTrack.Duration)
        : 0;

    self.postMessage({
      success: true,
      fileName: file.name,
      duration: durationSec,
    });
  } catch (error) {
    self.postMessage({
      success: false,
      fileName: file.name,
      error: error.message || error,
    });
  }
};
