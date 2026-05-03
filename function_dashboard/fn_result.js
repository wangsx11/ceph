(function () {
  function renderResult(detail, job) {
    const raw = detail.raw || {};
    const isHistory = detail.result_source === "前端执行历史";
    const evidence = Array.isArray(raw.evidence) ? raw.evidence : [];
    const env = raw.env || {};
    const jobLog = job && job.stdout_tail
      ? `<h3>实时输出</h3><div class="log-box">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(job.stdout_tail))}</div>`
      : "";
    const body = `
      ${isHistory ? "" : `<p class="muted" style="margin-bottom:12px">该功能点尚未从当前页面触发执行，下方为命令行基线参考结果。</p>`}
      <div class="kv-grid">
        <div class="kv-k">结果来源</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(detail.result_source || "基线结果")}</div>
        <div class="kv-k">最近运行时间</div>
        <div class="kv-v">${window.FDUtils.fmtTime(raw.finished_at || raw.generated_at)}</div>
        <div class="kv-k">${isHistory ? "当前状态" : "基线状态"}</div>
        <div class="kv-v">${window.FDUtils.badge(raw.status || detail.status, detail.status_text)}</div>
        <div class="kv-k">完成情况</div>
        <div class="kv-v">${window.FDUtils.completionBadge(raw.completion || detail.completion || "未完成")}</div>
        <div class="kv-k">日志路径</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(detail.history_dir || raw.log || "暂无"))}</div>
      </div>
      <h3>关键证据</h3>
      ${window.FDUtils.renderList(evidence)}
      <h3>环境信息</h3>
      <div class="code-box">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(JSON.stringify(env, null, 2)))}</div>
      ${jobLog}
    `;
    document.getElementById("result-pane").innerHTML = window.FDUtils.pane("测试结果展示", body);
  }

  window.FDResult = { renderResult };
})();
