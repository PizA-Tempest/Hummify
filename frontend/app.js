import { blobToWav, createRecorder } from "./components/recorder.js";

const API = "http://127.0.0.1:8000/api";
const recordBtn = document.getElementById("recordBtn");
const stopBtn = document.getElementById("stopBtn");
const generateBtn = document.getElementById("generateBtn");
const preview = document.getElementById("preview");
const styleSel = document.getElementById("style");
const output = document.getElementById("output");

let blob = null;
const rec = createRecorder();

fetch(`${API}/styles`).then(r => r.json()).then(({ styles }) => {
  for (const s of styles ?? ["lo-fi"]) {
    const o = document.createElement("option");
    o.value = o.textContent = s;
    styleSel.appendChild(o);
  }
}).catch(() => {
  const o = document.createElement("option");
  o.value = o.textContent = "lo-fi";
  styleSel.appendChild(o);
});

recordBtn.onclick = async () => {
  await rec.start();
  recordBtn.disabled = true;
  stopBtn.disabled = false;
};
stopBtn.onclick = async () => {
  blob = await rec.stop();
  preview.src = URL.createObjectURL(blob);
  recordBtn.disabled = false;
  stopBtn.disabled = true;
  generateBtn.disabled = !blob;
};
generateBtn.onclick = async () => {
  output.textContent = "Converting to WAV + analyzing…";
  const wav = await blobToWav(blob);
  const fd = new FormData();
  fd.append("file", wav, "hum.wav");
  fd.append("style", styleSel.value);
  fd.append("tempo", document.getElementById("tempo").value);
  fd.append("mood", document.getElementById("mood").value);
  const res = await fetch(`${API}/generate`, { method: "POST", body: fd });
  output.textContent = JSON.stringify(await res.json(), null, 2);
};
