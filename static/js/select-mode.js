/* Selectia multipla din ecranele Șterge si Coș.
 * Doar starea butonului si numaratoarea; stergerea ramane un POST obisnuit. */

class SelectMode {
  constructor(form) {
    this.form = form;
    this.counter = form.querySelector("[data-selection-count]");
    this.submit = form.querySelector("[data-selection-submit]");
    this.boxes = () => form.querySelectorAll("input[name='element']");
    form.addEventListener("change", () => this.update());
    this.update();
  }

  update() {
    const selected = Array.from(this.boxes()).filter((box) => box.checked).length;
    if (this.counter) {
      this.counter.textContent =
        selected === 0
          ? "Niciun element selectat"
          : selected === 1
            ? "1 element selectat"
            : `${selected} elemente selectate`;
    }
    if (this.submit) this.submit.disabled = selected === 0;
  }
}

export function init() {
  document.querySelectorAll("[data-select-mode]").forEach((form) => new SelectMode(form));
}
