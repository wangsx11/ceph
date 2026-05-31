(function () {
  const tabs = ["结果摘要", "原始结果"];
  const DEFAULT_RAW_PATHS = ["status", "passed"];
  const RAW_HIGHLIGHTS = {
    "PF-1": {
      paths: ["ops_per_sec", "bw_util_pct", "ops_fail", "ops_degraded", "bw_fail", "bw_degraded"],
      containers: ["thresholds"]
    },
    "PF-2": {
      paths: ["lat_avg_us", "lat_p99_us", "samples", "ops_fail", "ops_degraded"],
      containers: ["thresholds"]
    },
    "PF-3": {
      paths: ["gain_pct", "threshold_gain_pct", "hi_ops", "lo_ops", "hi_fail", "lo_fail", "qos_mode"]
    },
    "PF-4": {
      paths: [
        "passed_a",
        "passed_b",
        "scenario_a.elapsed_ms",
        "scenario_b.elapsed_ms",
        "scenario_a.ops_ok",
        "scenario_b.ops_ok",
        "scenario_a.ops_fail",
        "scenario_b.ops_fail",
        "scenario_a.ops_degraded",
        "scenario_b.ops_degraded"
      ]
    },
    "PF-5": {
      paths: ["mb_per_sec", "threshold_mbs", "ops_per_sec", "ops_fail", "ops_degraded"]
    },
    "PF-6": {
      paths: ["write_gbs", "read_gbs", "read_hit_ratio", "write_degraded", "read_fail", "val_size"]
    },
    "PF-7": {
      paths: ["lat_p999_us", "success_writes", "failed_writes", "backend", "raid5_confirmed", "strict_acceptance_passed", "presentation_passed"],
      containers: ["thresholds"]
    },
    "PF-8": {
      paths: ["speedup", "threshold_speedup", "events_per_sec", "entities", "events", "captured_dropped"]
    },
    "PF-9": {
      paths: ["overhead_pct", "savings_pct", "scale_gain_pct", "threads_multi"],
      containers: ["thresholds"]
    }
  };

  function collectEnv() {
    const env = { ...window.FDState.state.env };
    window.FDState.state.env = env;
    return env;
  }

  function rememberCompletedJob(job) {
    if (!job || !["finished", "failed"].includes(job.state) || !job.history_dir) return null;
    const completed = {
      job_id: job.job_id,
      kind: job.kind || "run_one",
      module: job.module || window.FDState.state.currentModule,
      fn_id: job.fn_id || window.FDState.state.currentFn,
      history_dir: job.history_dir
    };
    window.FDState.state.lastCompletedJob = completed;
    return completed;
  }

  function joinPath(parent, key) {
    return parent ? `${parent}.${key}` : key;
  }

  function isPlainObject(value) {
    return value && typeof value === "object" && !Array.isArray(value);
  }

  function primitiveJson(value) {
    return JSON.stringify(value);
  }

  function rawHighlightSpec(detail) {
    const spec = RAW_HIGHLIGHTS[detail.fn_id] || {};
    return {
      paths: new Set([...DEFAULT_RAW_PATHS, ...(spec.paths || [])]),
      containers: spec.containers || []
    };
  }

  function pathInContainer(path, containers) {
    return containers.some((container) =>
      path === container ||
      path.startsWith(`${container}.`) ||
      path.startsWith(`${container}[`)
    );
  }

  function shouldHighlight(path, spec) {
    return spec.paths.has(path) || pathInContainer(path, spec.containers);
  }

  function rawLine(text, highlighted) {
    const cls = highlighted ? "raw-json-line raw-highlight" : "raw-json-line";
    return `<span class="${cls}">${window.FDUtils.escapeHtml(text)}</span>`;
  }

  function renderJsonLines(value, path, level, spec) {
    const indent = "  ".repeat(level);
    if (Array.isArray(value)) {
      if (!value.length) return [{ text: "[]", path, value, highlighted: shouldHighlight(path, spec) }];
      const lines = [{ text: "[", path, value, highlighted: shouldHighlight(path, spec) }];
      value.forEach((item, index) => {
        const itemPath = `${path}[${index}]`;
        const last = index === value.length - 1;
        const child = renderJsonLines(item, itemPath, level + 1, spec);
        child[0].text = `${"  ".repeat(level + 1)}${child[0].text}`;
        child[child.length - 1].text += last ? "" : ",";
        lines.push(...child);
      });
      lines.push({ text: `${indent}]`, path, value, highlighted: false });
      return lines;
    }
    if (isPlainObject(value)) {
      const keys = Object.keys(value);
      if (!keys.length) return [{ text: "{}", path, value, highlighted: shouldHighlight(path, spec) }];
      const lines = [{ text: "{", path, value, highlighted: shouldHighlight(path, spec) }];
      keys.forEach((key, index) => {
        const childPath = joinPath(path, key);
        const childValue = value[key];
        const last = index === keys.length - 1;
        if (Array.isArray(childValue) || isPlainObject(childValue)) {
          const opener = Array.isArray(childValue) ? "[" : "{";
          const closer = Array.isArray(childValue) ? "]" : "}";
          const childLines = renderJsonLines(childValue, childPath, level + 1, spec);
          childLines.shift();
          childLines.pop();
          lines.push({
            text: `${"  ".repeat(level + 1)}"${key}": ${opener}`,
            path: childPath,
            value: childValue,
            highlighted: shouldHighlight(childPath, spec)
          });
          lines.push(...childLines);
          lines.push({
            text: `${"  ".repeat(level + 1)}${closer}${last ? "" : ","}`,
            path: childPath,
            value: childValue,
            highlighted: false
          });
        } else {
          lines.push({
            text: `${"  ".repeat(level + 1)}"${key}": ${primitiveJson(childValue)}${last ? "" : ","}`,
            path: childPath,
            value: childValue,
            highlighted: shouldHighlight(childPath, spec)
          });
        }
      });
      lines.push({ text: `${indent}}`, path, value, highlighted: false });
      return lines;
    }
    return [{ text: primitiveJson(value), path, value, highlighted: shouldHighlight(path, spec) }];
  }

  function renderHighlightedRaw(detail) {
    const spec = rawHighlightSpec(detail);
    return renderJsonLines(detail.raw || {}, "", 0, spec)
      .map((line) => rawLine(line.text, line.highlighted))
      .join("");
  }

  function materialContent(tab, detail) {
    if (tab === "原始结果") return renderHighlightedRaw(detail);
    return window.FDUtils.escapeHtml(detail.summary_md || "暂无结果摘要");
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
        <div class="code-box ${active === "原始结果" ? "raw-json-box" : ""}">${materialContent(active, detail)}</div>
      </div>
    `;
  }

  function renderRunner(detail, job) {
    const running = job && (job.state === "queued" || job.state === "running");
    const jobText = job
      ? `任务状态：${job.state === "finished" || job.state === "failed" ? "已完成" : "正在执行"}`
      : "尚未从页面发起执行";
    const body = `
      <div class="runner-controls">
        <button id="run-one-btn" class="btn primary" type="button" ${running ? "disabled" : ""}>
          ${running ? "执行中..." : "运行完整单项"}
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
          env.PERFORMANCE_PROFILE = "full";
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
            runAllBtn.textContent = "运行演示性能流";
          }
          const completed = rememberCompletedJob(job);
          await window.FDLayout.refreshSummary(false);
          await window.FDLayout.loadCurrentFunction(
            completed ? { history_dir: completed.history_dir, keepJob: true } : undefined
          );
        }
      } catch (err) {
        clearInterval(window.FDState.state.pollTimer);
        const runAllBtn = document.getElementById("run-all-btn");
        if (runAllBtn) {
          runAllBtn.disabled = false;
          runAllBtn.textContent = "运行演示性能流";
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
