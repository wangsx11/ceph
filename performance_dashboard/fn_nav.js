(function () {
  function renderFnNav() {
    const { state, functionsFor } = window.FDState;
    const root = document.getElementById("fn-nav");
    const rows = functionsFor(state.currentModule);
    root.innerHTML = rows.map((row) => {
      const active = row.fn_id === state.currentFn ? " active" : "";
      const statusClass = window.FDUtils.statusClass[String(row.status || "").toUpperCase()] || "muted";
      const statusText = window.FDUtils.statusText[String(row.status || "").toUpperCase()] || row.status_text;
      return `
        <button class="fn-btn${active}" type="button" data-fn="${row.fn_id}">
          <span class="fn-status-dot ${statusClass}"></span>
          <span class="fn-name">${window.FDUtils.escapeHtml(row.function_display_name)}</span>
          ${window.FDUtils.badge(row.status, statusText)}
        </button>
      `;
    }).join("");
    root.querySelectorAll("[data-fn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.currentFn = btn.dataset.fn;
        await window.FDLayout.loadCurrentFunction();
      });
    });
  }

  window.FDFnNav = { renderFnNav };
})();
