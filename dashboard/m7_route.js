// ============================================================
// m7_route.js — 模块⑦：路由 & 负载均衡（一致性哈希演示）
// 调用 Flask `/api/route/query` / `/api/route/scan`
// ============================================================

const ROUTE_API = (window.API_BASE || 'http://localhost:5000') + '/api/route';

let routeItems      = [];       // last scan result
let routeBusy       = false;
let routeSelfIp     = '';
let routeInputKey   = 'demo_42';
let routeInputPrefix = 'demo_';
let routeInputCount  = 40;

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
      <div class="mono" style="color:#e4edf6">${r.key}</div>
      <div style="color:#5a7a96">PRIMARY</div>
      <div class="mono" style="color:${primaryMine ? '#00e888' : '#00d0f0'}">${r.primary} ${primaryMine ? '(本机)' : ''}</div>
      <div style="color:#5a7a96">REPLICA</div>
      <div class="mono" style="color:${r.replica ? '#ffb020' : '#5a7a96'}">${r.replica || '(无副本)'}</div>
      <div style="color:#5a7a96">本机视角</div>
      <div style="color:#c0d8f0">${primaryMine ? '我是 primary，写请求本地生效' : '我不是 primary，请求由对端负责，本机仅持有副本'}</div>
    </div>`;
  })() : '<div style="color:#5a7a96;font-size:1.1rem;padding:18px;text-align:center">输入任意 key 查询它的路由决策</div>';

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
        后端: RPC_ROUTE_QUERY（零 I/O，只计算路由决策）
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
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('单 key 路由决策', '🔍', '#00d0f0')}
        <div class="card-body">${singleCard}</div>
      </div>
      <div class="card">${chead('主副本分布（批量扫描后）', '📊', '#00e888')}
        <div class="card-body">${distH}</div>
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
