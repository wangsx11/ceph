// ============================================================
// m10_capture.js — 模块⑩：仿真运行时采集演示
// 调用 Flask /api/sim/*
// ============================================================

const SIM_API = (window.API_BASE || location.origin) + '/api/sim';

let simBusy     = false;
let simLastRun  = null;    // last RPC_SIM_RUN response
let simStats    = null;    // last RPC_SIM_CAPTURE_STATS
let simWal      = null;    // last wal_head response
let simInput    = {
  entities:        100000,
  events:          1000000,
  threads:         4,
  stress:          32,
  capture_every_n: 256
};
let simStatsTimer = null;

function renderM10() {
  const el = document.getElementById('pg-m10');
  if (!el) return;

  // top metrics
  const rr = simLastRun || {};
  const ss = simStats   || {};
  const wal = simWal    || {};

  const dropRate = (ss.pushed_events && ss.dropped_events != null)
    ? (100 * ss.dropped_events / (ss.pushed_events + ss.dropped_events)).toFixed(2)
    : '0.00';
  const flushRatio = (ss.pushed_events && ss.flushed_events != null)
    ? (100 * ss.flushed_events / ss.pushed_events).toFixed(1)
    : '0.0';

  // 事件预览表
  const evRows = (wal.events || []).map((e, i) => {
    const typeColor = e.type === 1 ? '#00e888'
                    : e.type === 2 ? '#a060ff' : '#ffb020';
    return `<tr>
      <td style="color:#5a7a96">${i + 1}</td>
      <td class="mono" style="color:#c0d8f0">${(e.ts_ns / 1e6).toFixed(3)} ms</td>
      <td class="mono" style="color:${typeColor}">${e.type_name}</td>
      <td class="mono" style="color:#e4edf6">${e.entity_id}</td>
      <td class="mono" style="color:${e.peer_id ? '#ffb020' : '#5a7a96'}">${e.peer_id || '-'}</td>
      <td class="mono" style="color:#5a7a96">${e.blob_len}B</td>
      <td class="mono" style="color:#5a7a96;font-size:.95rem">${e.blob_hex.slice(0, 24)}...</td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" style="color:#5a7a96;text-align:center;padding:20px">点击"刷新 WAL 预览"从采集日志读取头部事件</td></tr>';

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">仿真运行时采集（Object Attr + Interaction Event）</div>
        <div class="ctrl-status ${simBusy ? 'running' : 'idle'}">
          <div class="dot ${simBusy ? 'dot-pulse' : ''}" style="background:${simBusy ? '#00e888' : '#5a7a96'};width:6px;height:6px"></div>
          ${simBusy ? '仿真进行中...' : '就绪'}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0">
        SimEngine 每 <span class="mono" style="color:#c0d8f0">capture_every_n</span> 个 event 向 SimCapture 投递一条记录，
        背景线程 100ms 批刷到 <span class="mono" style="color:#c0d8f0">/tmp/nr_sim_capture/sim_&lt;tag&gt;.log</span>。
        事件类型交替为 ObjectAttr（奇数采样）/ InteractionEvent（偶数采样）。
      </div>

      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label">entities</span>
        <input id="sim-ent"  class="ctrl-input" style="width:100px" value="${simInput.entities}">
        <span class="ctrl-label">events</span>
        <input id="sim-evt"  class="ctrl-input" style="width:100px" value="${simInput.events}">
        <span class="ctrl-label">threads</span>
        <input id="sim-th"   class="ctrl-input" style="width:70px"  value="${simInput.threads}">
        <span class="ctrl-label">stress</span>
        <input id="sim-str"  class="ctrl-input" style="width:70px"  value="${simInput.stress}">
        <span class="ctrl-label">capture/N</span>
        <input id="sim-cap"  class="ctrl-input" style="width:80px"  value="${simInput.capture_every_n}">
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <button class="btn btn-primary btn-sm" onclick="simRun()"    ${simBusy ? 'disabled' : ''}>▶ 运行仿真</button>
        <button class="btn btn-warning btn-sm" onclick="simReset()"  ${simBusy ? 'disabled' : ''}>↻ 重置采集</button>
        <button class="btn btn-outline btn-sm" onclick="simRefreshStats()">刷新统计</button>
        <button class="btn btn-outline btn-sm" onclick="simRefreshWal()">刷新 WAL 预览</button>
      </div>
    </div>

    <div class="g4" style="margin-top:14px">
      ${metric('仿真 events/s', rr.events_per_sec ? (rr.events_per_sec / 1e6).toFixed(2) : '-', 'M', '#00d0f0')}
      ${metric('仿真 speedup', rr.speedup ? rr.speedup.toFixed(1) : '-', 'x', '#00e888')}
      ${metric('captured',    rr.captured_events ?? '-',         '', '#ffb020')}
      ${metric('wall_s',      rr.wall_s ? rr.wall_s.toFixed(3) : '-', 's', '#a060ff')}
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('采集统计', '📈', '#00d0f0', tag('LIVE', '#00e888'))}
        <div class="card-body">
          <div class="g4">
            ${metric('pushed',  ss.pushed_events  ?? '-', '', '#00d0f0')}
            ${metric('flushed', ss.flushed_events ?? '-', '', '#00e888')}
            ${metric('dropped', ss.dropped_events ?? '-', '', '#ff4050')}
            ${metric('flush%',  flushRatio,               '%', '#a060ff')}
          </div>
          <div style="margin-top:10px;font-size:1rem;color:#5a7a96;line-height:1.7">
            <b style="color:#c0d8f0">pushed</b>：生产者已入环的事件总数<br>
            <b style="color:#c0d8f0">flushed</b>：已批刷到 WAL 的事件数<br>
            <b style="color:#c0d8f0">dropped</b>：环满背压丢弃（演示场景应恒 0）<br>
            <b style="color:#c0d8f0">丢弃率</b>：${dropRate}%
          </div>
        </div>
      </div>
      <div class="card">${chead('WAL 文件', '💾', '#a060ff')}
        <div class="card-body">
          <div class="g2">
            ${metric('文件大小', wal.size ? (wal.size / 1024).toFixed(1) : '0', 'KB', '#a060ff')}
            ${metric('预览条数', (wal.events || []).length,                 '',   '#ffb020')}
          </div>
          <div style="margin-top:8px;font-size:1rem;color:#5a7a96;word-break:break-all">
            路径: <span class="mono" style="color:#c0d8f0">${wal.path || '-'}</span>
          </div>
        </div>
      </div>
      <div class="card span2">${chead('WAL 事件预览', '🔍', '#ffb020')}
        <div class="card-body">
          <table class="dtable">
            <thead><tr>
              <th style="width:30px">#</th><th>时间戳</th><th>类型</th>
              <th>entity_id</th><th>peer_id</th><th>blob</th><th>blob 预览</th>
            </tr></thead>
            <tbody>${evRows}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

function _simReadInputs() {
  const g = id => (document.getElementById(id) || {}).value;
  simInput.entities        = parseInt(g('sim-ent'), 10) || simInput.entities;
  simInput.events          = parseInt(g('sim-evt'), 10) || simInput.events;
  simInput.threads         = parseInt(g('sim-th'),  10) || simInput.threads;
  simInput.stress          = parseInt(g('sim-str'), 10) || simInput.stress;
  simInput.capture_every_n = parseInt(g('sim-cap'), 10) || simInput.capture_every_n;
}

async function simRun() {
  _simReadInputs();
  simBusy = true; renderM10();
  try {
    const res = await fetch(`${SIM_API}/run`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(simInput)
    });
    simLastRun = await res.json();
  } catch (e) {
    simLastRun = { ok: false, err: e.message };
  }
  simBusy = false; renderM10();
  // 延迟 250ms 让后台 flush 线程把最后一批落盘
  setTimeout(() => { simRefreshStats(); simRefreshWal(); }, 300);
}

async function simReset() {
  simBusy = true; renderM10();
  try {
    await fetch(`${SIM_API}/capture/reset`, { method: 'POST' });
  } catch (e) { console.error('[M10] reset:', e); }
  simLastRun = null; simStats = null; simWal = null;
  simBusy = false; renderM10();
}

async function simRefreshStats() {
  try {
    const res = await fetch(`${SIM_API}/capture/stats`);
    simStats = await res.json();
  } catch (e) { simStats = { ok: false, err: e.message }; }
  renderM10();
}

async function simRefreshWal() {
  try {
    const res = await fetch(`${SIM_API}/capture/wal_head?limit=20`);
    simWal = await res.json();
  } catch (e) { simWal = { ok: false, err: e.message }; }
  renderM10();
}

// 切页到 m10 自动刷一次
(function _hookSimPolling() {
  const prev = window.goPage;
  window.goPage = function (name, el) {
    prev(name, el);
    if (name === 'm10') { simRefreshStats(); simRefreshWal(); }
  };
})();
