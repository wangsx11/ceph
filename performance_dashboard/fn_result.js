(function () {
  function renderResult(detail, job) {
    const raw = detail.raw || {};
    const evidence = Array.isArray(detail.evidence)
      ? detail.evidence
      : (Array.isArray(raw.evidence) ? raw.evidence : []);
    const status = detail.status || raw.presentation_status || raw.status;
    const body = `
      <div class="result-summary">
        ${window.FDUtils.badge(status, window.FDUtils.statusText[String(status || "").toUpperCase()]).replace("mini-pill", "mini-pill result-badge")}
        <div>
          ${window.FDUtils.renderEvidence(evidence, 3)}
        </div>
      </div>
    `;
    document.getElementById("result-pane").innerHTML = window.FDUtils.pane("验收结论", body);
  }

  window.FDResult = { renderResult };
})();
