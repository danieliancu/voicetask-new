/* Camera si incarcarea fotografiei.
 *
 * Modulul acceseaza camera, face captura, comprima imaginea pentru transport si
 * o trimite. Detectarea documentului si OCR-ul se fac pe server: indicatorul
 * „Document detectat" reflecta raspunsul serverului, nu o presupunere din JS. */

import { announce, postForm } from "./main.js";

const MAX_SIDE = 2000;
const JPEG_QUALITY = 0.9;
const DETECT_INTERVAL_MS = 1200;
const DETECT_FRAME_SIDE = 480;

async function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

function drawScaled(source, maxSide) {
  const width = source.videoWidth || source.naturalWidth || source.width;
  const height = source.videoHeight || source.naturalHeight || source.height;
  const scale = Math.min(1, maxSide / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

class Camera {
  constructor(root) {
    this.root = root;
    this.uploadUrl = root.dataset.uploadUrl;
    this.detectUrl = root.dataset.detectUrl;
    this.maxBytes = Number(root.dataset.maxBytes || 12 * 1024 * 1024);

    this.video = root.querySelector("[data-camera-video]");
    this.preview = root.querySelector("[data-camera-preview]");
    this.flag = root.querySelector("[data-camera-flag]");
    this.flagText = root.querySelector("[data-camera-flag-text]");

    this.shoot = document.querySelector("[data-camera-shoot]");
    this.fileInput = document.querySelector("[data-camera-file]");
    this.actions = document.querySelector("[data-camera-actions]");
    this.retake = document.querySelector("[data-camera-retake]");
    this.confirm = document.querySelector("[data-camera-confirm]");
    this.status = document.querySelector("[data-camera-status]");
    this.torchWrap = document.querySelector("[data-camera-torch-wrap]");
    this.torch = document.querySelector("[data-camera-torch]");

    this.shoot?.addEventListener("click", () => this.capture());
    this.fileInput?.addEventListener("change", (event) => this.fromFile(event));
    this.retake?.addEventListener("click", () => this.reset());
    this.confirm?.addEventListener("click", () => this.upload());
    this.torch?.addEventListener("change", () => this.setTorch(this.torch.checked));

    this.start();
  }

  setStatus(text) {
    if (this.status) this.status.textContent = text;
    announce(text);
  }

  setDetected(detected) {
    if (!this.flag) return;
    this.flag.dataset.detected = detected ? "true" : "false";
    if (this.flagText) {
      this.flagText.textContent = detected ? "Document detectat" : "Așază documentul în chenar";
    }
  }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) {
      this.useFileFallback("Browserul nu permite accesul la cameră.");
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
        audio: false,
      });
    } catch {
      this.useFileFallback("Nu am primit acces la cameră.");
      return;
    }
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    this.setStatus("Cameră pornită. Așază documentul în chenar.");
    this.setupTorch();
    this.detectLoop();
  }

  setupTorch() {
    const track = this.stream?.getVideoTracks()[0];
    const capabilities = track?.getCapabilities?.();
    if (capabilities?.torch) this.torchWrap?.removeAttribute("hidden");
  }

  async setTorch(on) {
    const track = this.stream?.getVideoTracks()[0];
    try {
      await track?.applyConstraints({ advanced: [{ torch: on }] });
    } catch {
      this.torchWrap?.setAttribute("hidden", "");
    }
  }

  detectLoop() {
    this.detectTimer = setInterval(async () => {
      if (!this.video?.videoWidth || this.captured) return;
      const canvas = drawScaled(this.video, DETECT_FRAME_SIDE);
      const blob = await canvasToBlob(canvas, "image/jpeg", 0.6);
      if (!blob) return;
      const form = new FormData();
      form.append("cadru", blob, "cadru.jpg");
      const { ok, data } = await postForm(this.detectUrl, form);
      if (ok) this.setDetected(Boolean(data?.detectat));
    }, DETECT_INTERVAL_MS);
  }

  async capture() {
    if (!this.video?.videoWidth) {
      this.fileInput?.click();
      return;
    }
    const canvas = drawScaled(this.video, MAX_SIDE);
    const blob = await canvasToBlob(canvas, "image/jpeg", JPEG_QUALITY);
    if (!blob) {
      this.setStatus("Fotografia nu a putut fi realizată.");
      return;
    }
    this.showPreview(blob);
  }

  async fromFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > this.maxBytes) {
      this.setStatus("Fișierul este prea mare.");
      return;
    }
    const bitmap = await createImageBitmap(file).catch(() => null);
    if (!bitmap) {
      this.showPreview(file);
      return;
    }
    const canvas = drawScaled(bitmap, MAX_SIDE);
    const blob = await canvasToBlob(canvas, "image/jpeg", JPEG_QUALITY);
    this.showPreview(blob || file);
  }

  showPreview(blob) {
    this.captured = blob;
    if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
    this.previewUrl = URL.createObjectURL(blob);
    this.preview.src = this.previewUrl;
    this.preview.removeAttribute("hidden");
    this.video.setAttribute("hidden", "");
    this.actions?.removeAttribute("hidden");
    this.shoot?.setAttribute("hidden", "");
    this.setStatus("Verifică fotografia, apoi trimite-o pentru procesare.");
  }

  reset() {
    this.captured = null;
    if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
    this.preview.setAttribute("hidden", "");
    this.video.removeAttribute("hidden");
    this.actions?.setAttribute("hidden", "");
    this.shoot?.removeAttribute("hidden");
    this.setStatus("Așază documentul în chenar.");
  }

  async upload() {
    if (!this.captured) return;
    if (this.captured.size > this.maxBytes) {
      this.setStatus("Imaginea este prea mare. Încearcă o fotografie mai mică.");
      return;
    }
    this.confirm.classList.add("is-loading");
    this.setStatus("Se trimite documentul…");

    const form = new FormData();
    form.append("imagine", this.captured, "document.jpg");
    const { ok, data } = await postForm(this.uploadUrl, form);

    this.confirm.classList.remove("is-loading");
    if (!ok || !data?.url_stare) {
      this.setStatus(data?.eroare || "Documentul nu a putut fi trimis.");
      return;
    }
    clearInterval(this.detectTimer);
    this.stream?.getTracks().forEach((track) => track.stop());
    this.setStatus(data.duplicat ? "Document deja scanat. Îl deschidem." : "Se procesează…");

    if (window.htmx) {
      window.htmx.ajax("GET", data.url_stare, { target: "#rezultat-scanare", swap: "innerHTML" });
    } else {
      window.location.assign(data.url_detaliu);
    }
  }

  useFileFallback(message) {
    this.setStatus(`${message} Poți alege o fotografie din galerie.`);
    this.video?.setAttribute("hidden", "");
    this.setDetected(false);
    if (this.fileInput) this.fileInput.setAttribute("capture", "environment");
  }
}

export function init() {
  document.querySelectorAll("[data-camera]").forEach((root) => new Camera(root));
}
