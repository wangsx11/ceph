(function () {
  function mdSection(text, title) {
    const lines = String(text || "").split("\n");
    const start = lines.findIndex((line) => line.includes(title));
    if (start < 0) return "";
    const out = [];
    for (let i = start + 1; i < lines.length; i += 1) {
      if (/^#{1,4}\s+/.test(lines[i])) break;
      out.push(lines[i]);
    }
    return out.join("\n").trim();
  }

  function renderRequirement(detail) {
    const raw = detail.raw || {};
    const md = detail.fn_md || "暂无功能需求文档";
    const body = `
      <div class="kv-grid">
        <div class="kv-k">功能点名称</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(detail.function_display_name)}</div>
        <div class="kv-k">来源要求</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(raw.source || ""))}</div>
        <div class="kv-k">功能点说明</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(raw.description || mdSection(detail.fn_md, "功能需求") || "见下方原始说明"))}</div>
        <div class="kv-k">完成判据</div>
        <div class="kv-v">${window.FDUtils.escapeHtml(window.FDUtils.sanitizeInternal(raw.criterion || mdSection(detail.fn_md, "完成判据") || "见下方原始说明"))}</div>
      </div>
      <div style="margin-top:12px">${window.FDUtils.renderMarkdown(md)}</div>
    `;
    document.getElementById("requirement-pane").innerHTML = window.FDUtils.pane("功能需求说明", body);
  }

  window.FDRequirement = { renderRequirement };
})();
