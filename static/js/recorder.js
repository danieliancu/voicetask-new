/* Inregistrarea audio. Se ocupa doar de microfon si de trimiterea fisierului:
 * transcrierea, interpretarea si validarea se fac pe server. */

import { announce, postForm } from "./main.js";

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function formatTime(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${m}:${s}`;
}

class Recorder {
  constructor(root) {
    this.root = root;
    this.uploadUrl = root.dataset.uploadUrl;
    this.maxBytes = Number(root.dataset.maxBytes || 20 * 1024 * 1024);
    this.toggle = root.querySelector("[data-record-toggle]");
    this.cancelButton = root.querySelector("[data-record-cancel]");
    this.timer = root.querySelector("[data-timer]");
    this.status = root.querySelector("[data-status]");
    this.level = root.querySelector("[data-level]");
    this.levelTrack = root.querySelector("[data-level-track]");
    this.chunks = [];
    this.cancelled = false;

    this.toggle?.addEventListener("click", () => this.onToggle());
    this.cancelButton?.addEventListener("click", () => this.cancel());
  }

  /* `progress` inlocuieste textul cu bara verde: durata nu se poate estima, asa
   * ca bara este indeterminata. Textul pleaca oricum spre cititoarele de ecran,
   * care nu au ce face cu o animatie. */
  setStatus(text, { progress = false } = {}) {
    if (this.status) this.status.textContent = progress ? "" : text;
    this.levelTrack?.toggleAttribute("data-progress", progress);
    if (progress && this.level) this.level.style.width = "";
    announce(text);
  }

  async onToggle() {
    if (this.recorder && this.recorder.state === "recording") {
      this.stop();
      return;
    }
    await this.start();
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      this.showTextFallback("Browserul nu permite înregistrarea audio.");
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.showTextFallback("Nu am primit acces la microfon.");
      return;
    }

    const mimeType = pickMimeType();
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.cancelled = false;

    this.recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    });
    this.recorder.addEventListener("stop", () => this.onStop(mimeType));

    this.recorder.start();
    this.startedAt = Date.now();
    this.tick();
    this.meter();

    this.toggle.dataset.state = "recording";
    this.toggle.setAttribute("aria-pressed", "true");
    this.toggle.setAttribute("aria-label", "Oprește înregistrarea");
    this.cancelButton?.removeAttribute("hidden");
    this.setStatus("Se înregistrează… Apasă din nou ca să oprești.");
  }

  tick() {
    this.interval = setInterval(() => {
      const elapsed = (Date.now() - this.startedAt) / 1000;
      if (this.timer) this.timer.textContent = formatTime(elapsed);
      if (elapsed > 120) this.stop();
    }, 200);
  }

  meter() {
    if (!this.level || !window.AudioContext) return;
    this.audioContext = new AudioContext();
    const source = this.audioContext.createMediaStreamSource(this.stream);
    const analyser = this.audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const draw = () => {
      if (!this.recorder || this.recorder.state !== "recording") return;
      analyser.getByteFrequencyData(data);
      const average = data.reduce((sum, value) => sum + value, 0) / data.length;
      this.level.style.width = `${Math.min(100, (average / 128) * 100)}%`;
      this.animation = requestAnimationFrame(draw);
    };
    draw();
  }

  cleanup() {
    clearInterval(this.interval);
    cancelAnimationFrame(this.animation);
    this.audioContext?.close().catch(() => {});
    this.stream?.getTracks().forEach((track) => track.stop());
    this.toggle.dataset.state = "idle";
    this.toggle.setAttribute("aria-pressed", "false");
    this.toggle.setAttribute("aria-label", "Începe înregistrarea");
    this.cancelButton?.setAttribute("hidden", "");
    if (this.level) this.level.style.width = "0";
  }

  stop() {
    if (this.recorder?.state === "recording") this.recorder.stop();
  }

  cancel() {
    this.cancelled = true;
    this.stop();
    this.setStatus("Înregistrare anulată.");
  }

  async onStop(mimeType) {
    this.cleanup();
    if (this.cancelled) return;

    const blob = new Blob(this.chunks, { type: mimeType || "audio/webm" });
    if (blob.size === 0) {
      this.setStatus("Nu s-a înregistrat nimic. Încearcă din nou.");
      return;
    }
    if (blob.size > this.maxBytes) {
      this.setStatus("Înregistrarea este prea lungă. Încearcă una mai scurtă.");
      return;
    }

    this.setStatus("Se trimite și se interpretează…", { progress: true });
    const form = new FormData();
    form.append("audio", blob, "comanda.webm");

    const { ok, data } = await postForm(this.uploadUrl, form);
    if (!ok || !data?.url) {
      this.setStatus(data?.eroare || "Comanda nu a putut fi procesată.");
      return;
    }
    this.setStatus("Gata. Verifică detaliile înainte de salvare.");
    const target = document.getElementById("zona-schita");
    if (target && window.htmx) {
      window.htmx.ajax("GET", data.url, { target: "#zona-schita", swap: "innerHTML" });
    } else {
      window.location.assign(data.url);
    }
  }

  showTextFallback(message) {
    this.setStatus(`${message} Poți scrie comanda în schimb.`);
    const fallback = document.querySelector("[data-text-fallback]");
    if (fallback) fallback.open = true;
  }
}

export function init() {
  document.querySelectorAll("[data-recorder]").forEach((root) => new Recorder(root));
}
