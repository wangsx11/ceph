// ============================================================
// m6_tiering.js — §6 分级存储能力演示（步进模式版本）
//
// 设计：
//   · 后端是 8 步的步进模式剧本；每点一次"下一步"按钮走一步
//   · 按钮右侧灰字提示下一步会做什么（由后端返回的 next_label）
//   · [开始演示] → 点完变成 [▶ 下一步]，演示结束后变成 [✓ 已完成]
//   · [↻ 重置] 任何时候都可点，回到未开始状态
//   · polling /api/demo6/status 刷新三层柱状图和事件流
//   · 后端有 hot_keys 保活线程，评审停顿几十秒也不会让 hot 被下沉
// ============================================================

const D6_API = (window.API_BASE || location.origin) + '/api/demo6';

// 8 步的可读标签（与后端 STEP_FLOW 保持顺序一致）
const D6_STEP_LABELS = [
  '清空旧数据 & 复位统计',
  '批量写入 100 个对象（全进 DRAM）',
  '高频访问 32 个 hot_keys（20 轮）',
  '对 40 个 warm_keys 做 2 次轻访问',
  '阶段 A：migrator 下沉 warm+cold → NVMe',
  '阶段 B：显式 demote 28 个 cold → HDD',
  '检查冷层是否达阈值 → 触发快照归档',
  '访问冷数据 → 观察 HDD→DRAM 自动回迁',
];
const D6_TOTAL_STEPS = 8;

const D6 = {
  running:    false,
  done:       false,
  busy:       false,
  step:       0,            // 已完成步数
  nextLabel:  '点击 [开始演示] 触发第 1 步',
  tiers:      { dram:0, nvme:0, hdd:0 },
  totals:     { total:0, hot:0, warm:0, cold:0 },
  events:     [],
  heat:       {},
  snapshots:  {},           // name -> detail
  snapList:   [],
  poll:       null,
  expanded:   {},
};

function renderM6() {
  const el = document.getElementById('pg-m6');
  if (!el) return;
  const statusCls = D6.busy ? 'running'
                  : D6.running ? 'running'
                  : (D6.done ? 'done' : 'idle');
  const statusTxt = D6.busy    ? `正在执行第 ${D6.step + 1} 步 ...`
                  : D6.done    ? '演示完成（可点 ↻ 重置 重新开始）'
                  : D6.running ? `已完成 ${D6.step}/${D6_TOTAL_STEPS} 步`
                  : '就绪（点击 [开始演示] 触发第 1 步）';

  // 步骤条：i <= step 已完成、== step+1 且 busy 正在进行
  let stepsH = '<div class="steps">';
  for (let i = 1; i <= D6_TOTAL_STEPS; i++) {
    const cls = (i <= D6.step) ? 'done'
              : (i === D6.step + 1 && D6.busy) ? 'active'
              : '';
    stepsH += `<div class="step ${cls}" title="${esc(D6_STEP_LABELS[i-1])}"></div>`;
  }
  stepsH += '</div>';

  // 当前/下一步提示文字
  const hintTxt = D6.done
    ? `✓ 已完成全部 ${D6_TOTAL_STEPS} 步`
    : (D6.busy
        ? `⏳ 正在执行：${esc(D6_STEP_LABELS[D6.step])}`
        : (D6.step === 0
            ? `▸ 第 1 步：${esc(D6_STEP_LABELS[0])}`
            : `▸ 下一步（第 ${D6.step + 1}/${D6_TOTAL_STEPS} 步）：${esc(D6_STEP_LABELS[D6.step])}`));
  const curStep = `<div style="font-size:1.05rem;color:${D6.done?'#00e888':'#ffb020'};margin-top:4px">${hintTxt}</div>`;

  // 目标规模总览
  const tt = D6.totals || { total:0, hot:0, warm:0, cold:0 };
  const targetH = `<div class="g4" style="margin-top:10px">
    ${metric('演示总对象数', tt.total||0, '',   '#c0d8f0')}
    ${metric('热对象（高频访问）', tt.hot||0, '', '#ff4050')}
    ${metric('温对象（轻访问）',  tt.warm||0, '', '#ffb020')}
    ${metric('冷对象（归档候选）', tt.cold||0, '', '#4488ff')}
  </div>`;

  // 三层柱状图
  const total = Math.max(1, D6.tiers.dram + D6.tiers.nvme + D6.tiers.hdd);
  const tiersH = `<div class="g3">
    ${d6Tier('🔥 热层 (DRAM)',  D6.tiers.dram, total, '#ff4050', '高频访问·0访问延迟')}
    ${d6Tier('🌡 温层 (NVMe)',  D6.tiers.nvme, total, '#ffb020', '中频数据·次级存储')}
    ${d6Tier('❄ 冷层 (HDD)',  D6.tiers.hdd,  total, '#4488ff', '长期无访问·归档')}
  </div>`;

  // 事件流：过滤掉 snapshot 类条目
  const migEvents = D6.events.filter(e => !e.snap_name);
  const migH = migEvents.length === 0
    ? '<div style="color:#5a7a96;padding:16px;text-align:center">等待演示开始...</div>'
    : migEvents.slice(0, 40).map((e, i) => `
        <div class="eitem ${i===0?'latest':''}">
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
  const archDir = '${NR_SNAPSHOT_DIR:-/tmp/nr_snapshots}';
  const snapHint = D6.snapList.length === 0
    ? `<div style="color:#5a7a96;padding:14px;text-align:center;font-size:1rem">
         尚无快照 — 冷层对象数达阈值 <b style="color:#ffb020">${threshold}</b> 时触发归档；
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

  // 按钮区：根据 D6 state 决定主按钮文案和是否可点
  let mainBtnHTML;
  if (!D6.running && !D6.done) {
    mainBtnHTML = `<button class="btn btn-primary" onclick="d6Start()">▶ 开始演示</button>`;
  } else if (D6.done) {
    mainBtnHTML = `<button class="btn btn-primary" disabled>✓ 演示完成</button>`;
  } else {
    mainBtnHTML = `<button class="btn btn-primary" onclick="d6NextStep()" ${D6.busy?'disabled':''}>
                     ${D6.busy ? `⏳ 正在执行第 ${D6.step + 1} 步 ...` : `▶ 下一步（${D6.step + 1}/${D6_TOTAL_STEPS}）`}
                   </button>`;
  }

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">⑥ 分级存储能力演示（8 步步进模式）</div>
        <div class="ctrl-status ${statusCls}">
          <div class="dot ${D6.busy?'dot-pulse':''}" style="background:${D6.busy?'#00e888':D6.done?'#00d0f0':'#5a7a96'};width:6px;height:6px"></div>
          ${statusTxt}
        </div>
      </div>
      ${stepsH}${curStep}
      ${targetH}
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0 10px">
        <b style="color:#c0d8f0">步进模式</b>：每次点击 [▶ 下一步] 执行 8 步剧本中的下一步，评审时可以边讲解边点。
        后端维护 hot_keys 保活线程（500ms 周期 GET），即使步骤之间长时间停顿也不会让 hot_keys 被误下沉。<br>
        层级计数来自 <span class="mono" style="color:#c0d8f0">RPC_TIER_STATS</span>；快照归档目录：<span class="mono" style="color:#c0d8f0">${archDir}</span>
      </div>
      <div class="ctrl-row" style="align-items:center;gap:12px">
        ${mainBtnHTML}
        <span style="color:#8aa8c6;font-size:0.95rem;flex:1">
          ${esc(D6.nextLabel || '')}
        </span>
        <button class="btn btn-outline btn-sm" onclick="d6Reset()" ${D6.busy?'disabled':''}>↻ 重置</button>
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
  try {
    const r = await fetch(`${D6_API}/start`, { method:'POST' });
    const j = await r.json();
    if (!j.ok) { alert('start failed: ' + (j.error||'?')); return; }
    D6.running = true; D6.done = false; D6.step = 0; D6.busy = false;
    D6.events = []; D6.snapshots = {}; D6.snapList = [];
    D6.nextLabel = j.next_label || D6_STEP_LABELS[0];
    renderM6();
    d6StartPoll();
  } catch (e) {
    alert('start error: ' + e);
  }
}

async function d6NextStep() {
  if (D6.busy) return;
  D6.busy = true;
  renderM6();
  try {
    // next_step 是阻塞式调用，后端执行完整的该步后才返回，
    // 可能需要几秒（如 step5 阶段 A 等 3s、step2 写入 ~1s）。
    const r = await fetch(`${D6_API}/next_step`, { method:'POST' });
    const j = await r.json();
    if (!j.ok) {
      alert('step failed: ' + (j.error||'?'));
      D6.busy = false;
      renderM6();
      return;
    }
    if (j.done) {
      D6.done = true;
      D6.running = false;
    }
    D6.nextLabel = j.next_label || '';
    D6.busy = false;
    // 立刻拉一次 status 同步所有层级/事件
    await d6PollOnce();
    renderM6();
  } catch (e) {
    D6.busy = false;
    alert('next_step error: ' + e);
    renderM6();
  }
}

async function d6Reset() {
  if (D6.poll) { clearInterval(D6.poll); D6.poll = null; }
  try {
    await fetch(`${D6_API}/reset`, { method:'POST' });
  } catch (_) {}
  Object.assign(D6, {
    running:false, done:false, busy:false, step:0,
    nextLabel: `点击 [开始演示] 触发第 1 步：${D6_STEP_LABELS[0]}`,
    tiers:{dram:0,nvme:0,hdd:0}, events:[], heat:{},
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
  // 演示期间持续 1s polling；步骤之间的保活期间也需要更新 hot_keys 最新热度。
  D6.poll = setInterval(d6PollOnce, 1000);
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
      // 初次进入拉取一次 status，让页面显示服务端当前状态（可能已经跑过几步）
      d6PollOnce();
      // 若后端 running 但前端没跑 poll，启动 poll
      if (D6.running && !D6.poll) d6StartPoll();
    }
  };
})();
