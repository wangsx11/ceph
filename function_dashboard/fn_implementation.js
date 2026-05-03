(function () {
  function extractSections(markdown, titles) {
    const lines = String(markdown || "").split("\n");
    const chunks = [];
    for (const title of titles) {
      const start = lines.findIndex((line) => new RegExp(`^#{1,4}\\s+${title}\\s*$`).test(line.trim()));
      if (start < 0) continue;
      const section = [lines[start]];
      for (let i = start + 1; i < lines.length; i += 1) {
        if (/^#{1,2}\s+/.test(lines[i].trim())) break;
        section.push(lines[i]);
      }
      chunks.push(section.join("\n").trim());
    }
    return chunks.join("\n\n");
  }

  function fallbackImplementation(detail) {
    const raw = detail.raw || {};
    const lines = [
      `## 实现概览`,
      `浏览器按钮通过 Flask 功能验收接口触发后台白名单脚本，脚本按该功能点的验收口径调用数据面或控制面接口，并将页面执行结果写入独立历史目录。`,
      ``,
      `## 当前完成情况`,
      `${raw.completion || detail.completion || "未完成"}`,
      ``,
      `## 测试入口`,
      `- 启动脚本：run.sh`,
      `- 测试脚本：run.py`,
      `- 页面执行结果：history/web_<timestamp>_<job_id>/`
    ];
    return lines.join("\n");
  }

  function renderImplementation(detail) {
    const raw = detail.raw || {};
    const implementationMd = extractSections(detail.fn_md, ["实现位置", "测试方案", "实现"]);
    const md = implementationMd || fallbackImplementation(detail);
    const body = `
      <div class="kv-grid">
        <div class="kv-k">当前完成情况</div>
        <div class="kv-v">${window.FDUtils.completionBadge(raw.completion || detail.completion || "未完成")}</div>
        <div class="kv-k">控制面入口</div>
        <div class="kv-v">浏览器按钮调用 Flask 功能验收接口，后台执行白名单脚本</div>
        <div class="kv-k">测试脚本路径</div>
        <div class="kv-v">见“测试脚本展示”窗格</div>
      </div>
      <div style="margin-top:12px">${window.FDUtils.renderMarkdown(md)}</div>
    `;
    document.getElementById("implementation-pane").innerHTML = window.FDUtils.pane("设计与实现说明", body);
  }

  window.FDImplementation = { renderImplementation };
})();
