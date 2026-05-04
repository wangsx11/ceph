(function () {
  function mdSection(text, title) {
    const lines = String(text || "").split("\n");
    const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const start = lines.findIndex((line) => new RegExp(`^#{1,4}\\s+${escaped}\\s*$`).test(line.trim()));
    if (start < 0) return "";
    const level = (/^(#{1,4})\s+/.exec(lines[start].trim()) || ["", "##"])[1].length;
    const out = [];
    for (let i = start + 1; i < lines.length; i += 1) {
      const heading = /^(#{1,4})\s+/.exec(lines[i].trim());
      if (heading && heading[1].length <= level) break;
      out.push(lines[i]);
    }
    return out.join("\n").trim();
  }

  function firstSection(text, titles) {
    for (const title of titles) {
      const value = mdSection(text, title);
      if (value) return value;
    }
    return "";
  }

  function stripNoise(markdown) {
    return String(markdown || "")
      .replace(/最近一次验证结果：[\s\S]*?(?=\n## |\n# |$)/g, "")
      .replace(/### 脚本入口[\s\S]*?(?=\n### |\n## |\n# |$)/g, "")
      .replace(/输出文件写入.*$/gm, "")
      .trim();
  }

  function briefLines(markdown, maxLines) {
    const lines = String(markdown || "")
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const visible = lines.slice(0, maxLines);
    if (lines.length > maxLines) visible.push(`另有 ${lines.length - maxLines} 行，查看结果摘要或原始结果。`);
    return visible;
  }

  function renderBrief(markdown, maxLines) {
    const lines = briefLines(stripNoise(markdown), maxLines);
    if (!lines.length) return `<p>暂无说明</p>`;
    const html = lines.map((line) => {
      if (/^#{1,4}\s+/.test(line)) {
        return `<div class="brief-subtitle">${window.FDUtils.escapeHtml(line.replace(/^#{1,4}\s+/, ""))}</div>`;
      }
      if (/^[-*+]\s+/.test(line)) {
        return `<p class="brief-bullet">${window.FDUtils.escapeHtml(line.replace(/^[-*+]\s+/, ""))}</p>`;
      }
      if (/^\d+\.\s+/.test(line)) {
        return `<p class="brief-bullet">${window.FDUtils.escapeHtml(line.replace(/^\d+\.\s+/, ""))}</p>`;
      }
      return `<p>${window.FDUtils.escapeHtml(line)}</p>`;
    }).join("");
    return `<div class="brief-text">${html}</div>`;
  }

  function hasDashboardCopy(copy) {
    if (!copy || typeof copy !== "object") return false;
    return Boolean(
      copy.goal ||
      copy.implementation ||
      (Array.isArray(copy.prerequisites) && copy.prerequisites.length) ||
      (Array.isArray(copy.test_plan) && copy.test_plan.length)
    );
  }

  function renderCopyMarkdown(markdown) {
    const lines = String(markdown || "")
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (!lines.length) return `<p>暂无说明</p>`;
    const html = lines.map((line) => {
      if (/^[-*+]\s+/.test(line)) {
        return `<p class="brief-bullet">${window.FDUtils.escapeHtml(line.replace(/^[-*+]\s+/, ""))}</p>`;
      }
      if (/^\d+\.\s+/.test(line)) {
        return `<p class="brief-bullet">${window.FDUtils.escapeHtml(line.replace(/^\d+\.\s+/, ""))}</p>`;
      }
      if (/^#{1,4}\s+/.test(line)) {
        return `<div class="brief-subtitle">${window.FDUtils.escapeHtml(line.replace(/^#{1,4}\s+/, ""))}</div>`;
      }
      return `<p>${window.FDUtils.escapeHtml(line)}</p>`;
    }).join("");
    return `<div class="brief-text">${html}</div>`;
  }

  function renderCopyList(items) {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!list.length) return `<p>暂无说明</p>`;
    return `
      <ul class="section-list">
        ${list.map((item) => `<li>${window.FDUtils.escapeHtml(item)}</li>`).join("")}
      </ul>
    `;
  }

  function renderDashboardCopy(copy) {
    const body = `
      <div class="brief-stack">
        <section class="brief-section">
          <h3>验证目标</h3>
          ${renderCopyMarkdown(copy.goal)}
        </section>
        <section class="brief-section">
          <h3>实现方案</h3>
          ${renderCopyMarkdown(copy.implementation)}
        </section>
        <section class="brief-section">
          <h3>测试方案</h3>
          <div class="brief-subtitle">前置条件</div>
          ${renderCopyList(copy.prerequisites)}
          <div class="brief-subtitle">测试方案</div>
          ${renderCopyList(copy.test_plan)}
        </section>
      </div>
    `;
    document.getElementById("requirement-pane").innerHTML = window.FDUtils.pane("验证与实现", body);
  }

  function fallbackImplementation(detail) {
    const raw = detail.raw || {};
    const calls = Array.isArray(raw.rpc_calls)
      ? raw.rpc_calls.map((item) => item && (item.rpc || item.name || item.op || item.method)).filter(Boolean)
      : [];
    if (calls.length) {
      const uniq = [...new Set(calls)].slice(0, 6);
      return `页面按钮通过 Flask 性能验收接口触发该性能点脚本，脚本调用真实数据面接口或压测二进制完成验收。\n- 关键调用：${uniq.join("、")}`;
    }
    return "页面按钮通过 Flask 性能验收接口触发该性能点脚本，脚本按性能验收口径调用真实数据面、压测二进制或存储测试工具，并写入可复查结果。";
  }

  function renderRequirement(detail) {
    const copy = detail.dashboard_copy || {};
    if (hasDashboardCopy(copy)) {
      renderDashboardCopy(copy);
      return;
    }
    const raw = detail.raw || {};
    const md = detail.fn_md || "暂无功能需求文档";
    const goal = raw.description || firstSection(md, ["功能点", "性能点", "指标要求"]) || "见结果摘要";
    const implementation = firstSection(md, ["实现", "实现位置"]) || fallbackImplementation(detail);
    const testPlan = firstSection(md, ["测试方案", "完成判据"]) || "见结果摘要";
    const body = `
      <div class="brief-stack">
        <section class="brief-section">
          <h3>验证目标</h3>
          ${renderBrief(goal, 4)}
        </section>
        <section class="brief-section">
          <h3>实现方案</h3>
          ${renderBrief(implementation, 7)}
        </section>
        <section class="brief-section">
          <h3>测试方案</h3>
          ${renderBrief(testPlan, 8)}
        </section>
      </div>
    `;
    document.getElementById("requirement-pane").innerHTML = window.FDUtils.pane("验证与实现", body);
  }

  window.FDRequirement = { renderRequirement };
})();
