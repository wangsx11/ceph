(function () {
  function renderHeaderSummary() {
    const summary = window.FDState.state.summary;
    const status = document.getElementById("global-status");
    if (!summary) {
      status.textContent = "状态加载中";
      return;
    }
    const totals = summary.totals || {};
    status.textContent = `${totals.total || 0} 项 · 通过 ${totals.PASS || 0} · 失败 ${totals.FAIL || 0} · 跳过 ${totals.SKIP || 0} · 豁免 ${totals.WAIVED || 0}`;
  }

  function renderModuleHead() {
    const info = window.FDState.moduleInfo(window.FDState.state.currentModule);
    if (!info) return;
    const counts = info.status_counts_text || {};
    document.getElementById("module-title").textContent = info.display_name;
    document.getElementById("module-summary").textContent =
      `${info.total || 0} 项性能验收 · 通过 ${counts["通过"] || 0} · 失败 ${counts["失败"] || 0} · 跳过 ${counts["跳过"] || 0} · 豁免 ${counts["豁免"] || 0}`;
  }

  function renderQuickStrip() {
    const detail = window.FDState.state.currentDetail;
    const root = document.getElementById("quick-strip");
    if (!root) return;
    if (!detail) {
      root.innerHTML = `
        <div class="quick-main">
          <div class="quick-title">正在读取性能点</div>
          <div class="quick-meta">结果加载中</div>
        </div>
      `;
      return;
    }
    const raw = detail.raw || {};
    const status = raw.status || detail.status;
    const completion = raw.completion || detail.completion || "";
    const finished = raw.finished_at || raw.generated_at || "";
    root.innerHTML = `
      <div class="quick-main">
        <div class="quick-title">${window.FDUtils.escapeHtml(detail.function_display_name)}</div>
        <div class="quick-meta">
          ${window.FDUtils.escapeHtml(detail.result_source || "基线结果")}
          ${finished ? ` · ${window.FDUtils.fmtTime(finished)}` : ""}
        </div>
      </div>
      <div class="quick-badges">
        ${window.FDUtils.badge(status, detail.status_text)}
        ${completion ? window.FDUtils.completionBadge(completion) : ""}
      </div>
    `;
  }

  function renderAll() {
    renderHeaderSummary();
    renderModuleHead();
    renderQuickStrip();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    if (window.FDState.state.currentDetail) {
      window.FDResult.renderResult(window.FDState.state.currentDetail, window.FDState.state.currentJob);
      window.FDRequirement.renderRequirement(window.FDState.state.currentDetail);
      window.FDRunner.renderRunner(window.FDState.state.currentDetail, window.FDState.state.currentJob);
    }
  }

  async function refreshSummary(resetSelection) {
    const summary = await window.FDApi.fetchSummary(window.FDState.state.profile);
    window.FDState.state.summary = summary;
    if (resetSelection) {
      window.FDState.state.currentModule = window.FDState.state.moduleOrder[0];
      window.FDState.state.currentFn = window.FDState.pickDefaultFn(window.FDState.state.currentModule);
    }
    renderHeaderSummary();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    renderModuleHead();
    renderQuickStrip();
  }

  function currentHistoryBinding() {
    const job = window.FDState.state.lastCompletedJob;
    if (!job || !job.history_dir) return null;
    if (job.kind !== "run_all" && job.fn_id !== window.FDState.state.currentFn) return null;
    return { history_dir: job.history_dir };
  }

  async function loadCurrentFunction(options) {
    const opts = options || {};
    renderModuleHead();
    renderQuickStrip();
    window.FDModuleNav.renderModuleNav();
    window.FDFnNav.renderFnNav();
    const binding = opts.history_dir ? opts : currentHistoryBinding();
    const detail = await window.FDApi.fetchFunction(
      window.FDState.state.currentModule,
      window.FDState.state.currentFn,
      window.FDState.state.profile,
      binding
    );
    window.FDState.state.currentDetail = detail;
    window.FDState.state.currentJob = opts.keepJob ? window.FDState.state.currentJob : null;
    renderAll();
  }

  async function runAll() {
    const btn = document.getElementById("run-all-btn");
    btn.disabled = true;
    btn.textContent = "正在执行...";
    try {
      const env = window.FDRunner.collectEnv ? window.FDRunner.collectEnv() : window.FDState.state.env;
      env.PERFORMANCE_PROFILE = window.FDState.state.profile;
      const resp = await window.FDApi.runAll(env, window.FDState.state.profile);
      window.FDState.state.currentJob = { job_id: resp.job_id, state: "queued" };
      window.FDRunner.pollJob(resp.job_id);
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
      btn.textContent = "运行演示性能流";
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
