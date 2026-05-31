(function () {
  const tabs = ["结果摘要", "原始结果"];
  const DEFAULT_RAW_PATHS = ["status", "completion", "passed"];
  const DEFAULT_RAW_CONTAINERS = ["evidence"];
  const RAW_HIGHLIGHTS = {
    "storage/FN-1": {
      paths: ["details.nvme.get.hit", "details.hdd.get.hit"]
    },
    "storage/FN-2": {
      paths: ["details.manual.get.hit", "details.auto.cold_get.hit", "details.auto.hot_final.hit"]
    },
    "storage/FN-3": {
      paths: [
        "details.stride.get.hit",
        "details.markov.get_b.hit",
        "details.markov.after.prefetch_loaded",
        "details.markov.after.prefetch_hits"
      ]
    },
    "storage/FN-4": {
      paths: [
        "details.after_compress.objects",
        "details.after_compress.saved_bytes",
        "details.after_dedup.duplicate_objects",
        "details.get_a.hit",
        "details.get_b.hit"
      ]
    },
    "storage/FN-5": {
      paths: [
        "details.after.fg_write_ops",
        "details.after.fg_read_ops",
        "details.after.bg_write_ops",
        "details.after.bg_read_ops",
        "details.fg.get.hit",
        "details.bg.get.hit"
      ]
    },
    "storage/FN-6": {
      paths: [
        "details.sim.captured_events",
        "details.capture_stats.pushed_events",
        "details.capture_stats.flushed_events",
        "details.wal_scan.events",
        "details.wal_scan.truncated_or_bad"
      ]
    },
    "rdma/FN-1": {
      paths: [
        "details.has_qp",
        "details.has_tcp",
        "details.has_oob",
        "details.cluster.peer_alive",
        "details.tcp_put.transport"
      ]
    },
    "rdma/FN-2": {
      paths: [
        "details.batch.ok_n",
        "details.batch.replicated_n",
        "details.batch.degraded_n"
      ]
    },
    "rdma/FN-3": {
      paths: [
        "details.has_qos",
        "details.hi.qos.priority",
        "details.hi.qos.qp_idx",
        "details.lo.qos.priority",
        "details.lo.qos.qp_idx",
        "details.hi_peer.ok",
        "details.lo_peer.ok"
      ]
    },
    "rdma/FN-4": {
      paths: [
        "details.gdr_status_peer.local_gpu_enabled",
        "details.gdr_status_peer.local_gpu_name",
        "details.gdr_write.transport",
        "details.gdr_write.bytes",
        "details.gdr_write.degraded",
        "details.gdr_validate.mismatches",
        "details.gdr_readback.mismatches"
      ]
    },
    "rdma/FN-5": {
      paths: [
        "details.local_put.route_forwarded",
        "details.remote_put.route_forwarded",
        "details.remote_put.forward_transport",
        "details.remote_put.degraded",
        "details.remote_put.offset",
        "details.remote_put.qp_idx",
        "details.remote_peer_get.ok"
      ],
      containers: ["details.counts"]
    },
    "mempool/FN-1": {
      paths: [
        "details.put.transport",
        "details.put.degraded",
        "details.cluster.peer_alive",
        "details.cluster.peer_slab_rkey",
        "details.peer_get.ok"
      ]
    },
    "mempool/FN-2": {
      paths: [
        "details.put.ok",
        "details.get.hit",
        "details.peer_get.ok",
        "details.put.transport",
        "details.cluster.local_slab_len",
        "details.cluster.peer_slab_len"
      ]
    },
    "mempool/FN-3": {
      paths: [
        "details.pools.local.name",
        "details.pools.remote.name",
        "details.pools.peer_id",
        "details.pools.local.rkey",
        "details.pools.remote.rkey"
      ]
    },
    "mempool/FN-4": {
      paths: [
        "details.put.placement",
        "details.adaptive_gets[0].hit",
        "details.migrated_get.hit",
        "details.migrated_get.migrated",
        "details.local_get.hit"
      ]
    },
    "mempool/FN-5": {
      paths: [
        "details.denied_a_before.ok",
        "details.allow_a.ok",
        "details.get_a.val",
        "details.get_b.val"
      ],
      containers: ["details.list_after_deny.allowed"]
    },
    "mempool/FN-6": {
      paths: [
        "details.before.peer_alive",
        "details.mid.peer_alive",
        "details.put_during_outage.degraded",
        "details.get_during_outage.hit",
        "details.after.degraded_puts",
        "details.after.degraded_bytes",
        "details.recovery_status.peer_alive",
        "details.post_recovery.put.degraded",
        "details.post_recovery.peer_get.ok"
      ]
    }
  };

  function collectEnv() {
    const env = { ...window.FDState.state.env, ALLOW_DESTRUCTIVE: "0" };
    if (
      window.FDState.state.currentModule === "mempool" &&
      window.FDState.state.currentFn === "FN-6"
    ) {
      Object.assign(env, {
        ALLOW_DESTRUCTIVE: "1",
        PEER_SSH: env.PEER_SSH || "xfusion4",
        PEER_DP_PATH: env.PEER_DP_PATH || "/home/wangshouxin/native-rdma-web/native_rdma/build-current/bin/native_rdma_dp",
        FN6_RECOVERY_CMD: env.FN6_RECOVERY_CMD ||
          "cd native_rdma && LOCAL_HOST=xfusion3 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 NR_SKIP_FLASK=1 bash start.sh",
        NR_TRANSPORT: "rdma",
        NR_ASYNC_REPL: "0"
      });
    }
    window.FDState.state.env = env;
    return env;
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
    const key = `${detail.module}/${detail.fn_id}`;
    const spec = RAW_HIGHLIGHTS[key] || {};
    return {
      paths: new Set([...DEFAULT_RAW_PATHS, ...(spec.paths || [])]),
      containers: [...DEFAULT_RAW_CONTAINERS, ...(spec.containers || [])]
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

  function isWarningLine(path, value) {
    return path === "completion" && String(value || "").includes("部分");
  }

  function rawLine(text, highlighted, warning) {
    const cls = highlighted
      ? `raw-json-line raw-highlight${warning ? " raw-warning" : ""}`
      : "raw-json-line";
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
      .map((line) => rawLine(line.text, line.highlighted, isWarningLine(line.path, line.value)))
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
      ? `任务状态：${job.state === "finished" ? "已完成" : (job.state === "failed" ? "执行失败" : "正在执行")}`
      : "尚未从页面发起执行";
    const body = `
      <div class="runner-controls">
        <button id="run-one-btn" class="btn primary" type="button" ${running ? "disabled" : ""}>
          ${running ? "执行中..." : "运行当前功能点"}
        </button>
        <span class="status-pill ${running ? "partial" : "muted"}">${window.FDUtils.escapeHtml(jobText)}</span>
      </div>
      <div id="runner-error" class="error" style="margin-top:10px"></div>
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
