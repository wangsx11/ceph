// ============================================================
// m6_tiering.js — §6 分级存储能力演示（重写版）
//
// 设计：
//   · 后端已改为"真实访问驱动"的 6 步剧本；前端只管订阅事件 + 渲染
//   · SSE /api/demo6/stream + 兜底 polling
//   · 3 层柱状图 (DRAM / NVMe / HDD) + 迁移事件时间线 + 快照详情展开
//   · 所有事件来自后端实际采集的 tier_stats / demote 日志，非模拟
// ============================================================

const D6_API = (window.API_BASE || location.origin) + '/api/demo6';

const D6_STEP_LABELS = [
  '清空旧数据 & 复位',
  '写入 24 个对象（全进 DRAM）',
  '高频访问 4 个热对象',
  '等待 migrator 识别冷数据并下沉',
  '冷层达阈值，触发快照',
  '再访问冷数据，自动回迁',
];

const D6 = {
  running:  false,
  done:     false,
  step:     0,
  tiers:    { dram:0, nvme:0, hdd:0 },
  events:   [],
  heat:     {},
  snapshots: {},     // name -> detail  (lazy loaded on click)
  sse:      null,
  poll:     null,
  expanded: {},      // snapshot name -> bool
};

function renderM6() {
  const el = document.getElementById('pg-m6');
  if (!el) return;
  const statusCls = D6.running ? 'running' : (D6.done ? 'done' : 'idle');
  const statusTxt = D6.running ? `执行中：步骤 ${D6.step}/6`
                  : D6.done    ? '演示完成'
                  : '就绪';

  // 步骤条
  let stepsH = '<div class="steps">';
  for (let i=1; i<=6; i++) {
    const cls = i < D6.step ? 'done' : (i === D6.step && D6.running ? 'active' : '');
    stepsH += `<div class="step ${cls}"></div>`;
  }
  stepsH += '</div>';
  const curStep = D6.step > 0 && D6.step <= 6
    ? `<div style="font-size:1.05rem;color:#00e888;margin-top:4px">▸ ${D6_STEP_LABELS[D6.step-1]}</div>`
    : '';

  // 三层柱状图
  const total = Math.max(1, D6.tiers.dram + D6.tiers.nvme + D6.tiers.hdd);
  const tiersH = `<div class="g3">
    ${d6Tier('🔥 热层 (DRAM)',  D6.tiers.dram, total, '#ff4050', '高频访问·0访问延迟')}
    ${d6Tier('🌡 温层 (NVMe)',  D6.tiers.nvme, total, '#ffb020', '中频数据·次级存储')}
    ${d6Tier('❄ 冷层 (HDD)',  D6.tiers.hdd,  total, '#4488ff', '长期无访问·归档')}
  </div>`;

  // 热度条（对前若干个对象显示累计 GET 次数）
  const heatKeys = Object.keys(D6.heat).sort();
  const heatH = heatKeys.length === 0
    ? '<div style="color:#5a7a96;padding:14px;text-align:center">尚未开始演示</div>'
    : '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px">' +
      heatKeys.map(k => {
        const h = D6.heat[k];
        const cnt = h.count || 0;
        const hot = cnt >= 4 ? '#ff4050' : cnt >= 1 ? '#ffb020' : '#5a7a96';
        return `<div style="padding:6px;background:#1b2a3d;border-radius:4px;border:1px solid ${hot}30">
          <div class="mono" style="font-size:0.95rem;color:#e4edf6">${esc(k)}</div>
          <div class="mono" style="font-size:1.1rem;color:${hot};font-weight:700">${cnt} GET</div>
          <div style="font-size:0.9rem;color:#5a7a96">hit=${h.last_hit||'-'}</div>
        </div>`;
      }).join('') + '</div>';

  // 事件时间线（区分 snapshot / migrate / step / hint）
  const evH = D6.events.length === 0
    ? '<div style="color:#5a7a96;padding:16px;text-align:center">等待演示开始...</div>'
    : D6.events.map((e, i) => {
        const main = `<div class="eitem ${i===0?'latest':''}" style="cursor:${e.snap_name?'pointer':'default'}"
                 ${e.snap_name ? `onclick="d6ToggleSnap('${esc(e.snap_name)}')"` : ''}>
          <span style="color:#5a7a96">${e.ts}</span>
          <span style="color:${e.color};font-weight:700;min-width:82px;display:inline-block">${e.kind}</span>
          <span style="color:#e4edf6">${esc(e.text)}</span>
          ${e.snap_name ? '<span style="color:#a060ff;margin-left:8px">▶ 点击查看对象清单</span>':''}
        </div>`;
        let detail = '';
        if (e.snap_name && D6.expanded[e.snap_name] && D6.snapshots[e.snap_name]) {
          detail = d6RenderSnapDetail(D6.snapshots[e.snap_name]);
        }
        return main + detail;
      }).join('');

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">⑥ 分级存储能力演示（访问驱动）</div>
        <div class="ctrl-status ${statusCls}">
          <div class="dot ${D6.running?'dot-pulse':''}" style="background:${D6.running?'#00e888':D6.done?'#00d0f0':'#5a7a96'};width:6px;height:6px"></div>
          ${statusTxt}
        </div>
      </div>
      ${stepsH}${curStep}
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0 10px">
        <b style="color:#c0d8f0">真实访问驱动</b>：写入 24 个 4KB 对象 → 高频访问其中 4 个 → migrator 后台识别长时间未访问的对象下沉 NVMe/HDD → 冷层达阈值自动快照 → 再访问冷对象自动回迁。<br>
        不依赖任何脚本化模拟迁移，层级计数来自 <span class="mono" style="color:#c0d8f0">RPC_TIER_STATS</span>。
      </div>
      <div class="ctrl-row">
        <button class="btn btn-primary" onclick="d6Start()" ${D6.running?'disabled':''}>▶ 开始演示</button>
        <button class="btn btn-outline btn-sm" onclick="d6Reset()">↻ 重置</button>
      </div>
    </div>

    <div class="g2" style="margin-top:12px">
      <div class="card span2">${chead('三层存储分布（来自 RPC_TIER_STATS）', '🏗')}
        <div class="card-body">${tiersH}</div>
      </div>
      <div class="card">${chead('对象热度（GET 累计次数）', '🌡', '#ff6090')}
        <div class="card-body">${heatH}</div>
      </div>
      <div class="card">${chead('迁移 / 快照 / 访问事件流', '📜', '#00d0f0', tag('LIVE', '#00e888'))}
        <div class="card-body"><div class="elog" style="max-height:420px">${evH}</div></div>
      </div>
    </div>`;
}

function d6Tier(title, n, total, color, desc) {
  const pct = (n / total * 100);
  return `<div class="tier-block" style="border:1px solid ${color}30;height:180px">
    <div class="tier-bg" style="height:${pct}%;background:${color}15"></div>
    <div class="tier-content">
      <div style="font-size:1.4rem;color:${color};font-weight:700">${title}</div>
      <div class="tier-count" style="font-size:3rem">${n}</div>
      <div style="font-size:0.95rem;color:#5a7a96">${desc}</div>
      <div style="margin-top:6px">${prog(n, total, color)}</div>
    </div>
  </div>`;
}

function d6RenderSnapDetail(s) {
  const rows = (s.objects || []).slice(0, 30).map((o, i) =>
    `<tr><td style="color:#5a7a96">${i+1}</td>
     <td class="mono" style="color:#e4edf6">${esc(o.name)}</td>
     <td class="mono" style="color:#ffb020">${o.size} B</td>
     <td class="mono" style="color:#5a7a96">${o.hash}</td></tr>`
  ).join('');
  return `<div style="margin:4px 0 10px 16px;padding:10px;background:#0d1b2a;border:1px solid #2d4a66;border-radius:4px">
    <div style="color:#a060ff;font-weight:700;margin-bottom:6px">
      快照 ${esc(s.name)} · ${s.count} 对象 · 耗时 ${F((s.dur_s||0)*1000, 1)} ms · ${esc(s.timestamp)}
    </div>
    <table class="dtable"><thead><tr>
      <th style="width:34px">#</th><th>对象名</th><th>大小</th><th>哈希</th>
    </tr></thead><tbody>${rows}</tbody></table>
  </div>`;
}

// ------------------------------------------------------------
// 动作
// ------------------------------------------------------------
async function d6Start() {
  const r = await fetch(`${D6_API}/start`, { method:'POST' });
  const j = await r.json();
  if (!j.ok) { alert('start failed: ' + (j.error||'?')); return; }
  D6.running = true; D6.done = false;
  D6.events = []; D6.snapshots = {};
  renderM6();
  d6ConnectSSE();
}

async function d6Reset() {
  if (D6.sse) { D6.sse.close(); D6.sse = null; }
  await fetch(`${D6_API}/reset`, { method:'POST' });
  Object.assign(D6, { running:false, done:false, step:0,
    tiers:{dram:0,nvme:0,hdd:0}, events:[], heat:{},
    snapshots:{}, expanded:{} });
  renderM6();
}

function d6ConnectSSE() {
  if (D6.sse) D6.sse.close();
  D6.sse = new EventSource(`${D6_API}/stream`);
  D6.sse.onmessage = (ev) => {
    try {
      const j = JSON.parse(ev.data);
      d6ApplyStatus(j);
      if (j.done) { D6.sse.close(); D6.sse = null; }
    } catch (_) {}
  };
  D6.sse.onerror = () => {
    if (D6.sse) { D6.sse.close(); D6.sse = null; }
    // 转 polling 兜底
    d6StartPoll();
  };
}

function d6StartPoll() {
  if (D6.poll) return;
  D6.poll = setInterval(async () => {
    try {
      const r = await fetch(`${D6_API}/status`);
      const j = await r.json();
      d6ApplyStatus(j);
      if (!j.running && j.step > 0) {
        clearInterval(D6.poll); D6.poll = null;
      }
    } catch (_) {}
  }, 1200);
}

function d6ApplyStatus(j) {
  if (j.running != null) D6.running = j.running;
  if (j.step    != null) D6.step    = j.step;
  if (j.tiers)           D6.tiers   = j.tiers;
  if (j.events)          D6.events  = j.events;
  if (j.heat)            D6.heat    = j.heat;
  if (j.done) D6.done = true;
  renderM6();
}

async function d6ToggleSnap(name) {
  D6.expanded[name] = !D6.expanded[name];
  if (D6.expanded[name] && !D6.snapshots[name]) {
    try {
      const r = await fetch(`${D6_API}/snapshot/${encodeURIComponent(name)}`);
      const j = await r.json();
      if (j.ok) D6.snapshots[name] = j;
    } catch (_) {}
  }
  renderM6();
}

// 页面切换钩子
(function _initM6() {
  const prev = window.goPage;
  window.goPage = function (name, el) {
    prev(name, el);
    if (name === 'm6') {
      // 初次进入拉取一次 status
      fetch(`${D6_API}/status`).then(r=>r.json()).then(j => {
        d6ApplyStatus(j);
      }).catch(()=>{});
    }
  };
})();