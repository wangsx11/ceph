(function () {
  const tabs = ["结果摘要", "原始结果"];

  function collectEnv() {
    const env = { ...window.FDState.state.env };
    window.FDState.state.env = env;
    return env;
  }

  function materialContent(tab, detail) {
    if (tab === "原始结果") return JSON.stringify(detail.raw || {}, null, 2);
    return detail.summary_md || "暂无结果摘要";
  }

  function renderMaterialTabs(detail) {
    const active = tabs.includes(window.FDState.state.scriptTab)
      ? window.FDState.state.scriptTab
      : "结果摘要";
    window.FDState.state.scriptTab = active;
    const tabHtml = tabs.map((tab) => `
      <button class="tab-btn ${tab === active ? "active" : ""}" type="button" data-material-tab="${tab}">
        ${window.FDUtils.escapeHtml(tab)}
      </button>
    `).join("");
    return `
      <div class="material-block">
        <div class="tab-row">${tabHtml}</div>
        <div class="code-box">${window.FDUtils.escapeHtml(materialContent(active, detail))}</div>
      </div>
    `;
  }

  function renderRunner(detail, job) {
    const running = job && (job.state === "queued" || job.state === "running");
    const jobText = job
      ? `任务状态：${job.state === "finished" ? "已完成" : (job.state === "failed" ? "执行失败" : "正在执行")}`
      : "尚未从页面发起执行";
    const body = `
      <div class="runner-controls">
        <button id="run-one-btn" class="btn primary" type="button" ${running ? "disabled" : ""}>
          ${running ? "执行中..." : "运行当前性能点"}
        </button>
        <span class="status-pill ${running ? "partial" : "muted"}">${window.FDUtils.escapeHtml(jobText)}</span>
      </div>
      <div id="runner-error" class="error" style="margin-top:10px">${window.FDUtils.escapeHtml((job && job.error) || "")}</div>
      ${renderMaterialTabs(detail)}
    `;
    document.getElementById("runner-pane").innerHTML = window.FDUtils.pane("执行与结果", body);
    const btn = document.getElementById("run-one-btn");
    if (btn) {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const env = collectEnv();
          const resp = await window.FDApi.runOne(window.FDState.state.currentModule, window.FDState.state.currentFn, env);
          window.FDState.state.currentJob = { job_id: resp.job_id, state: "queued" };
          window.FDRunner.pollJob(resp.job_id);
          renderRunner(detail, window.FDState.state.currentJob);
        } catch (err) {
          document.getElementById("runner-error").textContent = err.message;
          btn.disabled = false;
        }
      });
    }
    document.querySelectorAll("[data-material-tab]").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => {
        window.FDState.state.scriptTab = tabBtn.dataset.materialTab;
        renderRunner(detail, window.FDState.state.currentJob);
      });
    });
  }

  async function pollJob(jobId) {
    clearInterval(window.FDState.state.pollTimer);
    window.FDState.state.pollTimer = setInterval(async () => {
      try {
        const job = await window.FDApi.fetchJob(jobId);
        window.FDState.state.currentJob = job;
        window.FDResult.renderResult(window.FDState.state.currentDetail, job);
        renderRunner(window.FDState.state.currentDetail, job);
        if (job.state === "finished" || job.state === "failed") {
          clearInterval(window.FDState.state.pollTimer);
          const runAllBtn = document.getElementById("run-all-btn");
          if (runAllBtn) {
            runAllBtn.disabled = false;
            runAllBtn.textContent = "运行全部性能测试";
          }
          await window.FDLayout.refreshSummary(false);
          await window.FDLayout.loadCurrentFunction();
        }
      } catch (err) {
        clearInterval(window.FDState.state.pollTimer);
        const runAllBtn = document.getElementById("run-all-btn");
        if (runAllBtn) {
          runAllBtn.disabled = false;
          runAllBtn.textContent = "运行全部性能测试";
        }
        window.FDState.state.currentJob = {
          ...(window.FDState.state.currentJob || {}),
          state: "failed",
          error: `任务状态不可用：${err.message}`
        };
        try {
          await window.FDLayout.refreshSummary(false);
          await window.FDLayout.loadCurrentFunction();
        } catch (_refreshErr) {
          renderRunner(window.FDState.state.currentDetail, window.FDState.state.currentJob);
        }
      }
    }, 1500);
  }

  window.FDRunner = { renderRunner, pollJob, collectEnv };
})();
