/* Playerul rezumatului: play/pause, progres, cautare in piesa. */

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${m}:${s}`;
}

class Player {
  constructor(root) {
    this.audio = root.querySelector("[data-audio-source]");
    if (!this.audio) return;
    this.toggle = root.querySelector("[data-audio-toggle]");
    this.iconPlay = root.querySelector("[data-audio-icon-play]");
    this.iconPause = root.querySelector("[data-audio-icon-pause]");
    this.bar = root.querySelector("[data-audio-bar]");
    this.progress = root.querySelector("[data-audio-progress]");
    this.time = root.querySelector("[data-audio-time]");

    this.toggle?.addEventListener("click", () => this.onToggle());
    this.audio.addEventListener("timeupdate", () => this.onProgress());
    this.audio.addEventListener("loadedmetadata", () => this.onProgress());
    this.audio.addEventListener("ended", () => this.setPlaying(false));
    this.progress?.addEventListener("click", (event) => this.seek(event));
    this.progress?.addEventListener("keydown", (event) => this.onKey(event));
  }

  onToggle() {
    if (this.audio.paused) {
      this.audio.play().then(() => this.setPlaying(true)).catch(() => this.setPlaying(false));
    } else {
      this.audio.pause();
      this.setPlaying(false);
    }
  }

  setPlaying(playing) {
    this.toggle?.setAttribute("aria-pressed", playing ? "true" : "false");
    this.toggle?.setAttribute("aria-label", playing ? "Pune pauză" : "Redă rezumatul");
    this.iconPlay?.toggleAttribute("hidden", playing);
    this.iconPause?.toggleAttribute("hidden", !playing);
  }

  onProgress() {
    const ratio = this.audio.duration ? this.audio.currentTime / this.audio.duration : 0;
    if (this.bar) this.bar.style.width = `${ratio * 100}%`;
    if (this.progress) this.progress.setAttribute("aria-valuenow", Math.round(ratio * 100));
    if (this.time) {
      this.time.textContent = `${formatTime(this.audio.currentTime)} / ${formatTime(this.audio.duration)}`;
    }
  }

  seek(event) {
    if (!this.audio.duration) return;
    const rect = this.progress.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    this.audio.currentTime = ratio * this.audio.duration;
  }

  onKey(event) {
    if (!this.audio.duration) return;
    const step = 5;
    if (event.key === "ArrowRight") {
      this.audio.currentTime = Math.min(this.audio.duration, this.audio.currentTime + step);
      event.preventDefault();
    } else if (event.key === "ArrowLeft") {
      this.audio.currentTime = Math.max(0, this.audio.currentTime - step);
      event.preventDefault();
    } else if (event.key === " " || event.key === "Enter") {
      this.onToggle();
      event.preventDefault();
    }
  }
}

export function init() {
  document.querySelectorAll("[data-audio-player]").forEach((root) => new Player(root));
}
