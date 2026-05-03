(function () {
  function envInputs() {
    const env = window.FDState.state.env;
    return `
      <div class="env-grid">
        <label>控制面地址<input data-env="CTRL_URL" value="${window.FDUtils.escapeHtml(env.CTRL_URL)}"></label>
        <label>通信套接字<input data-env="UDS" value="${window.FDUtils.escapeHtml(env.UDS)}"></label>
        <label>要求对端在线<input data-env="REQUIRE_PEER" value="${window.FDUtils.escapeHtml(env.REQUIRE_PEER)}"></label>
        <label>当前节点<input data-env="CURRENT_NODE" value="${window.FDUtils.escapeHtml(env.CURRENT_NODE)}"></label>
      </div>
    `;
  }

  function collectEnv() {
    const env = { ...window.FDState.state.env, ALLOW_DESTRUCTIVE: "0" };
    document.querySelectorAll("[data-env]").forEach((input) => {
      env[input.dataset.env] = input.value;
    });
    window.FDState.state.env = env;
    return env;
  }

  function renderRunner(detail, job) {
    const running = job && (job.state === "queued" || job.state === "running");
    const jobText = job
      ? `任务状态：${job.state === "finished" ? "已完成" : (job.state === "failed" ? "执行失败" : "正在执行")}`
      : "尚未从页面发起执行";
    const body = `
      <div class="runner-controls">
        <button id="run-one-btn" class="btn primary" type="button" ${running ? "disabled" : ""}>
          ${running ? "正在执行..." : "运行当前功能点测试"}
        </button>
        <span class="status-pill ${running ? "partial" : "muted"}">${window.FDUtils.escapeHtml(jobText)}</span>
      </div>
      <p>默认使用非破坏性参数执行；破坏性高可靠演练不会从此页面默认触发。</p>
      ${envInputs()}
      <div id="runner-error" class="error" style="margin-top:10px"></div>
    `;
    document.getElementById("runner-pane").innerHTML = window.FDUtils.pane("一键启动测试", body);
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
            runAllBtn.textContent = "运行全部功能测试";
          }
          await window.FDLayout.refreshSummary(false);
          await window.FDLayout.loadCurrentFunction();
        }
      } catch (err) {
        clearInterval(window.FDState.state.pollTimer);
      }
    }, 1500);
  }

  window.FDRunner = { renderRunner, pollJob, collectEnv };
})();
