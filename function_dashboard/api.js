(function () {
  async function requestJson(url, options) {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({ ok: false, error: "响应不是 JSON" }));
    if (!resp.ok || data.ok === false) {
      throw new Error(data.error || `请求失败：${resp.status}`);
    }
    return data;
  }

  function fetchSummary() {
    return requestJson("/api/functions/summary");
  }

  function fetchFunction(moduleName, fnId) {
    return requestJson(`/api/functions/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}`);
  }

  function fetchFile(moduleName, fnId, name) {
    const q = new URLSearchParams({ name });
    return requestJson(`/api/functions/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}/file?${q}`);
  }

  function fetchLog(moduleName, fnId, name, tailBytes) {
    const q = new URLSearchParams({ name, tail_bytes: String(tailBytes || 65536) });
    return requestJson(`/api/functions/fn/${encodeURIComponent(moduleName)}/${encodeURIComponent(fnId)}/log?${q}`);
  }

  function runOne(moduleName, fnId, env) {
    return requestJson("/api/functions/run_one", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ module: moduleName, fn_id: fnId, env: env || {} })
    });
  }

  function runAll(env) {
    return requestJson("/api/functions/run_all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: env || {} })
    });
  }

  function fetchJob(jobId) {
    return requestJson(`/api/functions/jobs/${encodeURIComponent(jobId)}`);
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
