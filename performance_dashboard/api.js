(function () {
  async function requestJson(url, options) {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({ ok: false, error: "响应不是 JSON" }));
    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || `请求失败：${resp.status}`);
    }
    return data;
  }

  function activeProfile() {
    return (window.FDState && window.FDState.state && window.FDState.state.profile) || "presentation";
  }

  function fetchSummary(profile) {
    const selected = profile || activeProfile();
    if (selected === "presentation") {
      return requestJson("/api/performance/presentation_summary");
    }
    return requestJson("/api/performance/summary");
  }

  function fetchFunction(moduleName, fnId, profile, options) {
    const selected = profile || activeProfile();
    const base = `/api/performance/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}`;
    const q = new URLSearchParams();
    if (selected === "presentation") q.set("profile", "presentation");
    const historyDir = options && options.history_dir ? String(options.history_dir) : "";
    if (historyDir) q.set("history_dir", historyDir);
    const suffix = q.toString() ? `?${q}` : "";
    return requestJson(`${base}${suffix}`);
  }

  function fetchFile(moduleName, fnId, name) {
    const q = new URLSearchParams({ name });
    return requestJson(`/api/performance/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}/file?${q}`);
  }

  function fetchLog(moduleName, fnId, name, tailBytes) {
    const q = new URLSearchParams({ name, tail_bytes: String(tailBytes || 65536) });
    return requestJson(`/api/performance/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}/log?${q}`);
  }

  function runOne(moduleName, fnId, env) {
    return requestJson("/api/performance/run_one", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module: moduleName, fn_id: fnId, env: env || {} })
    });
  }

  function runAll(env, profile) {
    return requestJson("/api/performance/run_all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: env || {}, profile: profile || activeProfile() })
    });
  }

  function fetchJob(jobId) {
    return requestJson(`/api/performance/jobs/${encodeURIComponent(jobId)}`);
  }

  window.FDApi = {
    fetchSummary,
    fetchFunction,
    fetchFile,
    fetchLog,
    runOne,
    runAll,
    fetchJob
  };
})();
