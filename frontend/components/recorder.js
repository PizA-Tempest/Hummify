/** Decode any recorded blob via WebAudio and re-encode as 16-bit mono WAV. */
export async function blobToWav(blob, targetRate = 44100) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const buf = await blob.arrayBuffer();
  const audio = await ctx.decodeAudioData(buf);
  const dur = audio.duration;
  const len = Math.floor(dur * targetRate);
  const off = new OfflineAudioContext(1, len, targetRate);
  const src = off.createBufferSource();
  src.buffer = audio;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  const ch = rendered.getChannelData(0);
  await ctx.close();
  return encodeWav(ch, targetRate);
}

function encodeWav(samples, rate) {
  const n = samples.length;
  const ab = new ArrayBuffer(44 + n * 2);
  const v = new DataView(ab);
  const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  wstr(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); wstr(8, "WAVE");
  wstr(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  wstr(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([ab], { type: "audio/wav" });
}

/** MediaRecorder wrapper: start() then stop() -> Blob (for preview). */
export function createRecorder() {
  let mr = null;
  let chunks = [];
  let stream = null;
  return {
    async start() {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      mr = new MediaRecorder(stream);
      mr.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      mr.start();
    },
    stop() {
      return new Promise(resolve => {
        mr.onstop = () => {
          stream.getTracks().forEach(t => t.stop());
          resolve(new Blob(chunks, { type: mr.mimeType || "audio/webm" }));
        };
        mr.stop();
      });
    }
  };
}
