// ============================================================
// m5_perf.js — §5 吞吐量 & 扩展性演示（重写版）
//
// 设计：
//   · 本端点"开始本轮"，每 800ms 拉 /api/demo5/snapshot 取曲线
//   · 3 张曲线（IOPS / 吞吐量 / RDMA 复制延迟）纵向排布，叠加 3 轮
//   · 汇总表比较三轮"规模 vs 性能"
// ============================================================

const D5_API_SELF = (window.API_BASE || location.origin) + '/api/demo5';

const D5 = {
  rounds: {                                    // 本端 3 轮
    1: { running:false, phase:'idle', count:10000,  duration_s:12, samples:[], summary:null },
    2: { running:false, phase:'idle', count:50000,  duration_s:12, samples:[], summary:null },
    3: { running:false, phase:'idle', count:100000, duration_s:12, samples:[], summary:null },
  },
  currentRound: 0,         // 0 表示还未开跑
  poll: null,
};

const D5_COLORS = ['#ff6060', '#f0c030', '#40a0ff'];
const D5_LABELS = ['第一轮 1万', '第二轮 5万', '第三轮 10万'];
const D5_ROUND_DURS = { 1:12, 2:12, 3:12 };
const D5_X_MAX = Math.max(...Object.values(D5_ROUND_DURS));

// ------------------------------------------------------------
// 渲染
// ------------------------------------------------------------
function renderM5() {
  const el = document.getElementById('pg-m5');
  if (!el) return;

  const running = Object.values(D5.rounds).some(r => r.running);
  const active = Object.values(D5.rounds).find(r => r.running);
  const doneCnt = Object.values(D5.rounds).filter(r => r.summary).length;
  const errors = d5Errors();
  const statusText = running
    ? (active && active.phase === 'warmup' ? '预热中...' : '压测进行中...')
    : doneCnt>0 ? `已完成 ${doneCnt}/3 轮` : '就绪';

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">⑤ 系统吞吐量 & 扩展性测试（RDMA）</div>
        <div class="ctrl-status ${running?'running':doneCnt>0?'done':'idle'}">
          <div class="dot ${running?'dot-pulse':''}" style="background:${running?'#00e888':'#5a7a96'};width:6px;height:6px"></div>
          ${statusText}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:6px">
        · 本端 <span class="mono" style="color:#c0d8f0">nr_bench</span> 按共享 keyspace 逐轮递增 (1万/5万/10万 1KB 对象) 并发 PUT；先 warmup，正式采样每轮 12 秒<br>
        · 所有 PUT 要求 peer 在线并完成真实跨节点复制，降级本地写不计入通过<br>
        · 横坐标统一为 0~12s，便于直接比较对象规模变化下的 IOPS、吞吐量和 RDMA 复制延迟
      </div>
      <div class="ctrl-row">
        <button class="btn btn-round-1 btn-sm" onclick="d5Start(1)" ${d5BtnDisabled(1)}>▶ 第一轮 1万</button>
        <button class="btn btn-round-2 btn-sm" onclick="d5Start(2)" ${d5BtnDisabled(2)}>▶ 第二轮 5万</button>
        <button class="btn btn-round-3 btn-sm" onclick="d5Start(3)" ${d5BtnDisabled(3)}>▶ 第三轮 10万</button>
        <div style="flex:1"></div>
        <button class="btn btn-outline btn-sm" onclick="d5Reset()">↻ 重置</button>
      </div>
      ${errors ? `<div style="margin-top:10px;padding:9px 12px;background:#ff405012;border:1px solid #ff405040;border-radius:6px;color:#ff9aa3;font-size:1rem">${errors}</div>` : ''}
    </div>

    <div style="display:grid;grid-template-columns:1fr;gap:12px;margin-top:12px">
      <div class="card">${chead('IOPS 曲线 (ops/s)',      '⚡', '#ff6090')}<div class="card-body"><div style="height:190px">${d5Chart('iops')}</div></div></div>
      <div class="card">${chead('吞吐量曲线 (MB/s)',       '🚀', '#00d0f0')}<div class="card-body"><div style="height:190px">${d5Chart('tp')}</div></div></div>
      <div class="card">${chead('RDMA 复制延迟曲线 (μs)',  '⏳', '#ffb020', tag('瞬时', '#ffb020'))}<div class="card-body"><div style="height:190px">${d5Chart('repl')}</div></div></div>
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

function d5Errors() {
  const xs = [];
  for (let r=1; r<=3; r++) {
    const err = D5.rounds[r].error || (D5.rounds[r].summary && D5.rounds[r].summary.error);
    if (err) xs.push(`${D5_LABELS[r-1]}: ${err}`);
  }
  return xs.map(x => `<div>${x}</div>`).join('');
}

// SVG 三轮叠加曲线；所有图固定使用同一条 0~12s 横轴。
function d5Chart(type) {
  const w = 720, h = 170, pad = 46;
  let svg = `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px" preserveAspectRatio="none">`;
  svg += `<line x1="${pad}" y1="5" x2="${pad}" y2="${h-20}" stroke="#2d4a66"/>`;
  svg += `<line x1="${pad}" y1="${h-20}" x2="${w-5}" y2="${h-20}" stroke="#2d4a66"/>`;

  // 找所有值
  let all = [];
  for (let rr=1; rr<=3; rr++) {
    const samps = D5.rounds[rr].samples;
    samps.forEach(p => { if (p[type] != null) all.push(p[type]); });
  }
  if (all.length === 0) {
    svg += `<text x="${w/2}" y="${h/2}" fill="#5a7a96" font-size="11" text-anchor="middle" font-family="Share Tech Mono">等待数据...</text>`;
    return svg + '</svg>';
  }
  // 根据曲线类型决定 y 轴 padding：
  //   · 延迟类 (lat / repl) 抖动幅度通常很小（RDMA 稳定在微秒级），
  //     需要在上下各留 20% 空间，让曲线的小抖动在视觉上明显可见
  //   · 吞吐类 (iops / tp) 从 0 起步更符合直觉，下界压到 0
  const isLat = (type === 'lat' || type === 'repl');
  let rawMax = Math.max(...all);
  let rawMin = Math.min(...all);
  let mx, mn;
  if (isLat) {
    const span = Math.max(rawMax - rawMin, rawMax * 0.2, 1);  // 最少 20% 或 1μs
    mx = rawMax + span * 0.25;
    mn = Math.max(0, rawMin - span * 0.25);
  } else {
    // IOPS / 吞吐：若数据都集中在高位（min > 30% * max），下界抬到 min*0.7
    // 让曲线抖动可见；否则保留 0 起点符合直觉。
    mx = rawMax * 1.1 || 1;
    mn = (rawMin > rawMax * 0.3) ? Math.max(0, rawMin * 0.7) : 0;
  }
  const rng = (mx - mn) || 1;
  const xMax = D5_X_MAX;

  // 横轴
  for (let t=0; t<=xMax; t += Math.max(3, Math.floor(xMax/4))) {
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
      const t = Math.min(xMax, Number(p.t != null ? p.t : i * 0.25));
      const x = pad + (t / xMax) * (w - pad - 5);
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
    ['轮次','对象数','覆盖 MB','时长','线程','限速','ops/s','吞吐 MB/s','bw Gbps','延迟 avg(μs)','p50(μs)','p90(μs)','p99(μs)']
      .map(h => `<th style="text-align:right">${h}</th>`).join('') +
    '</tr></thead><tbody>';
  rows.forEach(r => {
    const s = D5.rounds[r].summary;
    const p90 = s.lat_p90_us != null ? s.lat_p90_us : s.lat_p99_us;
    body += `<tr>
      <td style="text-align:right;color:${D5_COLORS[r-1]};font-weight:700">${D5_LABELS[r-1]}</td>
      <td style="text-align:right">${(s.count||0).toLocaleString()}</td>
      <td style="text-align:right;color:#ffb020">${F(s.footprint_mb||0, 1)}</td>
      <td style="text-align:right;color:#5a7a96">${s.duration_s||'-'}s</td>
      <td style="text-align:right">${s.threads}</td>
      <td style="text-align:right;color:#5a7a96">${s.max_iops ? s.max_iops.toLocaleString() : 'off'}</td>
      <td style="text-align:right;color:#ff6090;font-weight:700">${(s.iops||0).toLocaleString()}</td>
      <td style="text-align:right">${F(s.tp_mbps, 2)}</td>
      <td style="text-align:right;color:#00d0f0">${F(s.gbps, 3)}</td>
      <td style="text-align:right">${F(s.lat_avg_us, 2)}</td>
      <td style="text-align:right">${F(s.lat_p50_us, 2)}</td>
      <td style="text-align:right;color:#ffb020">${F(p90, 2)}</td>
      <td style="text-align:right;color:#a060ff">${F(s.lat_p99_us, 2)}</td>
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
    D5.rounds[r].error    = null;
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
        D5.rounds[r].duration_s = rr.duration_s || D5_ROUND_DURS[r];
        D5.rounds[r].samples = rr.samples;
        D5.rounds[r].summary = rr.summary;
        D5.rounds[r].error   = rr.error || (rr.summary && rr.summary.error) || null;
      }
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
