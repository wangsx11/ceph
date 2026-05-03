(function () {
  const tabs = ["启动脚本", "测试脚本", "结果摘要", "原始结果", "最新日志"];

  function contentFor(tab, detail) {
    if (tab === "启动脚本") return detail.run_sh || "暂无启动脚本";
    if (tab === "测试脚本") return detail.run_py || "暂无测试脚本";
    if (tab === "结果摘要") return detail.summary_md || "暂无结果摘要";
    if (tab === "原始结果") return JSON.stringify(detail.raw || {}, null, 2);
    if (tab === "最新日志") {
      const logs = Array.isArray(detail.logs) ? detail.logs : [];
      if (!logs.length) return "暂无日志文件";
      return logs.map((item) => `${item.name}  ${item.size} bytes`).join("\n");
    }
    return "";
  }

  function renderScriptViewer(detail) {
    const active = window.FDState.state.scriptTab;
    const tabHtml = tabs.map((tab) => `
      <button class="tab-btn ${tab === active ? "active" : ""}" type="button" data-tab="${tab}">
        ${window.FDUtils.escapeHtml(tab)}
      </button>
    `).join("");
    const body = `
      <div class="tab-row">${tabHtml}</div>
      <div class="code-box">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(contentFor(active, detail)))}</div>
    `;
    document.getElementById("script-pane").innerHTML = window.FDUtils.pane("测试脚本展示", body);
    document.querySelectorAll("[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        window.FDState.state.scriptTab = btn.dataset.tab;
        renderScriptViewer(detail);
      });
    });
  }

  window.FDScriptViewer = { renderScriptViewer };
})();
