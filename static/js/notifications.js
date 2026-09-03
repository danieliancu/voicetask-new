/* Notificari in browser.
 *
 * Interfata declara push activ doar cand ambele conditii sunt adevarate:
 * permisiunea browserului este „granted" SI serverul confirma un abonament.
 * Starea nu este niciodata presupusa. */

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
  return response.ok ? response.json() : null;
}

class PushPanel {
  constructor(root) {
    this.root = root;
    this.subscribeUrl = root.dataset.subscribeUrl;
    this.unsubscribeUrl = root.dataset.unsubscribeUrl;
    this.vapidKey = root.dataset.vapidKey;
    this.serverSupports = root.dataset.serverSupports === "true";

    this.status = root.querySelector("[data-push-status]");
    this.enable = root.querySelector("[data-push-enable]");
    this.disable = root.querySelector("[data-push-disable]");
    this.fallback = root.querySelector("[data-push-fallback]");

    this.enable?.addEventListener("click", () => this.subscribe());
    this.disable?.addEventListener("click", () => this.unsubscribe());
    this.refresh();
  }

  supported() {
    return (
      this.serverSupports &&
      Boolean(this.vapidKey) &&
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    );
  }

  setStatus(text) {
    if (this.status) this.status.textContent = text;
  }

  async refresh() {
    if (!this.supported()) {
      this.enable?.setAttribute("hidden", "");
      this.disable?.setAttribute("hidden", "");
      this.setStatus("Browserul sau serverul nu acceptă notificări push.");
      return;
    }
    const registration = await navigator.serviceWorker.ready.catch(() => null);
    const subscription = await registration?.pushManager.getSubscription();
    const granted = Notification.permission === "granted";
    const active = granted && Boolean(subscription);

    this.enable?.toggleAttribute("hidden", active);
    this.disable?.toggleAttribute("hidden", !active);
    this.fallback?.toggleAttribute("hidden", Notification.permission !== "denied");
    this.setStatus(
      active
        ? "Notificările push sunt active pe acest dispozitiv."
        : Notification.permission === "denied"
          ? "Browserul a refuzat permisiunea pentru notificări."
          : "Nu ai activat notificările push pe acest dispozitiv."
    );
  }

  async subscribe() {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      await this.refresh();
      return;
    }
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager
      .subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(this.vapidKey),
      })
      .catch(() => null);
    if (!subscription) {
      this.setStatus("Abonarea nu a reușit. Încearcă din nou.");
      return;
    }
    await postJson(this.subscribeUrl, subscription.toJSON());
    await this.refresh();
  }

  async unsubscribe() {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await postJson(this.unsubscribeUrl, { endpoint: subscription.endpoint });
      await subscription.unsubscribe().catch(() => {});
    }
    await this.refresh();
  }
}

export function init() {
  document.querySelectorAll("[data-push]").forEach((root) => new PushPanel(root));
}
