(function () {
  function renderModuleNav() {
    const { state, moduleInfo } = window.FDState;
    const root = document.getElementById("module-nav");
    root.innerHTML = state.moduleOrder.map((moduleName) => {
      const info = moduleInfo(moduleName);
      if (!info) return "";
      const counts = info.status_counts_text || {};
      const active = moduleName === state.currentModule ? " active" : "";
      const pass = counts["通过"] || 0;
      const fail = counts["失败"] || 0;
      const skip = counts["跳过"] || 0;
      const waived = counts["豁免"] || 0;
      return `
        <button class="module-card${active}" type="button" data-module="${moduleName}">
          <div class="module-row-main">
            <div class="module-title">${window.FDUtils.escapeHtml(info.display_name)}</div>
            <span class="mini-pill ${fail ? "fail" : (skip ? "skip" : (waived ? "waived" : "pass"))}">${pass}/${info.total || 0}</span>
          </div>
          <div class="module-meta">
            失败 ${fail} · 跳过 ${skip} · 豁免 ${waived}
          </div>
        </button>
      `;
    }).join("");
    root.querySelectorAll("[data-module]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.currentModule = btn.dataset.module;
        state.currentFn = window.FDState.pickDefaultFn(state.currentModule);
        await window.FDLayout.loadCurrentFunction();
      });
    });
  }

  window.FDModuleNav = { renderModuleNav };
})();
