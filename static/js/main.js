/* Punctul de intrare. Configureaza HTMX, dialogurile si incarca lenes restul
 * modulelor, in functie de ce contine pagina. Niciun modul nu contine logica de
 * business: deciziile se iau in Python. */

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export function announce(message) {
  const region = document.getElementById("anunturi");
  if (region) region.textContent = message;
}

export async function postForm(url, formData) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "fetch" },
    body: formData,
    credentials: "same-origin",
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  return { ok: response.ok, status: response.status, data: payload };
}

document.body.addEventListener("htmx:configRequest", (event) => {
  event.detail.headers["X-CSRFToken"] = csrfToken();
});

/* Dialogurile <dialog>: deschidere, inchidere, revenirea focusului. */
function setupDialogs(root = document) {
  root.querySelectorAll("dialog[data-autoshow]").forEach((dialog) => {
    if (!dialog.open) dialog.showModal();
  });
  root.querySelectorAll("[data-close-dialog]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
}

document.querySelectorAll("[data-open-drawer]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById("meniu-lateral")?.showModal();
  });
});

/* Ecranele imersive (de exemplu camera) revin la ecranul care le-a deschis.
 * Linkul ramane un fallback functional pentru acces direct sau JS dezactivat. */
document.querySelectorAll("[data-history-back]").forEach((link) => {
  link.addEventListener("click", (event) => {
    let referrer;
    try {
      referrer = document.referrer ? new URL(document.referrer) : null;
    } catch {
      referrer = null;
    }

    if (referrer?.origin === window.location.origin && referrer.href !== window.location.href) {
      event.preventDefault();
      window.history.back();
    }
  });
});

document.body.addEventListener("htmx:afterSwap", (event) => setupDialogs(event.target));
setupDialogs();

/* Chipsurile de filtrare din cautare trimit formularul la schimbare. */
document.querySelectorAll("[data-source-all]").forEach((button) => {
  button.addEventListener("click", () => {
    document
      .querySelectorAll("input[name='sursa']")
      .forEach((input) => {
        input.checked = false;
        input.closest(".chip")?.classList.remove("is-active");
      });
    button.setAttribute("aria-pressed", "true");
    document.getElementById("formular-cautare")?.dispatchEvent(new Event("change", { bubbles: true }));
  });
});

document.querySelectorAll("input[name='sursa']").forEach((input) => {
  input.addEventListener("change", () => {
    input.closest(".chip")?.classList.toggle("is-active", input.checked);
    document.querySelector("[data-source-all]")?.setAttribute("aria-pressed", "false");
  });
});

/* Incarcare lenesa, doar pentru ce exista in pagina. */
if (document.querySelector("[data-recorder]")) {
  import("./recorder.js").then((module) => module.init());
}
if (document.querySelector("[data-camera]")) {
  import("./camera.js").then((module) => module.init());
}
if (document.querySelector("[data-audio-player]")) {
  import("./audio-player.js").then((module) => module.init());
}
if (document.querySelector("[data-push]")) {
  import("./notifications.js").then((module) => module.init());
}
if (document.querySelector("[data-select-mode]")) {
  import("./select-mode.js").then((module) => module.init());
}
if ("serviceWorker" in navigator) {
  import("./sw-register.js").then((module) => module.init());
}
