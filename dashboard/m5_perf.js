// ============================================================
// m5_perf.js — §5 吞吐量 & 扩展性演示（重写版）
//
// 设计：
//   · 本端点"开始本轮"，每 800ms 拉 /api/demo5/live?round=N 取曲线
//   · 4 张曲线（IOPS / 吞吐量 / 平均延迟 / P99 延迟）叠加 3 轮
//   · 右侧并排展示对端实时 shm metrics（通过 /api/peer/demo5/snapshot 取）
//   · 汇总表比较三轮"规模 vs 性能"
// ============================================================

const D5_API_SELF = (window.API_BASE || location.origin) + '/api/demo5';
const D5_API_PEER = (window.API_BASE || location.origin) + '/api/peer/demo5';

const D5 = {
  rounds: {                                    // 本端 3 轮
    1: { running:false, phase:'idle', count:10000,  samples:[], summary:null },
    2: { running:false, phase:'idle', count:50000,  samples:[], summary:null },
    3: { running:false, phase:'idle', count:100000, samples:[], summary:null },
  },
  currentRound: 0,         // 0 表示还未开跑
  peerRounds: null,        // 对端 snapshot_all 结果（只读展示）
  peerMetrics: null,
  selfMetrics: null,
  poll: null,
};

const D5_COLORS = ['#ff6060', '#f0c030', '#40a0ff'];
const D5_LABELS = ['第一轮 1万', '第二轮 5万', '第三轮 10万'];

// ------------------------------------------------------------
// 渲染
// ------------------------------------------------------------
function renderM5() {
  const el = document.getElementById('pg-m5');
  if (!el) return;

  const running = Object.values(D5.rounds).some(r => r.running);
  const doneCnt = Object.values(D5.rounds).filter(r => r.summary).length;

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">⑤ 系统吞吐量 & 扩展性测试（RDMA）</div>
        <div class="ctrl-status ${running?'running':doneCnt>0?'done':'idle'}">
          <div class="dot ${running?'dot-pulse':''}" style="background:${running?'#00e888':'#5a7a96'};width:6px;height:6px"></div>
          ${running ? '压测进行中...' : doneCnt>0 ? `已完成 ${doneCnt}/3 轮` : '就绪'}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:6px">
        · 本端 <span class="mono" style="color:#c0d8f0">nr_bench</span> 以逐轮递增的 keyspace (1万/5万/10万 1KB 对象) 持续 12 秒并发 PUT<br>
        · 数据平面通过 RDMA WRITE 将每条写入跨节点复制；UI 每秒采样 shm metrics 绘制曲线<br>
        · <span style="color:#ffb020">对端指标实时呈现</span>：展示 peer 的 shm 读数，验证"真实跨节点"而非本地模拟
      </div>
      <div class="ctrl-row">
        <button class="btn btn-round-1 btn-sm" onclick="d5Start(1)" ${d5BtnDisabled(1)}>▶ 第一轮 1万</button>
        <button class="btn btn-round-2 btn-sm" onclick="d5Start(2)" ${d5BtnDisabled(2)}>▶ 第二轮 5万</button>
        <button class="btn btn-round-3 btn-sm" onclick="d5Start(3)" ${d5BtnDisabled(3)}>▶ 第三轮 10万</button>
        <div style="flex:1"></div>
        <button class="btn btn-outline btn-sm" onclick="d5Reset()">↻ 重置</button>
      </div>
    </div>

    <div class="g2" style="margin-top:12px">
      ${d5MetricsCard('本端 (节点 A) 实时指标', D5.selfMetrics, '#00e888')}
      ${d5MetricsCard('对端 (节点 B) 实时指标', D5.peerMetrics, '#00d0f0')}
    </div>

    <div class="g2" style="margin-top:12px">
      <div class="card">${chead('IOPS 曲线 (ops/s)',      '⚡', '#ff6090')}<div class="card-body"><div style="height:170px">${d5Chart('iops')}</div></div></div>
      <div class="card">${chead('吞吐量曲线 (MB/s)',       '🚀', '#00d0f0')}<div class="card-body"><div style="height:170px">${d5Chart('tp')}</div></div></div>
      <div class="card">${chead('平均延迟曲线 (μs)',       '⏳', '#ffb020')}<div class="card-body"><div style="height:170px">${d5Chart('lat')}</div></div></div>
      <div class="card">${chead('P99 延迟曲线 (μs)',        '📈', '#a060ff')}<div class="card-body"><div style="height:170px">${d5Chart('p99')}</div></div></div>
    </div>

    <div class="card" style="margin-top:12px">${chead('三轮汇总（规模 → 性能）', '📊')}
      <div class="card-body">${d5Summary()}</div>
    </div>`;
}

function d5BtnDisabled(round) {
  const r = D5.rounds[round];
  if (r.running) return 'disabled';
  if (r.summary) return 'disabled';
  const anyRunning = Object.values(D5.rounds).some(x => x.running);
  return anyRunning ? 'disabled' : '';
}

function d5MetricsCard(title, m, color) {
  if (!m) {
    return `<div class="card">${chead(title, '📡', color)}
      <div class="card-body"><div style="color:#5a7a96;padding:12px;text-align:center">尚未获取指标...</div></div>
    </div>`;
  }
  return `<div class="card">${chead(title, '📡', color, tag('LIVE', '#00e888'))}
    <div class="card-body">
      <div class="g4">
        ${metric('ops/s',    F(m.ops_per_sec||0, 0),         '',   color)}
        ${metric('bw_tx',    F(m.bw_tx_gbps||0, 2),          'Gbps','#00d0f0')}
        ${metric('lat_avg',  F(m.lat_avg_us||0, 2),          'μs', '#ffb020')}
        ${metric('lat_p99',  F(m.lat_p99_us||0, 2),          'μs', '#a060ff')}
      </div>
      <div class="g4" style="margin-top:10px">
        ${metric('rdma_util',F(m.rdma_util_pct||0, 1),       '%',  '#ff6090')}
        ${metric('ops_total',F((m.ops_total||0)/1e6, 2),     'M',  '#5a7a96')}
        ${metric('obj_dram', m.obj_dram||0,                  '',   '#ff4050')}
        ${metric('obj_hdd',  m.obj_hdd||0,                   '',   '#4488ff')}
      </div>
    </div>
  </div>`;
}

// SVG 4 合 1 曲线
function d5Chart(type) {
  const w = 480, h = 150, pad = 38;
  let svg = `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px" preserveAspectRatio="none">`;
  svg += `<line x1="${pad}" y1="5" x2="${pad}" y2="${h-20}" stroke="#2d4a66"/>`;
  svg += `<line x1="${pad}" y1="${h-20}" x2="${w-5}" y2="${h-20}" stroke="#2d4a66"/>`;

  // 找所有值
  let maxT = 0, all = [];
  for (let rr=1; rr<=3; rr++) {
    const samps = D5.rounds[rr].samples;
    if (samps.length > maxT) maxT = samps.length;
    samps.forEach(p => { if (p[type] != null) all.push(p[type]); });
  }
  if (all.length === 0) {
    svg += `<text x="${w/2}" y="${h/2}" fill="#5a7a96" font-size="11" text-anchor="middle" font-family="Share Tech Mono">等待数据...</text>`;
    return svg + '</svg>';
  }
  const mx = Math.max(...all) || 1;
  const mn = Math.max(0, Math.min(...all) * 0.9);
  const rng = mx - mn || 1;
  const xMax = Math.max(maxT, 8);

  // 横轴
  for (let t=0; t<=xMax; t += Math.max(2, Math.floor(xMax/4))) {
    const x = pad + (t / xMax) * (w - pad - 5);
    svg += `<text x="${x}" y="${h-6}" fill="#5a7a96" font-size="9" text-anchor="middle" font-family="Share Tech Mono">${t}s</text>`;
  }
  // 纵轴 5 刻度
  for (let i=0; i<=4; i++) {
    const v = mn + rng * i / 4;
    const y = 8 + ((mx - v) / rng) * (h - 36);
    svg += `<line x1="${pad}" y1="${y}" x2="${w-5}" y2="${y}" stroke="#2d4a6633" stroke-dasharray="2,2"/>`;
    const vv = v>=1e6 ? (v/1e6).toFixed(1)+'M' : v>=1e3 ? (v/1e3).toFixed(1)+'K' : v.toFixed(1);
    svg += `<text x="${pad-4}" y="${y+3}" fill="#5a7a96" font-size="8" text-anchor="end" font-family="Share Tech Mono">${vv}</text>`;
  }

  // 3 条曲线
  for (let rr=1; rr<=3; rr++) {
    const samps = D5.rounds[rr].samples;
    if (samps.length < 2) continue;
    const color = D5_COLORS[rr-1];
    const pts = [];
    samps.forEach((p, i) => {
      if (p[type] == null) return;
      const x = pad + (i / xMax) * (w - pad - 5);
      const y = 8 + ((mx - p[type]) / rng) * (h - 36);
      pts.push(`${x},${y}`);
    });
    if (pts.length < 2) continue;
    svg += `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`;
    const last = pts[pts.length-1].split(',').map(Number);
    svg += `<circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}"/>`;
  }
  return svg + '</svg>';
}

function d5Summary() {
  const rows = [1,2,3].filter(r => D5.rounds[r].summary);
  if (!rows.length) return `<div style="color:#5a7a96;padding:16px;text-align:center">尚未有完成的轮次</div>`;
  let body = '<table class="dtable"><thead><tr>' +
    ['轮次','对象数','线程','ops/s','吞吐 MB/s','bw Gbps','延迟 avg','p50','p99','p99.9']
      .map(h => `<th style="text-align:right">${h}</th>`).join('') +
    '</tr></thead><tbody>';
  rows.forEach(r => {
    const s = D5.rounds[r].summary;
    body += `<tr>
      <td style="text-align:right;color:${D5_COLORS[r-1]};font-weight:700">${D5_LABELS[r-1]}</td>
      <td style="text-align:right">${s.count.toLocaleString()}</td>
      <td style="text-align:right">${s.threads}</td>
      <td style="text-align:right;color:#ff6090;font-weight:700">${s.iops.toLocaleString()}</td>
      <td style="text-align:right">${F(s.tp_mbps, 2)}</td>
      <td style="text-align:right;color:#00d0f0">${F(s.gbps, 3)}</td>
      <td style="text-align:right">${F(s.lat_avg_us, 2)}</td>
      <td style="text-align:right">${F(s.lat_p50_us, 2)}</td>
      <td style="text-align:right;color:#a060ff">${F(s.lat_p99_us, 2)}</td>
      <td style="text-align:right;color:#5a7a96">${F(s.lat_p99_9_us, 2)}</td>
    </tr>`;
  });
  body += '</tbody></table>';
  return body;
}

// ------------------------------------------------------------
// 动作
// ------------------------------------------------------------
async function d5Start(round) {
  try {
    const res = await fetch(`${D5_API_SELF}/start`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ round }),
    });
    const j = await res.json();
    if (!j.ok) { alert('启动失败: ' + (j.error || '?')); return; }
    D5.rounds[round].running = true;
    D5.currentRound = round;
    renderM5();
  } catch (e) { alert('start err: ' + e.message); }
}

async function d5Reset() {
  if (!confirm('重置所有压测结果？')) return;
  try {
    await fetch(`${D5_API_SELF}/reset`, { method:'POST' });
  } catch (_) {}
  for (let r=1;r<=3;r++) {
    D5.rounds[r].samples  = [];
    D5.rounds[r].summary  = null;
    D5.rounds[r].running  = false;
    D5.rounds[r].phase    = 'idle';
  }
  D5.currentRound = 0;
  renderM5();
}

async function d5Refresh() {
  try {
    // 本端 snapshot
    const res = await fetch(`${D5_API_SELF}/snapshot`);
    const j   = await res.json();
    if (j.ok) {
      for (let r=1; r<=3; r++) {
        const rr = j.rounds[r];
        if (!rr) continue;
        D5.rounds[r].running = rr.running;
        D5.rounds[r].phase   = rr.phase;
        D5.rounds[r].count   = rr.count;
        D5.rounds[r].samples = rr.samples;
        D5.rounds[r].summary = rr.summary;
      }
      D5.selfMetrics = j.metrics;
    }
    // 对端 snapshot（只用来展示 peer 实时指标）
    const pr  = await fetch(`${D5_API_PEER}/snapshot`);
    const pj  = await pr.json();
    if (pj.ok) {
      D5.peerMetrics = pj.metrics;
      D5.peerRounds  = pj.rounds;
    }
  } catch (e) { /* silent */ }
  renderM5();
}

function d5StartPoll() {
  if (D5.poll) return;
  D5.poll = setInterval(d5Refresh, 800);
}
function d5StopPoll() {
  if (D5.poll) { clearInterval(D5.poll); D5.poll = null; }
}

(function _initM5() {
  const prev = window.goPage;
  window.goPage = function (name, el) {
    prev(name, el);
    if (name === 'm5') { d5Refresh(); d5StartPoll(); }
    else                { d5StopPoll(); }
  };
})();
