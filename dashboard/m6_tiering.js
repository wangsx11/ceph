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
  snapList: [],      // 已观察到的快照条目（按时间倒序）；包含自动/手动触发
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

  // 目标规模总览
  const tt = D6.totals || { total:0, hot:0, warm:0, cold:0 };
  const targetH = `<div class="g4" style="margin-top:10px">
    ${metric('演示总对象数', tt.total||0, '',   '#c0d8f0')}
    ${metric('热对象（高频访问）', tt.hot||0, '', '#ff4050')}
    ${metric('温对象（静默）',  tt.warm||0, '', '#ffb020')}
    ${metric('冷对象（归档候选）', tt.cold||0, '', '#4488ff')}
  </div>`;

  // 三层柱状图
  const total = Math.max(1, D6.tiers.dram + D6.tiers.nvme + D6.tiers.hdd);
  const tiersH = `<div class="g3">
    ${d6Tier('🔥 热层 (DRAM)',  D6.tiers.dram, total, '#ff4050', '高频访问·0访问延迟')}
    ${d6Tier('🌡 温层 (NVMe)',  D6.tiers.nvme, total, '#ffb020', '中频数据·次级存储')}
    ${d6Tier('❄ 冷层 (HDD)',  D6.tiers.hdd,  total, '#4488ff', '长期无访问·归档')}
  </div>`;

  // 事件流：过滤掉 snapshot 类条目，snapshot 条目单独走"快照生成"卡片
  const migEvents = D6.events.filter(e => !e.snap_name);
  const migH = migEvents.length === 0
    ? '<div style="color:#5a7a96;padding:16px;text-align:center">等待演示开始...</div>'
    : migEvents.slice(0, 40).map((e, i) => `
        <div class="eitem ${i===0?'latest':''}">
          <span style="color:#5a7a96">${e.ts}</span>
          <span style="color:${e.color};font-weight:700;min-width:82px;display:inline-block">${e.kind}</span>
          <span style="color:#e4edf6">${esc(e.text)}</span>
        </div>`).join('');

  // 快照生成区：从事件流里拉 snap_name 条目，叠加 D6.snapList（手动触发）
  const snapEventItems = D6.events.filter(e => e.snap_name);
  const seenNames = new Set(D6.snapList.map(s => s.name));
  snapEventItems.forEach(e => {
    if (!seenNames.has(e.snap_name)) {
      D6.snapList.unshift({
        name:  e.snap_name,
        ts:    e.ts,
        text:  e.text,
        color: e.color || '#a060ff',
        src:   'auto',
      });
      seenNames.add(e.snap_name);
    }
  });
  if (D6.snapList.length > 32) D6.snapList.length = 32;

  const coldNow = D6.tiers.hdd;
  const threshold = 50;  // 与后端 SNAP_THRESHOLD 保持一致
  const archDir = '${NR_SNAPSHOT_DIR:-/tmp/nr_snapshots}';
  const snapHint = D6.snapList.length === 0
    ? `<div style="color:#5a7a96;padding:14px;text-align:center;font-size:1rem">
         尚无快照 — 冷层对象数达阈值 <b style="color:#ffb020">${threshold}</b> 时自动触发归档；
         当前冷层 <b style="color:${coldNow>=threshold?'#00e888':'#ff4050'}">${coldNow}</b>
         / ${threshold}
       </div>`
    : '';
  const snapRows = D6.snapList.map((s, i) => {
    const detail = D6.expanded[s.name] && D6.snapshots[s.name]
      ? d6RenderSnapDetail(D6.snapshots[s.name]) : '';
    return `<div>
      <div class="eitem ${i===0?'latest':''}" style="cursor:pointer"
           onclick="d6ToggleSnap('${esc(s.name)}')">
        <span style="color:#5a7a96">${s.ts}</span>
        <span style="color:${s.color};font-weight:700;min-width:100px;display:inline-block">SNAPSHOT</span>
        <span class="mono" style="color:#e4edf6">${esc(s.name)}</span>
        <span style="color:#5a7a96;margin-left:6px">${esc(s.text || '').slice(0, 80)}</span>
        <span style="color:#a060ff;margin-left:8px">▶ 点击查看对象清单</span>
      </div>
      ${detail}
    </div>`;
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
      ${targetH}
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0 10px">
        <b style="color:#c0d8f0">真实访问驱动</b>：写入 <b>1000 个 4KB</b> 对象 → 持续高频访问其中 <b>32 个</b>（热）→ migrator 后台识别剩余静默对象下沉 NVMe / HDD → 冷层 ≥ ${threshold} 个时触发快照并自动归档 JSON → 再访问冷对象自动回迁热层。<br>
        层级计数来自 <span class="mono" style="color:#c0d8f0">RPC_TIER_STATS</span>；快照归档目录：<span class="mono" style="color:#c0d8f0">${archDir}</span>
      </div>
      <div class="ctrl-row">
        <button class="btn btn-primary" onclick="d6Start()" ${D6.running?'disabled':''}>▶ 开始演示</button>
        <button class="btn btn-outline btn-sm" onclick="d6Reset()">↻ 重置</button>
      </div>
    </div>

    <div class="card" style="margin-top:12px">
      ${chead('三层存储分布（来自 RPC_TIER_STATS）', '🏗')}
      <div class="card-body">${tiersH}</div>
    </div>

    <div class="card" style="margin-top:12px">
      ${chead('迁移 / 访问 事件流', '📜', '#00d0f0', tag('LIVE', '#00e888'))}
      <div class="card-body"><div class="elog" style="max-height:300px">${migH}</div></div>
    </div>

    <div class="card" style="margin-top:12px">
      ${chead('快照生成 (snapshot & archive)', '📸', '#a060ff',
              tag(`${D6.snapList.length} 条`, '#a060ff'))}
      <div class="card-body">
        ${snapHint}
        <div class="elog" style="max-height:360px">${snapRows}</div>
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
  const rows = (s.objects || []).slice(0, 50).map((o, i) =>
    `<tr><td style="color:#5a7a96">${i+1}</td>
     <td class="mono" style="color:#e4edf6">${esc(o.name)}</td>
     <td class="mono" style="color:#ffb020">${o.size} B</td>
     <td class="mono" style="color:#5a7a96">${o.hash}</td></tr>`
  ).join('');
  const more = (s.objects || []).length > 50
    ? `<tr><td colspan="4" style="color:#5a7a96;text-align:center">… 共 ${s.objects.length} 个对象，UI 仅展示前 50 条</td></tr>`
    : '';
  const archiveInfo = s.archive_path
    ? `<div style="display:flex;gap:18px;margin-top:4px;font-size:1rem">
        <span style="color:#00e888">📦 归档文件</span>
        <span class="mono" style="color:#e4edf6">${esc(s.archive_path)}</span>
        <span style="color:#ffb020">${F((s.archive_size||0)/1024, 1)} KB</span>
      </div>` : '';
  const dur = s.dur_ms != null ? F(s.dur_ms, 1) : F((s.dur_s||0)*1000, 1);
  return `<div style="margin:4px 0 10px 16px;padding:10px;background:#0d1b2a;border:1px solid #2d4a66;border-radius:4px">
    <div style="color:#a060ff;font-weight:700;margin-bottom:6px">
      快照 ${esc(s.name)} · ${s.count} 对象 · 耗时 ${dur} ms · ${esc(s.timestamp||'')}
    </div>
    ${archiveInfo}
    <table class="dtable" style="margin-top:6px"><thead><tr>
      <th style="width:34px">#</th><th>对象名</th><th>大小</th><th>哈希</th>
    </tr></thead><tbody>${rows}${more}</tbody></table>
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
    snapshots:{}, expanded:{}, snapList: [] });
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