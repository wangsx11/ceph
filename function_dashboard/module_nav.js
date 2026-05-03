(function () {
  function renderModuleNav() {
    const { state, moduleInfo } = window.FDState;
    const root = document.getElementById("module-nav");
    root.innerHTML = state.moduleOrder.map((moduleName) => {
      const info = moduleInfo(moduleName);
      if (!info) return "";
      const counts = info.execution_counts_text || {};
      const active = moduleName === state.currentModule ? " active" : "";
      return `
        <button class="module-card${active}" type="button" data-module="${moduleName}">
          <div class="module-title">${window.FDUtils.escapeHtml(info.display_name)}</div>
          <div class="module-stats">
            <span class="mini-pill pass">通过 ${counts["通过"] || 0}</span>
            <span class="mini-pill fail">失败 ${counts["失败"] || 0}</span>
            <span class="mini-pill skip">跳过 ${counts["跳过"] || 0}</span>
            <span class="mini-pill waived">豁免 ${counts["豁免"] || 0}</span>
            <span class="mini-pill muted">待执行 ${info.pending || 0}</span>
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
