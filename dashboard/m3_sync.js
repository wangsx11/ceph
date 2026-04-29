// ============================================================
// m3_sync.js — §3 跨节点对象读写 & 数据同步（重写版）
//
// 设计：
//   · 只打本端 Flask；对端数据走 /api/peer/* 反向代理 → 零 CORS
//   · 页面分三区：节点概览 / 并排双面板 / 同步事件时间线
//   · 自动轮询 1s；用户发起的写/改/删/读操作立即触发两端刷新
//   · 延迟、命中层级、复制耗时等指标直接展示，满足 §3c 可观测性
// ============================================================

const D3_API_SELF = (window.API_BASE || location.origin) + '/api/demo3';
const D3_API_PEER = (window.API_BASE || location.origin) + '/api/peer/demo3';

const D3_STATE = {
  cluster: { A: null, B: null },
  objects: { A: [], B: [] },
  events:  [],           // 最近 50 条同步事件
  latestUid: null,       // 仅本轮新增事件的 uid；轮询 refresh 不变
  uidSeq:  0,            // 事件 uid 自增
  poll:    null,         // setInterval id
  form:    { name: 'unit_alpha_01', data: '{"kind":"侦察情报","unit":"A-01","ts":""}' },
  selected: null,        // 被选中查看详情的对象 name
  mode:    'panels',     // 'panels' | 'detail'
  busy:    false,
};

function d3ApiFor(node) { return node === 'A' ? D3_API_SELF : D3_API_PEER; }

// ------------------------------------------------------------
// 页面主渲染
// ------------------------------------------------------------
function renderM3() {
  const el = document.getElementById('pg-m3');
  if (!el) return;

  const cA = D3_STATE.cluster.A, cB = D3_STATE.cluster.B;
  const peerBadge = (c) => {
    if (!c)           return tag('离线', '#ff4050');
    if (!c.dp_online) return tag('DP 离线', '#ff4050');
    if (!c.rdma_connected) return tag('RDMA 未连接', '#ffb020');
    return tag('RDMA ✓', '#00e888');
  };
  const lagNum = (c) => c ? F(c.replica_lag_us || 0, 1) : '-';

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">③ 跨节点对象读写 & 数据同步（RDMA）</div>
        <div class="ctrl-status ${cA && cA.rdma_connected ? 'running' : 'idle'}">
          <div class="dot dot-pulse" style="background:${cA && cA.rdma_connected ? '#00e888' : '#ff4050'};width:6px;height:6px"></div>
          ${cA && cA.rdma_connected ? '双节点在线' : '等待节点就绪'}
        </div>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:8px">
        ◆ 本地 Flask 通过 UDS 把 PUT / GET 直投数据平面；写入由 RDMA 同步复制到对端节点<br>
        ◆ 每次操作展示：<span style="color:#c0d8f0">延迟(μs)</span> · <span style="color:#c0d8f0">命中层级</span>(local/remote/nvme/hdd) · <span style="color:#c0d8f0">replica_lag</span>
      </div>
      <div class="g2" style="gap:10px">
        ${d3RenderNodeStatCard('A', cA)}
        ${d3RenderNodeStatCard('B', cB)}
      </div>
    </div>

    <div class="ctrl-panel" style="margin-top:12px">
      <div style="font-size:1.2rem;font-weight:700;color:#c0d8f0;margin-bottom:8px">共享对象操作</div>
      <div class="ctrl-row">
        <span class="ctrl-label">对象名</span>
        <input id="d3-name" class="ctrl-input" style="width:200px" value="${escAttr(D3_STATE.form.name)}">
        <span class="ctrl-label">数据</span>
        <input id="d3-data" class="ctrl-input" style="width:420px" value="${escAttr(D3_STATE.form.data)}">
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label" style="color:#00e888">节点 A</span>
        <button class="btn btn-success btn-sm" onclick="d3Op('A','write')"  ${D3_STATE.busy?'disabled':''}>写入</button>
        <button class="btn btn-warning btn-sm" onclick="d3Op('A','modify')" ${D3_STATE.busy?'disabled':''}>修改</button>
        <button class="btn btn-outline btn-sm" onclick="d3Op('A','read')"   ${D3_STATE.busy?'disabled':''}>读取</button>
        <button class="btn btn-danger  btn-sm" onclick="d3Op('A','delete')" ${D3_STATE.busy?'disabled':''}>删除</button>
        <span style="width:18px"></span>
        <span class="ctrl-label" style="color:#00d0f0">节点 B</span>
        <button class="btn btn-success btn-sm" onclick="d3Op('B','write')"  ${D3_STATE.busy?'disabled':''}>写入</button>
        <button class="btn btn-warning btn-sm" onclick="d3Op('B','modify')" ${D3_STATE.busy?'disabled':''}>修改</button>
        <button class="btn btn-outline btn-sm" onclick="d3Op('B','read')"   ${D3_STATE.busy?'disabled':''}>读取</button>
        <button class="btn btn-danger  btn-sm" onclick="d3Op('B','delete')" ${D3_STATE.busy?'disabled':''}>删除</button>
        <div style="flex:1"></div>
        <button class="btn btn-outline btn-sm" onclick="d3FlushAll()">↻ 清空两端</button>
      </div>
      <div style="font-size:1rem;color:#5a7a96;margin-top:6px">
        提示：先在节点 A 写入，观察 B 面板自动同步出现同一对象；在 B 读取命中层级应为 <span class="mono" style="color:#00e888">local</span>（RDMA 复制已到）。
      </div>
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card">${chead('节点 A 对象列表', '🅰', '#00e888',
        tag(`${D3_STATE.objects.A.length} 对象`, '#00e888'))}
        <div class="card-body">${d3RenderObjTable('A')}</div>
      </div>
      <div class="card">${chead('节点 B 对象列表', '🅱', '#00d0f0',
        tag(`${D3_STATE.objects.B.length} 对象`, '#00d0f0'))}
        <div class="card-body">${d3RenderObjTable('B')}</div>
      </div>
    </div>

    <div class="card" style="margin-top:14px">${chead('同步事件时间线', '📜', '#a060ff', tag('LIVE', '#00e888'))}
      <div class="card-body"><div class="elog" style="max-height:300px">${d3RenderEvents()}</div></div>
    </div>`;
}

function d3RenderNodeStatCard(node, c) {
  const color = node === 'A' ? '#00e888' : '#00d0f0';
  if (!c) {
    return `<div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid ${color}30">
      <div style="display:flex;align-items:center;gap:8px">
        ${dot('offline')}
        <div style="font-size:1.3rem;color:${color};font-weight:700">节点 ${node}</div>
        <div style="color:#5a7a96;margin-left:auto">加载中...</div>
      </div>
    </div>`;
  }
  const peer = node === 'A' ? 'B' : 'A';
  return `<div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid ${color}30">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      ${dot(c.rdma_connected ? 'online' : 'warning')}
      <div style="font-size:1.3rem;color:${color};font-weight:700">节点 ${node}</div>
      <div style="color:#5a7a96">${c.self_ip || '-'}</div>
      <div style="margin-left:auto;display:flex;gap:6px">
        ${(c.dp_online)
            ? tag('DP ✓', '#00e888')
            : tag('DP 离线', '#ff4050')}
        ${(c.rdma_connected)
            ? tag(`→ ${peer} RDMA`, '#00d0f0')
            : tag(`→ ${peer} 未连`, '#ffb020')}
      </div>
    </div>
    <div class="g4" style="gap:8px">
      ${metric('本端对象',  c.objects_here,                    '',  color)}
      ${metric('replica lag', F(c.replica_lag_us || 0, 1),     'μs', '#ffb020')}
      ${metric('bw_tx',     F((c.metrics && c.metrics.bw_tx_gbps) || 0, 2), 'Gbps', '#00d0f0')}
      ${metric('QPs',       c.peer_num_qp,                     '',  '#a060ff')}
    </div>
  </div>`;
}

function d3RenderObjTable(node) {
  const list = D3_STATE.objects[node] || [];
  if (list.length === 0) {
    return `<div style="color:#5a7a96;text-align:center;padding:20px;font-size:1.1rem">
      该节点尚无对象；先点击上方【写入】即可同步观察</div>`;
  }
  const color = node === 'A' ? '#00e888' : '#00d0f0';
  const rows = list.slice(0, 12).map(o => {
    const hit = o.last_hit || '-';
    const hitColor = hit === 'local' ? '#00e888'
                   : hit === 'remote'? '#ffb020'
                   : hit === 'nvme'  ? '#4488ff'
                   : hit === 'hdd'   ? '#a060ff' : '#5a7a96';
    return `<tr onclick="d3ShowDetail('${node}','${escAttr(o.name)}')" style="cursor:pointer">
      <td class="mono" style="color:${color}">${esc(o.name)}</td>
      <td class="mono" style="color:#c0d8f0">v${o.version}</td>
      <td class="mono" style="color:#ffb020">${o.size}B</td>
      <td class="mono" style="color:#5a7a96">${o.hash}</td>
      <td class="mono" style="color:${hitColor}">${hit}</td>
      <td class="mono" style="color:#5a7a96">${o.ts}</td>
    </tr>`;
  }).join('');
  return `<table class="dtable">
    <thead><tr><th>NAME</th><th>VER</th><th>SIZE</th><th>HASH</th><th>LAST HIT</th><th>TS</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function d3RenderEvents() {
  if (D3_STATE.events.length === 0) {
    return `<div style="color:#5a7a96;text-align:center;padding:20px;font-size:1.1rem">
      尚无操作；请在上方发起写/改/读/删触发实时事件</div>`;
  }
  return D3_STATE.events.map((e) => {
    const isLatest = e.uid === D3_STATE.latestUid;
    return `<div class="eitem ${isLatest?'latest':''}">
    <span style="color:#5a7a96">${e.ts}</span>
    <span style="color:${e.color};font-weight:700;min-width:60px;display:inline-block">${e.op}</span>
    <span style="color:${e.nodeColor}">${e.node}</span>
    <span style="color:#e4edf6">${esc(e.name)}</span>
    <span style="color:#5a7a96">${e.detail || ''}</span>
    ${e.lat!=null ? `<span style="color:#ffb020">延迟 ${e.lat}μs</span>` : ''}
    ${e.hit ? `<span style="color:#00d0f0">hit=${e.hit}</span>` : ''}
    ${e.err ? `<span style="color:#ff4050">err: ${esc(e.err)}</span>` : ''}
  </div>`;
  }).join('');
}

// ------------------------------------------------------------
// 操作
// ------------------------------------------------------------
async function d3Op(node, op) {
  const nameEl = document.getElementById('d3-name');
  const dataEl = document.getElementById('d3-data');
  const name = (nameEl && nameEl.value || '').trim() || 'demo_obj';
  const data = (dataEl && dataEl.value) || '';
  D3_STATE.form = { name, data };
  D3_STATE.busy = true; renderM3();

  const api = d3ApiFor(node);
  const nodeColor = node === 'A' ? '#00e888' : '#00d0f0';
  try {
    let url, init;
    if (op === 'read') {
      url = `${api}/read?name=${encodeURIComponent(name)}`;
      init = { method: 'GET' };
    } else if (op === 'delete') {
      url = `${api}/delete`;
      init = { method: 'POST', headers: {'Content-Type':'application/json'},
               body: JSON.stringify({ name }) };
    } else {
      url = `${api}/${op}`;
      init = { method: 'POST', headers: {'Content-Type':'application/json'},
               body: JSON.stringify({ name, data }) };
    }
    const res = await fetch(url, init);
    const j = await res.json();
    d3PushEvent({
      ts:        j.ts || TS(),
      op:        op.toUpperCase(),
      color:     ({ write:'#00e888', modify:'#ffb020',
                    read:'#00d0f0',  delete:'#ff4050' })[op] || '#c0d8f0',
      node:      `节点${node}`,
      nodeColor, name,
      detail:    j.ok
        ? (op === 'read' ? `size=${j.size} data="${shrink(j.data)}"`
                         : `size=${j.size||'-'} ver=v${j.version||'-'} hash=${j.hash||'-'}`)
        : '',
      lat:       j.latency_us != null ? j.latency_us : null,
      hit:       j.hit || null,
      err:       j.ok ? null : (j.error || 'failed'),
    });
  } catch (e) {
    d3PushEvent({
      ts: TS(), op: op.toUpperCase(), color:'#ff4050',
      node:`节点${node}`, nodeColor, name, err: e.message,
    });
  }
  D3_STATE.busy = false;
  await d3Refresh();
}

async function d3FlushAll() {
  if (!confirm('确定清空两端的所有对象吗？（会调用 RPC_ADMIN_FLUSH）')) return;
  D3_STATE.busy = true; renderM3();
  try {
    await Promise.all([
      fetch(`${D3_API_SELF}/flush`, { method:'POST' }),
      fetch(`${D3_API_PEER}/flush`, { method:'POST' }),
    ]);
    d3PushEvent({ ts: TS(), op:'FLUSH', color:'#ff4050',
                  node:'两端', nodeColor:'#c0d8f0', name:'*',
                  detail:'ADMIN_FLUSH 已发送' });
  } catch (e) {
    d3PushEvent({ ts: TS(), op:'FLUSH', color:'#ff4050',
                  node:'两端', nodeColor:'#c0d8f0', name:'*',
                  err: e.message });
  }
  D3_STATE.busy = false;
  await d3Refresh();
}

function d3ShowDetail(node, name) {
  D3_STATE.selected = { node, name };
  // 触发一次读取以刷新 last_hit，再提示
  d3Op(node, 'read');
}

function d3PushEvent(ev) {
  ev.uid = ++D3_STATE.uidSeq;
  D3_STATE.latestUid = ev.uid;
  D3_STATE.events.unshift(ev);
  if (D3_STATE.events.length > 50) D3_STATE.events.pop();
}

// ------------------------------------------------------------
// 轮询 & 初始化
// ------------------------------------------------------------
async function d3Refresh() {
  try {
    const [ca, oa, cb, ob] = await Promise.all([
      fetch(`${D3_API_SELF}/cluster`).then(r => r.json()),
      fetch(`${D3_API_SELF}/objects`).then(r => r.json()),
      fetch(`${D3_API_PEER}/cluster`).then(r => r.json()),
      fetch(`${D3_API_PEER}/objects`).then(r => r.json()),
    ]);
    D3_STATE.cluster.A = ca.ok ? ca : null;
    D3_STATE.cluster.B = cb.ok ? cb : null;
    D3_STATE.objects.A = (oa.ok && oa.objects) || [];
    D3_STATE.objects.B = (ob.ok && ob.objects) || [];
  } catch (e) {
    console.warn('[demo3] refresh error', e);
  }
  renderM3();
}

function d3StartPoll() {
  if (D3_STATE.poll) return;
  D3_STATE.poll = setInterval(d3Refresh, 1500);
}
function d3StopPoll() {
  if (D3_STATE.poll) { clearInterval(D3_STATE.poll); D3_STATE.poll = null; }
}

// 首次加载即拉一次
(function _initM3() {
  const prev = window.goPage;
  window.goPage = function (name, el) {
    prev(name, el);
    if (name === 'm3') { d3Refresh(); d3StartPoll(); }
    else                { d3StopPoll(); }
  };
  // 页面首次加载时 m3 是默认激活的，启动轮询
  setTimeout(() => { d3Refresh(); d3StartPoll(); }, 100);
})();

// ------------------------------------------------------------
// 小工具
// ------------------------------------------------------------
function esc(s)     { return String(s==null?'':s).replace(/[<>&"']/g, c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(s) { return esc(s).replace(/\n/g, ' '); }
function shrink(s)  { s = String(s||''); return s.length > 48 ? s.slice(0, 45) + '...' : s; }
