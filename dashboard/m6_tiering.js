// ============================================================
// m6_tiering.js — §6 分级存储能力演示
//
// 设计：
//   · 后端是 8 步剧本，点击 [开始演示] 后后台线程一键走完
//   · 初始 100 对象落 NVMe 温层；真实 GET 负责热层回迁和分层变化
//   · [↻ 重置] 清理 DP 状态回到未开始
// ============================================================

const D6_API = (window.API_BASE || location.origin) + '/api/demo6';

// 8 步的可读标签（与后端 STEP_FLOW 保持顺序一致）
const D6_STEP_LABELS = [
  '清空旧数据 & 复位统计',
  '写入 100 个对象并落到温层 NVMe',
  '真实访问：hot 高频 / warm 轻访问 / cold 静默',
  '阶段 A：warm 热度衰减后回落 NVMe',
  '阶段 B：cold 下沉 HDD',
  '冷层达阈值 → 触发快照 + JSON 归档',
  '访问 5 个 HDD 对象 → 自动回迁 DRAM',
  '汇总三层分布 & 演示结束',
];
const D6_TOTAL_STEPS = 8;

const D6 = {
  running:    false,
  done:       false,
  busy:       false,
  step:       0,            // 已完成步数
  nextLabel:  '点击 [开始演示] 一键走完整剧本',
  tiers:      { dram:0, nvme:0, hdd:0 },
  totals:     { total:0, hot:0, warm:0, cold:0 },
  events:     [],
  heat:       {},
  snapshots:  {},           // name -> detail
  snapList:   [],
  poll:       null,
  expanded:   {},
};

function d6DisplayStep() {
  const raw = Number(D6.step || 0);
  if (D6.busy) return Math.min(D6_TOTAL_STEPS, Math.max(1, raw));
  return Math.min(D6_TOTAL_STEPS, Math.max(0, raw));
}

function renderM6() {
  const el = document.getElementById('pg-m6');
  if (!el) return;
  const shownStep = d6DisplayStep();
  const statusCls = D6.busy ? 'running'
                  : D6.running ? 'running'
                  : (D6.done ? 'done' : 'idle');
  const statusTxt = D6.busy    ? `正在执行第 ${shownStep} 步 ...`
                  : D6.done    ? '演示完成（可点 ↻ 重置 重新开始）'
                  : D6.running ? `已完成 ${D6.step}/${D6_TOTAL_STEPS} 步`
                  : '就绪（点击 [开始演示] 触发第 1 步）';

  // 步骤条：后端 busy 时 step 表示当前步；非 busy 时 step 表示已完成步数。
  let stepsH = '<div class="steps">';
  for (let i = 1; i <= D6_TOTAL_STEPS; i++) {
    const cls = D6.busy
      ? (i < shownStep ? 'done' : (i === shownStep ? 'active' : ''))
      : (i <= D6.step ? 'done' : '');
    stepsH += `<div class="step ${cls}" title="${esc(D6_STEP_LABELS[i-1])}"></div>`;
  }
  stepsH += '</div>';

  // 当前/下一步提示文字
  const labelIdx = D6.busy
    ? shownStep - 1
    : (D6.step === 0 ? 0 : Math.min(D6.step, D6_TOTAL_STEPS - 1));
  const hintTxt = D6.done
    ? `✓ 已完成全部 ${D6_TOTAL_STEPS} 步`
    : (D6.busy
        ? `⏳ 正在执行：${esc(D6_STEP_LABELS[labelIdx])}`
        : (D6.step === 0
            ? `▸ 第 1 步：${esc(D6_STEP_LABELS[0])}`
            : `▸ 下一步（第 ${Math.min(D6.step + 1, D6_TOTAL_STEPS)}/${D6_TOTAL_STEPS} 步）：${esc(D6_STEP_LABELS[labelIdx])}`));
  const curStep = `<div style="font-size:1.05rem;color:${D6.done?'#00e888':'#ffb020'};margin-top:4px">${hintTxt}</div>`;

  // 目标规模总览
  const tt = D6.totals || { total:0, hot:0, warm:0, cold:0 };
  const targetH = `<div class="g4" style="margin-top:10px">
    ${metric('演示总对象数', tt.total||0, '',  '#c0d8f0')}
    ${metric('热集 hot (高频访问)', tt.hot||0, '', '#ff4050')}
    ${metric('温集 warm (轻访问)',  tt.warm||0, '', '#ffb020')}
    ${metric('冷集 cold (从不访问)', tt.cold||0, '', '#4488ff')}
  </div>`;

  // 三层柱状图
  const total = Math.max(1, D6.tiers.dram + D6.tiers.nvme + D6.tiers.hdd);
  const tiersH = `<div class="g3">
    ${d6Tier('🔥 热层 (DRAM)',  D6.tiers.dram, total, '#ff4050', '高频访问·内存层')}
    ${d6Tier('🌡 温层 (NVMe)',  D6.tiers.nvme, total, '#ffb020', '轻访问数据·SSD温层')}
    ${d6Tier('❄ 冷层 (HDD)',  D6.tiers.hdd,  total, '#4488ff', '长期无访问·容量层')}
  </div>`;

  // 事件流：过滤掉 snapshot 类条目
  // （移除了前版的 `latest` 呼吸动画类：polling 每秒重渲染时
  //   每次都给首行打上 latest 会导致“一直闪个不停”的观感）
  const migEvents = D6.events.filter(e => !e.snap_name);
  const migH = migEvents.length === 0
    ? '<div style="color:#5a7a96;padding:16px;text-align:center">等待演示开始...</div>'
    : migEvents.slice(0, 40).map((e) => `
        <div class="eitem">
          <span style="color:#5a7a96">${e.ts}</span>
          <span style="color:${e.color};font-weight:700;min-width:82px;display:inline-block">${e.kind}</span>
          <span style="color:#e4edf6">${esc(e.text)}</span>
        </div>`).join('');

  // 快照生成区
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
  const threshold = 20;  // 与后端 SNAP_THRESHOLD 保持一致
  const snapHint = D6.snapList.length === 0
    ? `<div style="color:#5a7a96;padding:14px;text-align:center;font-size:1rem">
         尚无快照 — 冷层对象数达阈值 <b style="color:#ffb020">${threshold}</b> 时触发归档；
         当前冷层 <b style="color:${coldNow>=threshold?'#00e888':'#ff4050'}">${coldNow}</b>
         / ${threshold}
       </div>`
    : '';
  const snapRows = D6.snapList.map((s) => {
    const detail = D6.expanded[s.name] && D6.snapshots[s.name]
      ? d6RenderSnapDetail(D6.snapshots[s.name]) : '';
    return `<div>
      <div class="eitem" style="cursor:pointer"
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

  // 按钮区：一键执行模式 — 只有一个“开始演示”按钮；执行中禁用，
  // 完成后文案变为“演示完成”。不再需要用户点“下一步”。
  let mainBtnHTML;
  if (!D6.running && !D6.done) {
    mainBtnHTML = `<button class="btn btn-primary" onclick="d6Start()">▶ 开始演示</button>`;
  } else if (D6.done) {
    mainBtnHTML = `<button class="btn btn-primary" disabled>✓ 演示完成</button>`;
  } else {
    // running 中
    mainBtnHTML = `<button class="btn btn-primary" disabled>
                     ⏳ ${D6.busy ? `第 ${shownStep} 步` : `已完成 ${D6.step}/${D6_TOTAL_STEPS}`}
                   </button>`;
  }

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">⑥ 分级存储能力演示</div>
        <div class="ctrl-status ${statusCls}">
          <div class="dot ${D6.busy?'dot-pulse':''}" style="background:${D6.busy?'#00e888':D6.done?'#00d0f0':'#5a7a96'};width:6px;height:6px"></div>
          ${statusTxt}
        </div>
      </div>
      ${stepsH}${curStep}
      ${targetH}
      <div class="ctrl-row" style="align-items:center;gap:12px">
        ${mainBtnHTML}
        <span style="color:#8aa8c6;font-size:0.95rem;flex:1">
          ${esc(D6.nextLabel || '')}
        </span>
        <button class="btn btn-outline btn-sm" onclick="d6Reset()" ${D6.busy?'disabled':''}>↻ 重置</button>
      </div>
    </div>

    <div class="card" style="margin-top:12px">
      ${chead('三层存储分布', '🏗')}
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
  try {
    const r = await fetch(`${D6_API}/start`, { method:'POST' });
    const j = await r.json();
    if (!j.ok) { alert('start failed: ' + (j.error||'?')); return; }
    D6.running = true; D6.done = false; D6.step = 0; D6.busy = false;
    D6.events = []; D6.snapshots = {}; D6.snapList = [];
    D6.nextLabel = j.next_label || D6_STEP_LABELS[0];
    renderM6();
    d6StartPoll();
    d6PollOnce();
  } catch (e) {
    alert('start error: ' + e);
  }
}

// 保留该函数作为旧前端兼容兼容入口；一键执行模式下本页不再调用。
async function d6NextStep() {
  try { await fetch(`${D6_API}/next_step`, { method:'POST' }); } catch (_) {}
}

async function d6Reset() {
  if (D6.poll) { clearInterval(D6.poll); D6.poll = null; }
  try {
    await fetch(`${D6_API}/reset`, { method:'POST' });
  } catch (_) {}
  Object.assign(D6, {
    running:false, done:false, busy:false, step:0,
    nextLabel: '点击 [开始演示] 一键走完整剧本',
    tiers:{dram:0,nvme:0,hdd:0}, events:[], heat:{},
    totals:{total:0,hot:0,warm:0,cold:0},
    snapshots:{}, expanded:{}, snapList: [],
  });
  renderM6();
}

async function d6PollOnce() {
  try {
    const r = await fetch(`${D6_API}/status`);
    const j = await r.json();
    d6ApplyStatus(j);
  } catch (_) {}
}

function d6StartPoll() {
  if (D6.poll) return;
  // 贴近数据平面采样周期，避免整批迁移被 1s 采样压成突变。
  D6.poll = setInterval(d6PollOnce, 350);
}

function d6ApplyStatus(j) {
  if (j.running != null) D6.running = j.running;
  if (j.step    != null) D6.step    = j.step;
  if (j.busy    != null) D6.busy    = j.busy;
  if (j.next_label != null) D6.nextLabel = j.next_label;
  if (j.tiers)           D6.tiers   = j.tiers;
  if (j.totals)          D6.totals  = j.totals;
  if (j.events)          D6.events  = j.events;
  if (j.heat)            D6.heat    = j.heat;
  if (j.done) {
    D6.done = true;
    D6.running = false;
    D6.busy = false;
    if (D6.poll) { clearInterval(D6.poll); D6.poll = null; }
  }
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
      // 初次进入拉取一次 status，让页面显示服务端当前状态（可能已经跑过几步）
      d6PollOnce();
      // 若后端 running 但前端没跑 poll，启动 poll
      if (D6.running && !D6.poll) d6StartPoll();
    }
  };
})();
