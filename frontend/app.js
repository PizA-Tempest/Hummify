import { blobToWav, createRecorder } from "./components/recorder.js";

const API = "http://127.0.0.1:8000/api";
const $ = id => document.getElementById(id);
const recordBtn = $("recordBtn"), stopBtn = $("stopBtn"), generateBtn = $("generateBtn");
const preview = $("preview"), beat = $("beat"), download = $("download");
const chips = $("style"), tempo = $("tempo"), tempoVal = $("tempoVal"), mood = $("mood");
const output = $("output"), banner = $("banner"), status = $("apiStatus");
const resultCard = $("resultCard"), resultMeta = $("resultMeta"), recTimer = $("recTimer");
const regenBtn = $("regenBtn"), versions = $("versions");
const stemsBox = $("stems"), stemLinks = $("stemLinks");

let blob = null, lastWav = null, selectedStyle = null, timerId = null, timerStart = 0;
let versionCount = 0;

function showError(msg) {
  banner.textContent = msg;
  banner.hidden = false;
}
function clearError() { banner.hidden = true; }
function setStatus(state, text) {
  status.dataset.state = state;
  status.textContent = text;
}

async function apiOnline() {
  try {
    const r = await fetch(`${API}/health`);
    return r.ok;
  } catch { return false; }
}

async function init() {
  if (await apiOnline()) {
    setStatus("online", "API online");
    clearError();
  } else {
    setStatus("offline", "API offline");
    showError("Can't reach the backend. Start it with: uvicorn backend.app:app --reload (in the Hummify folder).");
  }
  let styles = ["lo-fi"];
  try {
    const r = await fetch(`${API}/styles`);
    if (r.ok) styles = (await r.json()).styles ?? styles;
  } catch { /* offline: fallback chips */ }
  chips.innerHTML = "";
  for (const s of styles) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = s;
    b.setAttribute("role", "radio");
    b.onclick = () => {
      selectedStyle = s;
      chips.querySelectorAll(".chip").forEach(c => {
        const on = c === b;
        c.classList.toggle("on", on);
        c.setAttribute("aria-checked", on);
      });
    };
    chips.appendChild(b);
  }
  chips.firstChild?.click();
}

const rec = createRecorder();

function tick() {
  const s = Math.floor((Date.now() - timerStart) / 1000);
  recTimer.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

recordBtn.onclick = async () => {
  clearError();
  try {
    await rec.start();
  } catch {
    showError("Microphone blocked. Allow mic access in the browser, then try again. (Use http://localhost:5500 — some browsers block the mic on file://.)");
    return;
  }
  timerStart = Date.now();
  recTimer.hidden = false;
  timerId = setInterval(tick, 250);
  document.body.classList.add("recording");
  recordBtn.disabled = true;
  stopBtn.disabled = false;
};

stopBtn.onclick = async () => {
  blob = await rec.stop();
  clearInterval(timerId);
  recTimer.hidden = true;
  document.body.classList.remove("recording");
  preview.src = URL.createObjectURL(blob);
  lastWav = null;
  versionCount = 0;
  versions.innerHTML = "";
  stemLinks.innerHTML = "";
  stemLinks.hidden = true;
  resultCard.hidden = true;
  recordBtn.disabled = false;
  stopBtn.disabled = true;
  generateBtn.disabled = !blob;
};

tempo.oninput = () => { tempoVal.value = tempo.value; };

generateBtn.onclick = () => requestBeat(null);
regenBtn.onclick = () => requestBeat(Math.floor(Math.random() * 2 ** 31));

async function requestBeat(seed) {
  clearError();
  document.body.classList.add("generating");
  generateBtn.disabled = true;
  regenBtn.disabled = true;
  try {
    lastWav = lastWav && seed !== null ? lastWav : await blobToWav(blob);
    const fd = new FormData();
    fd.append("file", lastWav, "hum.wav");
    fd.append("style", selectedStyle);
    fd.append("tempo", tempo.value);
    fd.append("mood", mood.value);
    if (seed !== null) fd.append("seed", seed);
    fd.append("stems", stemsBox.checked);
    let res;
    try {
      res = await fetch(`${API}/generate`, { method: "POST", body: fd });
    } catch {
      showError("Can't reach the backend. Start it with: uvicorn backend.app:app --reload.");
      return;
    }
    const data = await res.json();
    output.textContent = JSON.stringify(data, null, 2);
    if (!res.ok) {
      showError(`Backend error: ${data.detail ?? res.status}`);
      return;
    }
    versionCount += 1;
    const url = new URL(data.audio_url, `${API}/`).href;
    resultMeta.textContent = `v${versionCount} · ${data.style} · ${data.tempo_bpm} BPM · ${data.duration_s}s · seed ${data.seed}`;
    beat.src = url;
    download.href = url;
    download.download = `hummify-${data.style}-v${versionCount}.wav`;
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = url;
    a.textContent = `v${versionCount} (${data.tempo_bpm} BPM, seed ${data.seed})`;
    a.onclick = e => { e.preventDefault(); beat.src = url; beat.play(); };
    li.appendChild(a);
    versions.prepend(li);
    stemLinks.innerHTML = "";
    if (data.stems) {
      for (const [name, href] of Object.entries(data.stems)) {
        const s = document.createElement("a");
        s.className = "chip stem";
        s.href = new URL(href, `${API}/`).href;
        s.textContent = `${name} WAV`;
        s.download = `hummify-${data.style}-${name}-v${versionCount}.wav`;
        stemLinks.appendChild(s);
      }
      stemLinks.hidden = false;
    } else {
      stemLinks.hidden = true;
    }
    resultCard.hidden = false;
    resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } finally {
    document.body.classList.remove("generating");
    generateBtn.disabled = !blob;
    regenBtn.disabled = false;
  }
}

init();
