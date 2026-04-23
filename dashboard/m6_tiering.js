// ============================================================
// m6_tiering.js — 模块六：分级存储能力演示
// 调用真实后端API (Flask + 分布式存储 三层分级存储)
// 使用SSE实时推送迁移事件
// ============================================================

const TIER_API = (window.API_BASE || 'http://localhost:5000') + '/api/m6';

let tierRunning = false, tierStep = 0;
let tierMigEvts = [], tierSnapEvts = [];
let tierState = { hot: 0, warm: 0, cold: 0 };

// ── 冻结机制 ──────────────────────────────────────────────
// tierDisplayFrozen = true  → 三个池显示 tierFrozenSnapshot 的值，忽略后端数据
// tierDisplayFrozen = false → 正常跟随后端数据
let tierDisplayFrozen = true;
let tierFrozenSnapshot = { hot: 0, warm: 0, cold: 0 }; // 点击"开始"时保存的快照
// ──────────────────────────────────────────────────────────

let deployShow = false;
let tierEventSource = null;
let tierPollTimer = null;

const TIER_STEPS = ['写入温层', '模拟访问', '冷热识别迁移', '冷数据快照', '回访回迁', '再次分层'];

function renderM6() {
  const el = document.getElementById('pg-m6');
  const statusCls = tierRunning ? 'running' : tierStep > 0 ? 'done' : 'idle';
  const statusTxt = tierRunning
    ? `执行中: ${tierStep === 0 ? '清理旧数据...' : (TIER_STEPS[tierStep - 1] || '完成')}`
    : tierStep > 0 ? '演示完成' : '就绪';

  // Steps bar
  let stepsH = '<div class="steps">' + TIER_STEPS.map((_, i) =>
    `<div class="step ${i < tierStep ? 'done' : i === tierStep - 1 && tierRunning ? 'active' : ''}"></div>`
  ).join('') + '</div>';

  // 决定展示哪份数据：冻结期间用快照，否则用实时数据
  const displayState = tierDisplayFrozen ? tierFrozenSnapshot : tierState;

  // Tier visualization
  const total = displayState.hot + displayState.warm + displayState.cold || 1;
  const tiers = [
    { name: '热层(DRAM)', icon: '🔥', color: '#ff4050', count: displayState.hot,  desc: '高频访问数据·ramfs' },
    { name: '温层(SSD)',  icon: '🌡',  color: '#ffb020', count: displayState.warm, desc: '中频访问数据·warm_pool' },
    { name: '冷层(HDD)', icon: '❄',   color: '#4488ff', count: displayState.cold, desc: '低频归档数据·cold_pool' },
  ];
  let vizH = '<div class="g3">' + tiers.map(t => {
    const pct = t.count / total * 100;
    return `<div class="tier-block" style="border:1px solid ${t.color}30">
      <div class="tier-bg" style="height:${pct}%;background:${t.color}12"></div>
      <div class="tier-content">
        <div class="tier-icon">${t.icon}</div>
        <div style="font-size:1.3rem;font-weight:700;color:${t.color};margin-top:3px">${t.name}</div>
        <div class="tier-count">${t.count}</div>
        <div style="font-size:1rem;color:#5a7a96">${t.desc}</div>
        <div style="margin-top:6px">${prog(t.count, total, t.color)}</div>
      </div>
    </div>`;
  }).join('') + '</div>';

  // Migration events (缓存模式：显示缓存层级变化)
  let mH = '';
  if (!tierMigEvts.length) {
    mH = '<div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:20px">等待演示开始...</div>';
  } else {
    tierMigEvts.forEach((e, i) => {
      const isCache = e.reason && e.reason.includes('缓存');
      const dirColor = e.dir.includes('PROMOTE') ? '#00e888' : '#00d0f0';
      const actionLabel = isCache ? (e.dir.includes('PROMOTE') ? '缓存提升' : '缓存复制') : e.dir;

      mH += `<div class="eitem ${i === 0 ? 'latest' : ''}">
        <span style="color:#5a7a96">${e.ts}</span>
        <span style="color:${dirColor};font-weight:700">${actionLabel}</span>
        <span style="color:#e4edf6">${e.obj}</span>
        <span style="color:#5a7a96">${e.from}→${e.to}</span>
        ${isCache ? '<span style="color:#4488ff;font-size:.9rem">📋 缓存副本</span>' : ''} |
        <span style="color:#ffb020">触发: ${e.reason}</span>
      </div>`;
    });
  }

  // Snapshot events
  let sH = '';
  if (!tierSnapEvts.length) {
    sH = '<div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:20px">冷数据下沉后自动触发快照...</div>';
  } else {
    tierSnapEvts.forEach((e, i) => {
      const snapId = (e.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
      sH += `<div class="eitem ${i === 0 ? 'latest' : ''}" style="cursor:pointer" onclick="toggleSnapDetail('${e.name}','${snapId}')">
        <span style="color:#5a7a96">${e.ts}</span>
        <span style="color:#a060ff;font-weight:700">SNAPSHOT</span>
        <span style="color:#e4edf6">${e.name}</span> |
        对象:<span style="color:#ffb020">${e.count}</span> |
        耗时:<span style="color:#00e888">${e.dur}s</span>
        <span style="color:#5a7a96;font-size:1rem;margin-left:8px">▶ 点击查看详情</span>
      </div>
      <div id="snap-detail-${snapId}" style="display:none;margin:4px 0 8px 16px;padding:8px;background:#0d1b2a;border:1px solid #2d4a6640;border-radius:4px;max-height:300px;overflow-y:auto"></div>`;
    });
  }

  // 冻结状态提示（仅在运行中且仍处于冻结期时显示）
  const frozenTipH = (tierRunning && tierDisplayFrozen)
    ? `<div style="text-align:center;font-size:1rem;color:#5a7a96;margin-top:4px;font-style:italic">
        ⏳ 后台清理旧数据中，数据将在写入阶段开始后更新...
       </div>`
    : '';

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">分级存储能力演示</div>
        <div class="ctrl-status ${statusCls}">
          <div class="dot ${tierRunning ? 'dot-pulse' : ''}" style="background:${tierRunning ? '#00e888' : '#5a7a96'};width:6px;height:6px"></div>
          ${statusTxt}
        </div>
      </div>
      ${stepsH}
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0">
        热度(Heat Score): 根据访问频率和时间衰减自动计算。热度&gt;3.0提升至热层, &lt;0.5下沉至冷层。全程自动，无人工干预。<br>
        后端: 分布式存储 (warm_pool/cold_pool) + ramfs (/mnt/hot) | 真实迁移 · 真实快照
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <button class="btn btn-primary" onclick="startTier()" ${tierRunning ? 'disabled' : ''}>▶ 开始演示</button>
        <button class="btn btn-outline btn-sm" onclick="deployShow=!deployShow;renderM6()">📋 ${deployShow ? '收起' : '查看'}部署详情</button>
        <button class="btn btn-outline btn-sm" onclick="resetTier()">↻ 重置</button>
      </div>
      <div class="deploy-detail ${deployShow ? 'show' : ''}" style="margin-top:10px">
        <span style="color:#00d0f0">一键部署执行的操作：</span><br>
        1. 创建三层存储池: hot_pool (DRAM/ramfs), warm_pool (SSD), cold_pool (HDD)<br>
        2. 设置存储规则: 将不同池映射到不同存储介质<br>
        3. 配置缓存分层: hot_pool作为warm_pool的缓存层<br>
        4. 设置提升/降级阈值: 热度&gt;3.0提升, 热度&lt;0.5下沉 (滞后区间防抖动)<br>
        5. 启动热度追踪守护进程: 基于时间衰减的访问频率评分<br>
        6. 配置快照自动触发: 冷层数据到达阈值时自动创建快照
      </div>
    </div>
    <div class="g2" style="margin-top:14px">
      <div class="card span2">
        ${chead('三层存储分布', '🏗')}
        <div class="card-body">${vizH}${frozenTipH}</div>
      </div>
      <div class="card">${chead('迁移事件', '🔄', '#00d0f0', tag('LIVE', '#00e888'))}<div class="card-body"><div id="tier-mig-log" class="elog">${mH}</div></div></div>
      <div class="card">${chead('快照/备份事件', '💾', '#a060ff')}<div class="card-body"><div id="tier-snap-log" class="elog">${sH}</div></div></div>
      <div class="card span2">${chead('热度阈值配置', '🌡')}<div class="card-body">
        <div class="g4">${[
          { l: '提升至热层', v: '> 3.0', c: '#ff4050', desc: '高频数据升入DRAM' },
          { l: '热层降级',   v: '< 2.0', c: '#ffb020', desc: '访问减少降回SSD' },
          { l: '提升至温层', v: '> 1.0', c: '#ffb020', desc: '冷数据回访后回迁' },
          { l: '下沉至冷层', v: '< 0.5', c: '#4488ff', desc: '长期无访问归档HDD' }
        ].map(t => `<div style="padding:10px;background:#1b2a3d;border-radius:6px;text-align:center;border:1px solid ${t.c}20">
          <div style="font-size:1rem;color:#5a7a96;margin-bottom:3px">${t.l}</div>
          <div class="mono" style="font-size:2.2rem;font-weight:700;color:${t.c}">${t.v}</div>
          <div style="font-size:.9rem;color:#5a7a96;margin-top:2px">${t.desc}</div>
        </div>`).join('')}</div>
      </div></div>
    </div>`;
}

async function startTier() {
  if (tierRunning) return;

  // ── 关键：保存当前显示数据作为冻结快照，不清零 ──
  tierFrozenSnapshot = { ...tierState };
  tierDisplayFrozen = true;
  // ─────────────────────────────────────────────────

  tierRunning = true;
  tierStep = 0;
  tierMigEvts = [];
  tierSnapEvts = [];
  // 注意：tierState 不在这里重置，由后端数据驱动
  renderM6();

  try {
    const res = await fetch(`${TIER_API}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (!data.ok) {
      console.error('[M6] start failed:', data.error);
      tierRunning = false;
      tierDisplayFrozen = false;
      renderM6();
      return;
    }
    connectTierSSE();
  } catch (e) {
    console.error('[M6] start error:', e);
    tierRunning = false;
    tierDisplayFrozen = false;
    renderM6();
  }
}

function connectTierSSE() {
  if (tierEventSource) tierEventSource.close();

  tierEventSource = new EventSource(`${TIER_API}/stream`);

  tierEventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      updateTierFromData(data);
      if (data.done) {
        tierEventSource.close();
        tierEventSource = null;
      }
    } catch (e) {
      console.error('[M6] SSE parse error:', e);
    }
  };

  tierEventSource.onerror = () => {
    if (tierEventSource) { tierEventSource.close(); tierEventSource = null; }
    startTierPolling();
  };
}

function startTierPolling() {
  if (tierPollTimer) clearInterval(tierPollTimer);
  tierPollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${TIER_API}/status`);
      const data = await res.json();
      if (data.ok) {
        updateTierFromData(data);
        if (!data.running && data.step > 0) {
          clearInterval(tierPollTimer);
          tierPollTimer = null;
        }
      }
    } catch (e) {
      console.error('[M6] polling error:', e);
    }
  }, 1500);
}

function updateTierFromData(data) {
  const prevStep    = tierStep;
  const prevRunning = tierRunning;

  if (data.running !== undefined) tierRunning = data.running;
  if (data.step    !== undefined) tierStep    = data.step;

  // ── 解冻判断：后端进入 step 1（写入温层）后才解冻 ──
  // step > 0 表示清理完毕，正式开始写数据
  if (tierDisplayFrozen && tierStep > 0) {
    tierDisplayFrozen = false;
  }

  // 更新实时数据（无论是否解冻都更新 tierState，解冻后才会呈现）
  if (data.tier_state) {
    tierState = data.tier_state;
  }

  if (data.migration_events) tierMigEvts = data.migration_events;
  if (data.snapshot_events)  tierSnapEvts = data.snapshot_events;

  // 步骤或运行状态变化 → 全量重绘（更新步骤条、按钮、冻结提示）
  if (prevStep !== tierStep || prevRunning !== tierRunning) {
    renderM6();
    return;
  }

  // 其余情况 → 局部更新（不重建 DOM，保留快照展开状态）
  updateTierPartial();
}

function updateTierPartial() {
  // 决定展示哪份数据
  const displayState = tierDisplayFrozen ? tierFrozenSnapshot : tierState;
  const total = displayState.hot + displayState.warm + displayState.cold || 1;
  const counts = [displayState.hot, displayState.warm, displayState.cold];

  // 更新数字
  document.querySelectorAll('.tier-count').forEach((el, i) => {
    if (counts[i] !== undefined) el.textContent = counts[i];
  });
  // 更新百分比条
  document.querySelectorAll('.tier-block').forEach((el, i) => {
    const pct = counts[i] / total * 100;
    const bg = el.querySelector('.tier-bg');
    if (bg) bg.style.height = pct + '%';
  });

  // 更新迁移事件
  const migLog = document.getElementById('tier-mig-log');
  if (migLog) {
    let mH = '';
    if (!tierMigEvts.length) {
      mH = '<div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:20px">等待演示开始...</div>';
    } else {
      tierMigEvts.forEach((e, i) => {
        mH += `<div class="eitem ${i === 0 ? 'latest' : ''}">
          <span style="color:#5a7a96">${e.ts}</span>
          <span style="color:${e.dir.includes('PROMOTE') ? '#00e888' : '#00d0f0'};font-weight:700">${e.dir}</span>
          <span style="color:#e4edf6">${e.obj}</span>
          <span style="color:#5a7a96">${e.from}→${e.to}</span> |
          <span style="color:#ffb020">触发: ${e.reason}</span>
        </div>`;
      });
    }
    migLog.innerHTML = mH;
  }

  // 快照区域：有新快照才重绘（避免破坏已展开的详情）
  const snapLog = document.getElementById('tier-snap-log');
  if (snapLog && tierSnapEvts.length > snapLog.querySelectorAll('.eitem').length) {
    let sH = '';
    tierSnapEvts.forEach((e, i) => {
      const snapId = (e.name || '').replace(/[^a-zA-Z0-9_-]/g, '_');
      sH += `<div class="eitem ${i === 0 ? 'latest' : ''}" style="cursor:pointer" onclick="toggleSnapDetail('${e.name}','${snapId}')">
        <span style="color:#5a7a96">${e.ts}</span>
        <span style="color:#a060ff;font-weight:700">SNAPSHOT</span>
        <span style="color:#e4edf6">${e.name}</span> |
        对象:<span style="color:#ffb020">${e.count}</span> |
        耗时:<span style="color:#00e888">${e.dur}s</span>
        <span style="color:#5a7a96;font-size:1rem;margin-left:8px">▶ 点击查看详情</span>
      </div>
      <div id="snap-detail-${snapId}" style="display:none;margin:4px 0 8px 16px;padding:8px;background:#0d1b2a;border:1px solid #2d4a6640;border-radius:4px;max-height:300px;overflow-y:auto"></div>`;
    });
    snapLog.innerHTML = sH;
  }
}

async function resetTier() {
  if (tierEventSource) { tierEventSource.close(); tierEventSource = null; }
  if (tierPollTimer)   { clearInterval(tierPollTimer); tierPollTimer = null; }

  try {
    await fetch(`${TIER_API}/reset`, { method: 'POST' });
  } catch (e) {
    console.error('[M6] reset error:', e);
  }

  tierRunning       = false;
  tierStep          = 0;
  tierMigEvts       = [];
  tierSnapEvts      = [];
  tierState         = { hot: 0, warm: 0, cold: 0 };
  tierDisplayFrozen = true;
  tierFrozenSnapshot = { hot: 0, warm: 0, cold: 0 };
  renderM6();
}

async function toggleSnapDetail(snapName, snapId) {
  const el = document.getElementById('snap-detail-' + snapId);
  if (!el) return;

  if (el.style.display !== 'none') {
    el.style.display = 'none';
    return;
  }

  el.style.display = 'block';
  el.innerHTML = '<div style="color:#5a7a96;font-size:1.1rem;padding:8px">加载快照内容...</div>';

  try {
    const res  = await fetch(`${TIER_API}/snapshot/${snapName}`);
    const data = await res.json();
    if (!data.ok) {
      el.innerHTML = `<div style="color:#ff4050;font-size:1.1rem;padding:8px">加载失败: ${data.error}</div>`;
      return;
    }

    const storageTag = data.storage === 'ceph_backup_pool'
      ? `<span style="color:#00e888;font-weight:700;margin-left:8px">[已备份至 Ceph backup_pool]</span>`
      : '';
    let html = `<div style="font-size:1.1rem;color:#c0d8f0;margin-bottom:6px;font-weight:700">
      快照: ${data.name} | 时间: ${data.timestamp} | 共 ${data.count} 个对象${storageTag}
    </div>`;
    html += `<table class="dtable" style="font-size:1rem">
      <thead><tr><th style="width:40px">#</th><th>对象名称</th><th style="width:70px">大小(B)</th><th>哈希</th></tr></thead><tbody>`;
    data.objects.forEach((obj, i) => {
      html += `<tr>
        <td style="color:#5a7a96">${i + 1}</td>
        <td style="color:#e4edf6">${obj.name}</td>
        <td style="color:#ffb020">${obj.size}</td>
        <td style="color:#5a7a96;font-family:'Share Tech Mono',monospace">${obj.hash}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = `<div style="color:#ff4050;font-size:1.1rem;padding:8px">请求失败: ${e.message}</div>`;
  }
}