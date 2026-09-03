/* Inregistrarea service workerului, cu scope-ul radacinii. */

export function init() {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* Fara service worker aplicatia ramane complet functionala online. */
    });
  });
}
