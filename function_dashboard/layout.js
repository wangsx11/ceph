(function () {
  function renderHeaderSummary() {
    const summary = window.FDState.state.summary;
    const status = document.getElementById("global-status");
    if (!summary) {
      status.textContent = "状态加载中";
      return;
    }
    const totals = summary.execution_totals || {};
    status.textContent = `页面已执行 ${totals.executed || 0}/${totals.total || 0} · 通过 ${totals.PASS || 0} / 失败 ${totals.FAIL || 0} / 跳过 ${totals.SKIP || 0} / 豁免 ${totals.WAIVED || 0}`;
  }

  function renderModuleHead() {
    const info = window.FDState.moduleInfo(window.FDState.state.currentModule);
    if (!info) return;
    const counts = info.execution_counts_text || {};
    document.getElementById("module-title").textContent = info.display_name;
    document.getElementById("module-summary").textContent =
      `页面已执行 ${info.executed || 0}/${info.total || 0}，通过 ${counts["通过"] || 0}，失败 ${counts["失败"] || 0}，跳过 ${counts["跳过"] || 0}，豁免 ${counts["豁免"] || 0}，待执行 ${info.pending || 0}`;
  }

  function renderAll() {
    renderHeaderSummary();
    renderModuleHead();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    if (window.FDState.state.currentDetail) {
      window.FDRequirement.renderRequirement(window.FDState.state.currentDetail);
      window.FDImplementation.renderImplementation(window.FDState.state.currentDetail);
      window.FDRunner.renderRunner(window.FDState.state.currentDetail, window.FDState.state.currentJob);
      window.FDResult.renderResult(window.FDState.state.currentDetail, window.FDState.state.currentJob);
      window.FDScriptViewer.renderScriptViewer(window.FDState.state.currentDetail);
    }
  }

  async function refreshSummary(resetSelection) {
    const summary = await window.FDApi.fetchSummary();
    window.FDState.state.summary = summary;
    if (resetSelection) {
      window.FDState.state.currentModule = window.FDState.state.moduleOrder[0];
      window.FDState.state.currentFn = window.FDState.pickDefaultFn(window.FDState.state.currentModule);
    }
    renderHeaderSummary();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    renderModuleHead();
  }

  async function loadCurrentFunction() {
    renderModuleHead();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    const detail = await window.FDApi.fetchFunction(window.FDState.state.currentModule, window.FDState.state.currentFn);
    window.FDState.state.currentDetail = detail;
    window.FDState.state.currentJob = null;
    renderAll();
  }

  async function runAll() {
    const btn = document.getElementById("run-all-btn");
    btn.disabled = true;
    btn.textContent = "正在执行...";
    try {
      const env = window.FDRunner.collectEnv ? window.FDRunner.collectEnv() : window.FDState.state.env;
      const resp = await window.FDApi.runAll(env);
      window.FDState.state.currentJob = { job_id: resp.job_id, state: "queued" };
      window.FDRunner.pollJob(resp.job_id);
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
      btn.textContent = "运行全部功能测试";
    }
  }

  async function init() {
    document.getElementById("refresh-btn").addEventListener("click", async () => {
      await refreshSummary(false);
      await loadCurrentFunction();
    });
    document.getElementById("run-all-btn").addEventListener("click", runAll);
    try {
      await refreshSummary(true);
      await loadCurrentFunction();
    } catch (err) {
      document.getElementById("global-status").textContent = `加载失败：${err.message}`;
    }
  }

  window.FDLayout = { init, refreshSummary, loadCurrentFunction };
  window.addEventListener("DOMContentLoaded", init);
})();
