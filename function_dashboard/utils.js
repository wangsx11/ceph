(function () {
  const statusClass = {
    PASS: "pass",
    FAIL: "fail",
    SKIP: "skip",
    WAIVED: "waived"
  };
  const statusText = {
    PASS: "通过",
    FAIL: "失败",
    SKIP: "跳过",
    WAIVED: "豁免"
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function badge(status, text) {
    const s = String(status || "").toUpperCase();
    return `<span class="mini-pill ${statusClass[s] || "muted"}">${escapeHtml(text || statusText[s] || "未知")}</span>`;
  }

  function executionBadge(row) {
    if (!row || row.executed === false || row.result_source !== "前端执行历史") {
      return `<span class="mini-pill muted">待页面执行</span>`;
    }
    return badge(row.status, row.display_status_text || row.status_text);
  }

  function completionBadge(value) {
    if (!value) return "";
    const cls = value === "完成" ? "pass" : (value === "硬件/环境豁免" ? "waived" : "partial");
    return `<span class="mini-pill ${cls}">${escapeHtml(value)}</span>`;
  }

  function sanitizeInternal(value) {
    return String(value ?? "")
      .replace(/\b(storage|rdma|mempool)\b/g, "模块")
      .replace(/FN-\d+/g, "功能点");
  }

  function renderList(items) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) return `<p>暂无记录</p>`;
    return `<ul class="section-list">${list.map((item) => `<li>${escapeHtml(sanitizeInternal(item))}</li>`).join("")}</ul>`;
  }

  function renderMarkdown(md) {
    const text = sanitizeInternal(md || "");
    const lines = String(text).replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let i = 0;
    let inCode = false;
    let codeBuf = [];
    let paraBuf = [];
    let listType = null;
    let listBuf = [];

    function flushPara() {
      if (!paraBuf.length) return;
      out.push(`<p>${inline(paraBuf.join(" ").trim())}</p>`);
      paraBuf = [];
    }

    function flushList() {
      if (!listBuf.length) return;
      const tag = listType === "ol" ? "ol" : "ul";
      out.push(`<${tag}>${listBuf.map((item) => `<li>${inline(item)}</li>`).join("")}</${tag}>`);
      listBuf = [];
      listType = null;
    }

    function flushCode() {
      if (!codeBuf.length) return;
      out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
      codeBuf = [];
    }

    function inline(value) {
      return escapeHtml(value)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
    }

    while (i < lines.length) {
      const line = lines[i];
      if (line.trim().startsWith("```")) {
        if (inCode) {
          flushCode();
          inCode = false;
        } else {
          flushPara();
          flushList();
          inCode = true;
        }
        i += 1;
        continue;
      }
      if (inCode) {
        codeBuf.push(line);
        i += 1;
        continue;
      }
      const trimmed = line.trim();
      if (!trimmed) {
        flushPara();
        flushList();
        i += 1;
        continue;
      }
      const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed);
      if (heading) {
        flushPara();
        flushList();
        out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
        i += 1;
        continue;
      }
      const ordered = /^\d+\.\s+(.*)$/.exec(trimmed);
      const unordered = /^[-*+]\s+(.*)$/.exec(trimmed);
      if (ordered || unordered) {
        flushPara();
        const currentType = ordered ? "ol" : "ul";
        if (listType && listType !== currentType) flushList();
        listType = currentType;
        listBuf.push((ordered || unordered)[1]);
        i += 1;
        continue;
      }
      if (listType) flushList();
      paraBuf.push(trimmed);
      i += 1;
    }
    flushPara();
    flushList();
    flushCode();
    return `<div class="markdown-rendered">${out.join("") || "<p>暂无内容</p>"}</div>`;
  }

  function pane(title, body, extra) {
    return `
      <div class="pane-head">
        <div class="pane-title">${escapeHtml(title)}</div>
        <div>${extra || ""}</div>
      </div>
      <div class="pane-body">${body}</div>
    `;
  }

  function fmtTime(value) {
    if (!value) return "暂无";
    return escapeHtml(String(value));
  }

  window.FDUtils = {
    escapeHtml,
    badge,
    executionBadge,
    completionBadge,
    renderMarkdown,
    sanitizeInternal,
    renderList,
    pane,
    fmtTime,
    statusClass,
    statusText
  };
})();
