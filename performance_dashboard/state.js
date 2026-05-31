(function () {
  const moduleOrder = ["performance"];
  const state = {
    moduleOrder,
    currentModule: "performance",
    currentFn: "PF-1",
    summary: null,
    currentDetail: null,
    currentJob: null,
    lastCompletedJob: null,
    pollTimer: null,
    scriptTab: "结果摘要",
    profile: "presentation",
    env: {
      CTRL_URL: window.location && window.location.origin ? window.location.origin : "http://127.0.0.1:5000",
      UDS: "/tmp/native_rdma-dp.sock",
      REQUIRE_PEER: "1",
      CURRENT_NODE: "A"
    }
  };

  function moduleInfo(moduleName) {
    return state.summary && state.summary.modules
      ? state.summary.modules[moduleName]
      : null;
  }

  function functionsFor(moduleName) {
    const info = moduleInfo(moduleName);
    return info && Array.isArray(info.functions) ? info.functions : [];
  }

  function pickDefaultFn(moduleName) {
    const rows = functionsFor(moduleName);
    const attention = rows.find((row) => row.attention);
    return (attention || rows[0] || {}).fn_id || "PF-1";
  }

  window.FDState = {
    state,
    moduleInfo,
    functionsFor,
    pickDefaultFn
  };
})();
