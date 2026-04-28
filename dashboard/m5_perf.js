// ============================================================
// m5_perf.js — 模块五：系统吞吐量及实体数量增加对性能影响
// 调用真实后端API (Flask + native_rdma 分布式共享空间)
// 使用轮询实时拉取性能数据
// ============================================================

const PERF_API = (window.API_BASE || 'http://localhost:5000') + '/api/m5';

let perfRound = 0, perfRunning = false;
let perfData = { 1: [], 2: [], 3: [] };
// 用 round 做 key，避免重复
let perfSummary = {};  // { 1: {...}, 2: {...}, 3: {...} }
let perfPollTimer = null;

const ROUND_COLORS = ['#ff6060', '#f0c030', '#40a0ff'];
const ROUND_LABELS = ['第一轮(1万)', '第二轮(5万)', '第三轮(10万)'];
const ROUND_COUNTS = [10000, 50000, 100000];

function renderM5() {
  const el = document.getElementById('pg-m5');
  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">系统吞吐量与扩展性测试</div>
        <div class="ctrl-status ${perfRunning ? 'running' : perfRound > 0 ? 'done' : 'idle'}">
          <div class="dot ${perfRunning ? 'dot-pulse' : ''}" style="background:${perfRunning ? '#00e888' : '#5a7a96'};width:6px;height:6px"></div>
          ${perfRunning ? 'RDMA 分布式写入中...' : perfRound > 0 ? `已完成${perfRound}轮` : '就绪'}
        </div>
      </div>

      <!-- 双节点状态信息 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;background:#0a1420;padding:10px;border-radius:6px">
        <div style="font-size:1.1rem">
          <div style="color:#00e888;font-weight:700;margin-bottom:4px">● 节点A (xfusion3)</div>
          <div style="color:#5a7a96;margin-left:10px">IP: ${window.API_BASE_A ? window.API_BASE_A.replace('http://','').replace(':5000','') : '10.26.42.224'}</div>
          <div style="margin-left:10px">角色: 协调节点(预填充+测试)</div>
        </div>
        <div style="font-size:1.1rem">
          <div style="color:#00d0f0;font-weight:700;margin-bottom:4px">● 节点B (xfusion4)</div>
          <div style="color:#5a7a96;margin-left:10px">IP: ${window.API_BASE_B ? window.API_BASE_B.replace('http://','').replace(':5000','') : '10.26.42.225'}</div>
          <div style="margin-left:10px">角色: 测试节点(并行测试)</div>
        </div>
      </div>

      <div style="font-size:1rem;color:#5a7a96;margin-bottom:8px;font-family:'Share Tech Mono',monospace;background:#0d1b2a;padding:8px;border-radius:4px">
        执行: 双节点真实 RDMA 分布式共享空间写入 | 1KB 逻辑对象进行跨节点复制 | 每轮 12 秒<br>
        后端: nr_bench + native_rdma_dp | Pool: default/slab1k | 展示真实 RDMA 逻辑吞吐与延迟分布
      </div>
      <div class="ctrl-row">
        <button class="btn btn-round-1 btn-sm" onclick="startPerfRound(1)" ${perfRound >= 1 || perfRunning ? 'disabled' : ''}>▶ 第一轮: 1万对象</button>
        <button class="btn btn-round-2 btn-sm" onclick="startPerfRound(2)" ${perfRound < 1 || perfRound >= 2 || perfRunning ? 'disabled' : ''}>▶ 第二轮: 5万对象</button>
        <button class="btn btn-round-3 btn-sm" onclick="startPerfRound(3)" ${perfRound < 2 || perfRound >= 3 || perfRunning ? 'disabled' : ''}>▶ 第三轮: 10万对象</button>
        <div style="flex:1"></div>
        <div style="display:flex;gap:8px;font-size:1rem;align-items:center">
          <span style="color:#ff6060">● 1万</span><span style="color:#f0c030">● 5万</span><span style="color:#40a0ff">● 10万</span>
        </div>
        <button class="btn btn-outline btn-sm" onclick="resetPerf()">↻ 重置</button>
      </div>
    </div>
    <div class="g2">
      <div class="card">${chead('IOPS曲线(对象数/s)', '⚡', '#ff6090')}<div class="card-body"><div id="chart-iops" style="height:160px">${renderPerfChart('iops')}</div></div></div>
      <div class="card">${chead('吞吐量曲线(MB/s,每秒传输量)', '🚀', '#00d0f0')}<div class="card-body"><div id="chart-tp" style="height:160px">${renderPerfChart('tp')}</div></div></div>
      <div class="card">${chead('平均延迟曲线(μs)', '⏳', '#ffb020')}<div class="card-body"><div id="chart-lat" style="height:160px">${renderPerfChart('lat')}</div></div></div>
      <div class="card">${chead('P99延迟曲线(μs)', '📈', '#a060ff')}<div class="card-body"><div id="chart-p99" style="height:160px">${renderPerfChart('p99')}</div></div></div>
    </div>
    <div class="card" style="margin-top:14px">${chead('汇总数据表', '📊')}<div class="card-body" id="perf-table-body">
      ${renderPerfTable()}
    </div></div>
    <div class="card" style="margin-top:14px">${chead('指标注释', '📖')}<div class="card-body" style="font-size:1.1rem;color:#7a95b0;line-height:1.8">
      <b style="color:#c0d8f0">RDMA 分布式写入</b> - 真实跨节点 RDMA WRITE，IOPS 按 1KB 逻辑对象统计 |
      <b style="color:#c0d8f0">平均延迟</b> - 每个 PUT 包含本地写入 + 跨节点复制 + ACK |
      <b style="color:#c0d8f0">P99 延迟</b> - 性能要求项，目标 ≤ 100μs，来自真实 shm 采样
    </div></div>`;}

function renderPerfChart(type) {
  const w = 480, h = 150, pad = 35;
  let svg = `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px" preserveAspectRatio="none">`;

  svg += `<line x1="${pad}" y1="5" x2="${pad}" y2="${h - 20}" stroke="#2d4a66" stroke-width="1"/>`;
  svg += `<line x1="${pad}" y1="${h - 20}" x2="${w - 5}" y2="${h - 20}" stroke="#2d4a66" stroke-width="1"/>`;

  // 根据实际数据点数量确定横轴范围
  let maxDataPoints = 0;
  for (let rr = 1; rr <= 3; rr++) {
    if (perfData[rr] && perfData[rr].length > maxDataPoints) {
      maxDataPoints = perfData[rr].length;
    }
  }
  const xMax = Math.max(maxDataPoints, 8);  // 至少显示8秒

  for (let t = 0; t <= xMax; t += Math.max(2, Math.floor(xMax/4))) {
    const x = pad + (t / xMax) * (w - pad - 5);
    svg += `<text x="${x}" y="${h - 6}" fill="#5a7a96" font-size="9" text-anchor="middle" font-family="Share Tech Mono">${t}s</text>`;
    svg += `<line x1="${x}" y1="5" x2="${x}" y2="${h - 20}" stroke="#2d4a6633" stroke-width="1"/>`;
  }

  const allVals = [];
  for (let rr = 1; rr <= 3; rr++) {
    if (perfData[rr]) perfData[rr].forEach(p => { if (p[type] != null) allVals.push(p[type]); });
  }
  if (allVals.length === 0) {
    svg += `<text x="${w / 2}" y="${h / 2}" fill="#5a7a96" font-size="11" text-anchor="middle" font-family="Share Tech Mono">等待数据...</text>`;
    svg += `</svg>`;
    return svg;
  }

  const mx = Math.max(...allVals), mn = Math.min(...allVals) * 0.9;
  const rng = mx - mn || 1;

  // 定义纵轴单位
  const yAxisUnits = {
    'iops':     { label: 'IOPS',   unit: 'ops/s' },
    'tp':       { label: '吞吐',   unit: 'MB/s' },
    'lat':      { label: '延迟',   unit: 'μs' },
    'p99':      { label: 'P99',    unit: 'μs' },
  };

  // 绘制纵轴刻度（5个刻度）
  for (let i = 0; i <= 4; i++) {
    const val = mn + (rng * i / 4);
    const y = 8 + ((mx - val) / rng) * (h - 36);

    // 绘制刻度线
    svg += `<line x1="${pad}" y1="${y}" x2="${w - 5}" y2="${y}" stroke="#2d4a6633" stroke-width="1" stroke-dasharray="2,2"/>`;

    // 绘制刻度数值
    const absVal = Math.abs(val);
    const valText = absVal >= 1_000_000_000
      ? (val / 1_000_000_000).toFixed(1) + 'G'
      : absVal >= 1_000_000
        ? (val / 1_000_000).toFixed(1) + 'M'
        : absVal >= 1000
          ? (val / 1000).toFixed(1) + 'K'
          : val.toFixed(1);
    svg += `<text x="${pad - 5}" y="${y + 3}" fill="#5a7a96" font-size="8" text-anchor="end" font-family="Share Tech Mono">${valText}</text>`;
  }

  // 绘制纵轴单位标签（放在图表顶部中间）
  const unitInfo = yAxisUnits[type] || { label: '', unit: '' };
  svg += `<text x="${w / 2}" y="10" fill="#5a7a96" font-size="9" text-anchor="middle" font-family="Share Tech Mono">${unitInfo.unit}</text>`;

  for (let r = 1; r <= 3; r++) {
    const d = perfData[r];
    if (!d || d.length < 2) continue;
    const color = ROUND_COLORS[r - 1];

    // 过滤掉 null 值
    const validPts = [];
    d.forEach((p, i) => {
      if (p[type] != null) {
        const x = pad + (i / xMax) * (w - pad - 5);
        const y = 8 + ((mx - p[type]) / rng) * (h - 36);
        validPts.push({ x, y });
      }
    });
    if (validPts.length < 2) continue;

    const pts = validPts.map(p => `${p.x},${p.y}`);

    svg += `<defs><linearGradient id="pg_${type}_${r}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity="0.15"/><stop offset="100%" stop-color="${color}" stop-opacity="0.02"/></linearGradient></defs>`;
    svg += `<polygon points="${validPts[0].x},${h - 20} ${pts.join(' ')} ${validPts[validPts.length-1].x},${h - 20}" fill="url(#pg_${type}_${r})"/>`;
    svg += `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;

    const lastP = validPts[validPts.length - 1];
    svg += `<circle cx="${lastP.x}" cy="${lastP.y}" r="3" fill="${color}"/>`;
  }

  svg += `</svg>`;
  return svg;
}

function renderPerfTable() {
  // 按轮次1/2/3顺序渲染，用 perfSummary[round] 取数据
  const rounds = [1, 2, 3].filter(r => perfSummary[r]);
  if (rounds.length === 0) {
    return '<div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:20px">点击按钮逐轮执行测试，结果将逐行添加</div>';
  }

  const headers = ['轮次', '对象数', '节点', '逻辑IOPS(ops/s)', 'Ceph吞吐量(MB/s)', '平均延迟(μs)', 'P90延迟(μs)', 'P99延迟(μs)'];
  let rows = rounds.map(r => {
    const s = perfSummary[r];
    const isDual = s.dual_node;
    const nodeModeLabel = s.node_mode === 'dual'
      ? `<span style="color:#00e888;font-weight:700">[双节点]</span>`
      : `<span style="color:#ff4050;font-weight:700">[单节点]</span>`;
    const modeLabel = s.mode === 'ceph_aggregate'
      ? `<span style="color:#00d0f0;font-weight:700">[Ceph聚合]</span>`
      : `<span style="color:#ffb020;font-weight:700">[RADOS基线]</span>`;
    return `<tr>
      <td style="text-align:right;color:${ROUND_COLORS[r - 1]};font-weight:700">${ROUND_LABELS[r - 1]} ${nodeModeLabel} ${modeLabel}</td>
      <td style="text-align:right">${s.count.toLocaleString()}</td>
      <td style="text-align:right;color:#00e888">${isDual ? '<span style="color:#00e888">双节点</span>' : '<span style="color:#5a7a96">单节点</span>'}</td>
      <td style="text-align:right;color:#ff6090;font-weight:700">${s.iops ? s.iops.toLocaleString() : '-'}</td>
      <td style="text-align:right">${F(s.tp, 2)}</td>
      <td style="text-align:right">${F(s.avg, 2)}</td>
      <td style="text-align:right">${F(s.p90, 2)}</td>
      <td style="text-align:right;color:#a060ff">${F(s.p99, 2)}</td>
    </tr>`;
  }).join('');
  return `<table class="dtable"><thead><tr>${headers.map(h => `<th style="text-align:right">${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>`;
}

async function startPerfRound(round) {
  if (perfRunning) return;
  perfRunning = true;
  perfData[round] = [];
  renderM5();

  try {
    const res = await fetch(`${PERF_API}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ round, mode: 'rdma_shared' }),
    });
    const data = await res.json();
    if (!data.ok) {
      console.error('[M5] start failed:', data.error);
      perfRunning = false;
      renderM5();
      return;
    }

    // 启动轮询拉取实时数据
    startPerfPolling(round);

  } catch (e) {
    console.error('[M5] start error:', e);
    perfRunning = false;
    renderM5();
  }
}

function startPerfPolling(round) {
  if (perfPollTimer) clearInterval(perfPollTimer);

  perfPollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${PERF_API}/live?round=${round}`);
      const data = await res.json();
      if (!data.ok) return;

      // 显示当前阶段
      const statusEl = document.querySelector('.ctrl-status');
      if (statusEl && (data.phase === 'preparing_rdma_shared' || data.phase === 'queued_rdma_shared')) {
        statusEl.innerHTML = `<div class="dot dot-pulse" style="background:#ffb020;width:6px;height:6px"></div>准备 RDMA 共享写入...`;
      } else if (statusEl && data.phase === 'testing_rdma_shared') {
        statusEl.innerHTML = `<div class="dot dot-pulse" style="background:#00e888;width:6px;height:6px"></div>真实 RDMA 分布式共享写入测试中...`;
      }

      // 更新曲线数据
      const points = data.data_points || [];
      if (points.length > perfData[round].length) {
        perfData[round] = points;
        // 实时更新五张图表
        ['iops', 'tp', 'lat', 'p99'].forEach(type => {
          const cel = document.getElementById('chart-' + type);
          if (cel) cel.innerHTML = renderPerfChart(type);
        });
      }

      // 测试完成
      if (!data.running && data.summary) {
        perfRunning = false;
        perfRound = round;
        perfSummary[round] = data.summary;

        clearInterval(perfPollTimer);
        perfPollTimer = null;
        renderM5();
      }
    } catch (e) {
      console.error('[M5] polling error:', e);
    }
  }, 800);
}

async function resetPerf() {
  if (perfPollTimer) {
    clearInterval(perfPollTimer);
    perfPollTimer = null;
  }

  try {
    await fetch(`${PERF_API}/reset`, { method: 'POST' });
  } catch (e) {
    console.error('[M5] reset error:', e);
  }

  perfRound = 0;
  perfRunning = false;
  perfData = { 1: [], 2: [], 3: [] };
  perfSummary = {};
  renderM5();
}
