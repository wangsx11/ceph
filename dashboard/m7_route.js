// ============================================================
// m7_route.js — 模块⑦：路由 & 负载均衡（一致性哈希演示）
// 调用 Flask `/api/route/query` / `/api/route/scan` / `/api/route/put`
// ============================================================

const ROUTE_API = (window.API_BASE || location.origin) + '/api/route';

let routeItems      = [];       // last scan result
let routeBusy       = false;
let routeSelfIp     = '';
let routeInputKey   = 'demo_42';
let routeInputPrefix = 'demo_';
let routeInputCount  = 40;
let routePutValue    = 'route-rdma-payload';

function routeEsc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function routeBool(v) {
  return v ? '<span class="label-store">true</span>' : '<span style="color:#5a7a96">false</span>';
}

function renderM7() {
  const el = document.getElementById('pg-m7');
  if (!el) return;

  // 按 primary 分组统计分布
  const byNode = {};
  for (const it of routeItems) {
    if (!it.ok) continue;
    const p = it.primary || '(unassigned)';
    byNode[p] = (byNode[p] || 0) + 1;
  }
  const total = routeItems.length || 1;
  const distH = Object.keys(byNode).length === 0
    ? '<div style="color:#5a7a96;font-size:1.1rem;padding:18px;text-align:center">暂无扫描数据，点击"扫描路由"生成分布</div>'
    : '<div class="g3">' + Object.entries(byNode).map(([node, n]) => {
        const isSelf = (node === routeSelfIp);
        const color = isSelf ? '#00e888' : '#00d0f0';
        return `<div style="padding:16px;background:#1b2a3d;border-radius:8px;border:1px solid ${color}30">
          <div style="font-size:1rem;color:#5a7a96">节点</div>
          <div class="mono" style="font-size:1.5rem;color:${color};margin:4px 0">${node}${isSelf ? ' (本机)' : ''}</div>
          <div style="display:flex;align-items:baseline;gap:8px">
            <div class="mono" style="font-size:2.4rem;color:${color};font-weight:700">${n}</div>
            <div style="color:#7a95b0">/ ${total}</div>
          </div>
          <div style="margin-top:6px">${prog(n, total, color)}</div>
        </div>`;
      }).join('') + '</div>';

  // 单 key 结果卡
  const singleCard = window._routeSingle ? (() => {
    const r = window._routeSingle;
    if (!r.ok) {
      return `<div style="color:#ff4050;font-size:1.2rem;padding:10px">查询失败: ${r.err || '(未知)'}</div>`;
    }
    const primaryMine = r.local_is_primary;
    return `<div style="display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:1.2rem">
      <div style="color:#5a7a96">KEY</div>
      <div class="mono" style="color:#e4edf6">${routeEsc(r.key)}</div>
      <div style="color:#5a7a96">PRIMARY</div>
      <div class="mono" style="color:${primaryMine ? '#00e888' : '#00d0f0'}">${routeEsc(r.primary)} ${primaryMine ? '(本机)' : ''}</div>
      <div style="color:#5a7a96">REPLICA</div>
      <div class="mono" style="color:${r.replica ? '#ffb020' : '#5a7a96'}">${routeEsc(r.replica || '(无副本)')}</div>
      <div style="color:#5a7a96">本机视角</div>
      <div style="color:#c0d8f0">${primaryMine ? '我是 primary，routed PUT 本地写入' : '远端 primary，routed PUT 通过 RDMA WRITE 转发到 peer slab'}</div>
    </div>`;
  })() : '<div style="color:#5a7a96;font-size:1.1rem;padding:18px;text-align:center">输入任意 key 查询它的路由决策</div>';

  const routeWriteCard = window._routePut ? (() => {
    const r = window._routePut;
    const p = r.put || {};
    const rb = r.readback || {};
    if (!r.ok) {
      return `<div style="color:#ff4050;font-size:1.2rem;padding:10px">写入失败: ${routeEsc(p.err || r.err || '(未知)')}</div>`;
    }
    const transport = p.forward_transport || r.write_transport || '-';
    const transportColor = transport === 'rdma' ? '#00e888' : (transport === 'local' ? '#00d0f0' : '#ffb020');
    return `<div style="display:grid;grid-template-columns:auto 1fr auto 1fr;gap:8px 16px;font-size:1.1rem">
      <div style="color:#5a7a96">KEY</div>
      <div class="mono" style="color:#e4edf6">${routeEsc(r.key)}</div>
      <div style="color:#5a7a96">写入路径</div>
      <div class="mono" style="color:${transportColor}">${routeEsc(transport)}</div>
      <div style="color:#5a7a96">route_forwarded</div>
      <div>${routeBool(p.route_forwarded)}</div>
      <div style="color:#5a7a96">degraded</div>
      <div>${routeBool(p.degraded)}</div>
      <div style="color:#5a7a96">offset</div>
      <div class="mono" style="color:#c0d8f0">${routeEsc(p.offset ?? '-')}</div>
      <div style="color:#5a7a96">qp_idx</div>
      <div class="mono" style="color:#c0d8f0">${routeEsc(p.qp_idx ?? '-')}</div>
      <div style="color:#5a7a96">读回校验</div>
      <div>${routeBool(rb.ok)}</div>
      <div style="color:#5a7a96">value</div>
      <div class="mono" style="color:#c0d8f0">${routeEsc(rb.val || r.value || '')}</div>
    </div>`;
  })() : '<div style="color:#5a7a96;font-size:1.1rem;padding:18px;text-align:center">点击"RDMA 远端写入"执行 routed PUT</div>';

  // 扫描结果表
  const tableRows = routeItems.slice(0, 60).map(it => {
    if (!it.ok) return `<tr><td colspan="4" style="color:#ff4050">${it.key}</td></tr>`;
    return `<tr>
      <td class="mono" style="color:#e4edf6">${it.key}</td>
      <td class="mono" style="color:${it.local_is_primary ? '#00e888' : '#00d0f0'}">${it.primary}</td>
      <td class="mono" style="color:${it.replica ? '#ffb020' : '#5a7a96'}">${it.replica || '-'}</td>
      <td>${it.local_is_primary ? '<span class="label-store">本机主</span>' : ''}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">路由 & 负载均衡（一致性哈希）</div>
        <div class="ctrl-status ${routeBusy ? 'running' : 'idle'}">
          <div class="dot ${routeBusy ? 'dot-pulse' : ''}" style="background:${routeBusy ? '#00e888' : '#5a7a96'};width:6px;height:6px"></div>
          ${routeBusy ? '查询中...' : '就绪'}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin:6px 0">
        数据平面用 160 vnode 一致性哈希环将对象 key 映射到具体节点，副本通过 <span class="mono" style="color:#c0d8f0">key + "$r"</span> 二次哈希选定。<br>
        后端: RPC_ROUTE_QUERY / RPC_ROUTE_PUT；远端 primary 写入返回 <span class="mono" style="color:#00e888">forward_transport=rdma</span>
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label">单 key</span>
        <input id="route-key" class="ctrl-input" style="width:180px" value="${routeInputKey}">
        <button class="btn btn-primary btn-sm" onclick="routeQueryOne()">查询路由</button>
        <span style="width:14px"></span>
        <span class="ctrl-label">批量前缀</span>
        <input id="route-prefix" class="ctrl-input" style="width:120px" value="${routeInputPrefix}">
        <span class="ctrl-label">数量</span>
        <input id="route-count" class="ctrl-input" style="width:70px" value="${routeInputCount}">
        <button class="btn btn-success btn-sm" onclick="routeScan()">扫描路由</button>
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label">写入值</span>
        <input id="route-value" class="ctrl-input" style="width:220px" value="${routePutValue}">
        <button class="btn btn-success btn-sm" onclick="routePutRemote()">RDMA 远端写入</button>
      </div>
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('单 key 路由决策', '🔍', '#00d0f0')}
        <div class="card-body">${singleCard}</div>
      </div>
      <div class="card">${chead('主副本分布（批量扫描后）', '📊', '#00e888')}
        <div class="card-body">${distH}</div>
      </div>
      <div class="card span2">${chead('Routed PUT RDMA 写入结果', '⚡', '#00e888')}
        <div class="card-body">${routeWriteCard}</div>
      </div>
      <div class="card span2">${chead('批量扫描明细', '📋', '#ffb020', tag(`${routeItems.length} keys`, '#ffb020'))}
        <div class="card-body">
          <table class="dtable">
            <thead><tr><th>KEY</th><th>PRIMARY</th><th>REPLICA</th><th></th></tr></thead>
            <tbody>${tableRows || '<tr><td colspan="4" style="color:#5a7a96;text-align:center;padding:20px">先点上方"扫描路由"生成数据</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

async function routePutRemote() {
  const k = (document.getElementById('route-key') || {}).value || routeInputKey;
  const v = (document.getElementById('route-value') || {}).value || routePutValue;
  routeInputKey = k;
  routePutValue = v;
  routeBusy = true; renderM7();
  try {
    const res = await fetch(`${ROUTE_API}/put`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key: k,
        value: v,
        prefix: routeInputPrefix,
        prefer_remote: true
      })
    });
    const data = await res.json();
    window._routePut = data;
    if (data.key) routeInputKey = data.key;
    if (data.route) window._routeSingle = data.route;
    routeSelfIp = data.self || routeSelfIp;
  } catch (e) {
    window._routePut = { ok: false, err: e.message, put: { err: e.message } };
  }
  routeBusy = false; renderM7();
}

async function routeQueryOne() {
  const k = (document.getElementById('route-key') || {}).value || routeInputKey;
  routeInputKey = k;
  routeBusy = true; renderM7();
  try {
    const res = await fetch(`${ROUTE_API}/query?key=${encodeURIComponent(k)}`);
    window._routeSingle = await res.json();
    routeSelfIp = window._routeSingle.self || routeSelfIp;
  } catch (e) {
    window._routeSingle = { ok: false, err: e.message };
  }
  routeBusy = false; renderM7();
}

async function routeScan() {
  const pref = (document.getElementById('route-prefix') || {}).value || routeInputPrefix;
  const cnt  = parseInt((document.getElementById('route-count') || {}).value || routeInputCount, 10) || 40;
  routeInputPrefix = pref; routeInputCount = cnt;
  routeBusy = true; renderM7();
  try {
    const res = await fetch(`${ROUTE_API}/scan?prefix=${encodeURIComponent(pref)}&count=${cnt}`);
    const data = await res.json();
    if (data.ok) {
      routeItems  = data.items || [];
      routeSelfIp = data.self || routeSelfIp;
    }
  } catch (e) {
    console.error('[M7] scan error:', e);
  }
  routeBusy = false; renderM7();
}
