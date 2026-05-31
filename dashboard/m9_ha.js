// ============================================================
// m9_ha.js — 模块⑨：高可靠（Peer 故障降级）演示
// 调用 Flask /api/ha/* 和 /api/kv/*（打流观察 degraded 计数）
// ============================================================

const HA_API = (window.API_BASE || location.origin) + '/api/ha';
const KV_API = (window.API_BASE || location.origin) + '/api/kv';

let haStatus    = {};          // latest RPC_CLUSTER_STATUS result
let haPollTimer = null;
let haEvents    = [];          // ALLOW/DENY/KILL/RESTORE timeline

function haPushEvent(kind, color, text) {
  haEvents.unshift({
    ts: new Date().toLocaleTimeString(),
    kind, color, text
  });
  if (haEvents.length > 40) haEvents.pop();
}

function renderM9() {
  const el = document.getElementById('pg-m9');
  if (!el) return;

  const alive    = haStatus.peer_alive === true;
  const dp_up    = haStatus.dp_online !== false;
  const degN     = haStatus.degraded_puts  || 0;
  const degB     = haStatus.degraded_bytes || 0;
  const peerCtl  = haStatus.peer_ctl === true;

  // 状态大卡片
  const stateColor = !dp_up ? '#ff4050' : (alive ? '#00e888' : '#ffb020');
  const stateLabel = !dp_up ? '数据平面离线' : (alive ? '双节点正常' : '降级（peer 失联）');

  // 事件时间线
  const evH = haEvents.length === 0
    ? '<div style="color:#5a7a96;padding:20px;text-align:center">尚无故障演练事件</div>'
    : haEvents.map((e, i) => `<div class="eitem ${i === 0 ? 'latest' : ''}">
        <span style="color:#5a7a96">${e.ts}</span>
        <span style="color:${e.color};font-weight:700;min-width:88px;display:inline-block">${e.kind}</span>
        <span style="color:#e4edf6">${e.text}</span>
      </div>`).join('');

  const peerCtlWarn = !peerCtl
    ? `<div style="padding:10px;background:#ffb02015;border:1px solid #ffb02040;border-radius:6px;margin-top:10px;font-size:1rem;color:#ffb020">
        ⚠ 未配置 peer ssh 控制。无法从 Web 界面强杀/恢复 B 端进程。启动 Flask 前需设置：<br>
        <span class="mono" style="color:#c0d8f0">NR_PEER_SSH=&lt;user@peer&gt; NR_PEER_DP_PATH=&lt;/abs/path/to/native_rdma_dp&gt; NR_PEER_START_CMD="&lt;start-script&gt;"</span><br>
        未设置时，可手动在 peer 主机上 <span class="mono" style="color:#c0d8f0">pkill -9 -f 'build/bin/native_rdma_dp'</span> 模拟故障。
      </div>`
    : '';

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">高可靠（Peer 故障降级）</div>
        <div class="ctrl-status ${alive && dp_up ? 'running' : 'idle'}">
          <div class="dot dot-pulse" style="background:${stateColor};width:6px;height:6px"></div>
          ${stateLabel}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0">
        心跳通过 QP_HB 周期性 RDMA SEND 检测；超过 3s 无应答则 <span class="mono" style="color:#ffb020">peer_alive=false</span>，
        后续 PUT 自动跳过跨节点复制、本地成功返回（响应 <span class="mono" style="color:#ffb020">degraded=true</span>），
        避免整个数据平面被失联对端卡住。恢复后自动切回强复制。
      </div>
      <div class="ctrl-row" style="margin-top:10px">
        <button class="btn btn-danger  btn-sm" onclick="haKill()"    ${peerCtl ? '' : 'disabled'}>⚠ 杀死 Peer</button>
        <button class="btn btn-success btn-sm" onclick="haRestore()" ${peerCtl ? '' : 'disabled'}>↻ 恢复 Peer</button>
        <button class="btn btn-primary btn-sm" onclick="haBurst(10)">⚡ 发 10 次 PUT（观察 degraded）</button>
        <button class="btn btn-outline btn-sm" onclick="haRefresh()">刷新状态</button>
      </div>
      ${peerCtlWarn}
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('节点状态', '🛰', stateColor)}
        <div class="card-body">
          <div class="g4">
            ${metric('SELF',        haStatus.self || '-',                     '', '#00d0f0')}
            ${metric('DP_ONLINE',   dp_up ? 'TRUE' : 'FALSE',                 '', dp_up ? '#00e888' : '#ff4050')}
            ${metric('PEER_ALIVE',  alive ? 'TRUE' : 'FALSE',                 '', alive ? '#00e888' : '#ffb020')}
            ${metric('PEER_NUM_QP', haStatus.peer_num_qp ?? 0,                '', '#a060ff')}
          </div>
        </div>
      </div>
      <div class="card">${chead('降级计数器', '📉', '#ffb020')}
        <div class="card-body">
          <div class="g2">
            ${metric('degraded_puts',  degN, '次',  '#ffb020')}
            ${metric('degraded_bytes', (degB / 1024).toFixed(1), 'KB', '#ffb020')}
          </div>
          <div style="margin-top:10px;font-size:1rem;color:#5a7a96;line-height:1.7">
            <b style="color:#c0d8f0">读取方法</b>：每个本地写在 peer 失联期间累加一次 degraded_puts；恢复后不自动清零，方便演示结束后核对发生过多少"只写本地"。
          </div>
        </div>
      </div>
      <div class="card span2">${chead('故障演练时间线', '📜', '#00d0f0', tag('LIVE', '#00e888'))}
        <div class="card-body"><div class="elog">${evH}</div></div>
      </div>
    </div>`;
}

async function haRefresh() {
  try {
    const res = await fetch(`${HA_API}/status`);
    haStatus = await res.json();
  } catch (e) { haStatus = { ok: false, err: e.message }; }
  renderM9();
}

function haStartPolling() {
  if (haPollTimer) return;
  haPollTimer = setInterval(haRefresh, 1500);
}
function haStopPolling() {
  if (haPollTimer) { clearInterval(haPollTimer); haPollTimer = null; }
}

async function haKill() {
  haPushEvent('KILL_PEER', '#ff4050', '发送 pkill 命令到 peer ...');
  renderM9();
  try {
    const res  = await fetch(`${HA_API}/kill_peer`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      haPushEvent('KILL_PEER', '#ff4050',
        `已发送 (rc=${data.ssh && data.ssh.rc}); 预期 3s 后 peer_alive=false`);
    } else {
      haPushEvent('KILL_PEER ✗', '#ff4050', data.err || 'unknown error');
    }
  } catch (e) { haPushEvent('ERR', '#ff4050', `kill failed: ${e.message}`); }
  await haRefresh();
}

async function haRestore() {
  haPushEvent('RESTORE', '#00e888', '启动 peer ...');
  renderM9();
  try {
    const res  = await fetch(`${HA_API}/restore_peer`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      haPushEvent('RESTORE', '#00e888',
        `已发送 (rc=${data.ssh && data.ssh.rc}); 预期 5-8s 后 peer_alive=true`);
    } else {
      haPushEvent('RESTORE ✗', '#ff4050', data.err || 'unknown error');
    }
  } catch (e) { haPushEvent('ERR', '#ff4050', `restore failed: ${e.message}`); }
  await haRefresh();
}

async function haBurst(n) {
  haPushEvent('BURST_PUT', '#00d0f0', `发射 ${n} 次 PUT 观察 degraded 变化...`);
  renderM9();
  let okCnt = 0, degCnt = 0, failCnt = 0;
  for (let i = 0; i < n; ++i) {
    try {
      const res = await fetch(`${KV_API}/put`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ key: `ha_demo_${Date.now()}_${i}`, val: `v${i}` })
      });
      const data = await res.json();
      if (data.ok) {
        okCnt += 1;
        if (data.degraded) degCnt += 1;
      } else failCnt += 1;
    } catch { failCnt += 1; }
  }
  haPushEvent('BURST_PUT', '#00d0f0',
    `完成: ok=${okCnt} degraded=${degCnt} fail=${failCnt}`);
  await haRefresh();
}

// 切页到 m9 时开始轮询；其它模块保持静默
(function _hookHaPolling() {
  const origGoPage = window.goPage;
  window.goPage = function (name, el) {
    origGoPage(name, el);
    if (name === 'm9') { haRefresh(); haStartPolling(); }
    else               { haStopPolling(); }
  };
})();
