// ============================================================
// m8_isolation.js — 模块⑧：租户/任务 内存隔离 ACL 演示
// 调用 Flask /api/iso/*
// ============================================================

const ISO_API = (window.API_BASE || 'http://localhost:5000') + '/api/iso';

let isoBusy       = false;
let isoAllowList  = [];        // strings like "7|default/slab1k"
let isoEvents     = [];        // timeline of ACL / PUT / GET events
let isoInputTid   = 7;
let isoInputPool  = 'default/slab1k';
let isoInputKey   = 'hello';
let isoInputVal   = 'world';

function isoPushEvent(kind, color, text) {
  const now = new Date().toLocaleTimeString();
  isoEvents.unshift({ ts: now, kind, color, text });
  if (isoEvents.length > 40) isoEvents.pop();
}

function renderM8() {
  const el = document.getElementById('pg-m8');
  if (!el) return;

  // ACL 列表
  const aclH = isoAllowList.length === 0
    ? '<div style="color:#5a7a96;padding:16px;text-align:center">ACL 为空；点击"刷新 ACL"或"允许"生成条目</div>'
    : '<div style="display:flex;flex-wrap:wrap;gap:8px">' +
      isoAllowList.map(s => {
        const [tid, pool] = s.split('|');
        const isDefault = (tid === '0');
        const color = isDefault ? '#00e888' : '#00d0f0';
        return `<div style="padding:8px 14px;background:#1b2a3d;border:1px solid ${color}40;border-radius:6px;display:flex;align-items:center;gap:8px">
          <span class="label-rdma" style="background:${color}20;color:${color};border-color:${color}40">T${tid}</span>
          <span class="mono" style="color:#e4edf6">${pool}</span>
          ${isDefault ? '<span style="font-size:1rem;color:#5a7a96">(默认)</span>' : ''}
        </div>`;
      }).join('') + '</div>';

  // 事件流
  const evH = isoEvents.length === 0
    ? '<div style="color:#5a7a96;padding:20px;text-align:center">请在上方控制面板触发 ALLOW / DENY / PUT / GET 操作</div>'
    : isoEvents.map((e, i) => `<div class="eitem ${i === 0 ? 'latest' : ''}">
        <span style="color:#5a7a96">${e.ts}</span>
        <span style="color:${e.color};font-weight:700;min-width:72px;display:inline-block">${e.kind}</span>
        <span style="color:#e4edf6">${e.text}</span>
      </div>`).join('');

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">租户/任务 内存隔离 ACL</div>
        <div class="ctrl-status ${isoBusy ? 'running' : 'idle'}">
          <div class="dot ${isoBusy ? 'dot-pulse' : ''}" style="background:${isoBusy ? '#00e888' : '#5a7a96'};width:6px;height:6px"></div>
          ${isoBusy ? '处理中...' : '就绪'}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0">
        每条 KV_PUT/KV_GET 在入口按 <span class="mono" style="color:#c0d8f0">(tenant_id, pool)</span> 查 ACL；未授权请求立即被拒绝。<br>
        客户端通过 <span class="mono" style="color:#c0d8f0">T&lt;id&gt;:&lt;key&gt;</span> 线格式声明租户；默认 tid=0 已预装授权。
      </div>

      <div class="ctrl-row" style="margin-top:10px">
        <span class="ctrl-label">Tenant</span>
        <input id="iso-tid"  class="ctrl-input" style="width:80px"  value="${isoInputTid}">
        <span class="ctrl-label">Pool</span>
        <input id="iso-pool" class="ctrl-input" style="width:180px" value="${isoInputPool}">
        <button class="btn btn-success btn-sm" onclick="isoAllow()">允许</button>
        <button class="btn btn-danger  btn-sm" onclick="isoDeny()">拒绝</button>
        <button class="btn btn-outline btn-sm" onclick="isoRefresh()">刷新 ACL</button>
      </div>

      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label">KEY</span>
        <input id="iso-key" class="ctrl-input" style="width:120px" value="${isoInputKey}">
        <span class="ctrl-label">VAL</span>
        <input id="iso-val" class="ctrl-input" style="width:180px" value="${isoInputVal}">
        <button class="btn btn-primary btn-sm" onclick="isoTryPut()">尝试 PUT (T${isoInputTid})</button>
        <button class="btn btn-primary btn-sm" onclick="isoTryGet()">尝试 GET (T${isoInputTid})</button>
      </div>
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('当前 ACL 白名单', '🔐', '#00e888', tag(`${isoAllowList.length} 条`, '#00e888'))}
        <div class="card-body">${aclH}</div>
      </div>
      <div class="card">${chead('操作时间线', '📜', '#00d0f0', tag('LIVE', '#00e888'))}
        <div class="card-body"><div class="elog">${evH}</div></div>
      </div>
    </div>`;
}

async function isoRefresh() {
  isoBusy = true; renderM8();
  try {
    const res = await fetch(`${ISO_API}/list`);
    const data = await res.json();
    if (data.ok) isoAllowList = data.allowed || [];
  } catch (e) {
    isoPushEvent('ERR', '#ff4050', `list failed: ${e.message}`);
  }
  isoBusy = false; renderM8();
}

function _isoReadInputs() {
  isoInputTid  = parseInt((document.getElementById('iso-tid')  || {}).value || isoInputTid, 10) || 0;
  isoInputPool = (document.getElementById('iso-pool') || {}).value || isoInputPool;
  isoInputKey  = (document.getElementById('iso-key')  || {}).value || isoInputKey;
  isoInputVal  = (document.getElementById('iso-val')  || {}).value || isoInputVal;
}

async function isoAllow() {
  _isoReadInputs(); isoBusy = true; renderM8();
  try {
    const res = await fetch(`${ISO_API}/allow`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ tenant_id: isoInputTid, pool: isoInputPool })
    });
    const data = await res.json();
    isoPushEvent('ALLOW', '#00e888',
      `T${isoInputTid} on ${isoInputPool} -> ${data.ok ? 'OK' : 'FAIL: ' + (data.err || '?')}`);
  } catch (e) { isoPushEvent('ERR', '#ff4050', `allow failed: ${e.message}`); }
  await isoRefresh();
}

async function isoDeny() {
  _isoReadInputs(); isoBusy = true; renderM8();
  try {
    const res = await fetch(`${ISO_API}/deny`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ tenant_id: isoInputTid, pool: isoInputPool })
    });
    const data = await res.json();
    isoPushEvent('DENY', '#ffb020',
      `T${isoInputTid} on ${isoInputPool} -> ${data.ok ? 'OK' : 'FAIL: ' + (data.err || '?')}`);
  } catch (e) { isoPushEvent('ERR', '#ff4050', `deny failed: ${e.message}`); }
  await isoRefresh();
}

async function isoTryPut() {
  _isoReadInputs(); isoBusy = true; renderM8();
  try {
    const res = await fetch(`${ISO_API}/kv_put`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ tenant_id: isoInputTid, key: isoInputKey, val: isoInputVal })
    });
    const data = await res.json();
    if (data.ok) {
      isoPushEvent('PUT ✓', '#00d0f0',
        `T${isoInputTid}:${isoInputKey}=${isoInputVal}  size=${data.size} off=${data.offset}`);
    } else {
      isoPushEvent('PUT ✗', '#ff4050',
        `T${isoInputTid}:${isoInputKey}  err: ${data.err}`);
    }
  } catch (e) { isoPushEvent('ERR', '#ff4050', `put failed: ${e.message}`); }
  isoBusy = false; renderM8();
}

async function isoTryGet() {
  _isoReadInputs(); isoBusy = true; renderM8();
  try {
    const res = await fetch(`${ISO_API}/kv_get?tenant_id=${isoInputTid}&key=${encodeURIComponent(isoInputKey)}`);
    const data = await res.json();
    if (data.ok) {
      isoPushEvent('GET ✓', '#00e888',
        `T${isoInputTid}:${isoInputKey} -> "${data.val}"  hit=${data.hit}`);
    } else {
      isoPushEvent('GET ✗', '#ff4050',
        `T${isoInputTid}:${isoInputKey}  err: ${data.err}`);
    }
  } catch (e) { isoPushEvent('ERR', '#ff4050', `get failed: ${e.message}`); }
  isoBusy = false; renderM8();
}
