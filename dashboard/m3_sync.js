// ============================================================
// m3_sync.js — §3 跨节点对象读写 & 数据同步（重写版）
//
// 设计：
//   · 页面通过 /api/demo3 和 /api/peer/demo3 操作 A/B 两端
//   · 页面分三区：节点概览 / 并排双节点面板 / 同步事件时间线
//   · 自动轮询 1s；用户发起的写/改/删/读操作立即触发两端刷新
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
  // A/B 各自一套表单状态
  forms: {
    A: { name: 'unit_alpha_01', data: '{"kind":"侦察情报","unit":"A-01","ts":""}' },
    B: { name: 'unit_alpha_01', data: '{"kind":"侦察情报","unit":"A-01","ts":""}' },
  },
  detail:   null,        // {node, name, loading, data, editData, meta, error}
  busy:    false,
};

function d3ApiFor(node) { return node === 'A' ? D3_API_SELF : D3_API_PEER; }

// ------------------------------------------------------------
// 页面主渲染（只建骨架；后续更新走 d3UpdateXxx 小函数，保证事件列表的 DOM 稳定）
// ------------------------------------------------------------
function renderM3() {
  const el = document.getElementById('pg-m3');
  if (!el) return;

  const cA = D3_STATE.cluster.A, cB = D3_STATE.cluster.B;

  el.innerHTML = `
    <div class="ctrl-panel">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0">③ 跨节点对象读写 & 数据同步（RDMA）</div>
        <div id="d3-status" class="ctrl-status idle">
          <div class="dot" style="background:#5a7a96;width:6px;height:6px"></div>等待就绪
        </div>
      </div>
      <div id="d3-cluster-summary">${d3RenderClusterSummary(cA, cB)}</div>
    </div>

    <div class="ctrl-panel" style="margin-top:12px">
      <div style="font-size:1.2rem;font-weight:700;color:#c0d8f0;margin-bottom:8px">对象操作</div>
      <div class="g2" style="gap:10px">
        ${d3RenderOpPanel('A')}
        ${d3RenderOpPanel('B')}
      </div>
    </div>

    <div class="g2" style="margin-top:14px">
      <div class="card"><div id="d3-head-A">${chead('节点 A 对象列表', '🅰', '#00e888', tag(`0 对象`, '#00e888'))}</div>
        <div class="card-body"><div id="d3-list-A">${d3RenderObjTable('A')}</div></div>
      </div>
      <div class="card"><div id="d3-head-B">${chead('节点 B 对象列表', '🅱', '#00d0f0', tag(`0 对象`, '#00d0f0'))}</div>
        <div class="card-body"><div id="d3-list-B">${d3RenderObjTable('B')}</div></div>
      </div>
    </div>

    <div id="d3-detail" style="margin-top:14px">${d3RenderDetail()}</div>

    <div class="card" style="margin-top:14px">${chead('同步事件时间线', '📜', '#a060ff', tag('LIVE', '#00e888'))}
      <div class="card-body"><div id="d3-events" class="elog" style="max-height:300px">${d3RenderEventsInitial()}</div></div>
    </div>`;
}

// 首次进入页面时列出已有事件（通常为空）
function d3RenderEventsInitial() {
  if (D3_STATE.events.length === 0) {
    return `<div id="d3-events-empty" style="color:#5a7a96;text-align:center;padding:20px;font-size:1.1rem">
      尚无操作；请在上方发起写/改/读/删触发实时事件</div>`;
  }
  return D3_STATE.events.map(e => d3EventHTML(e, false)).join('');
}

function d3EventHTML(e, withLatest) {
  return `<div class="eitem${withLatest?' latest':''}" data-uid="${e.uid}">
    <span style="color:#5a7a96">${e.ts}</span>
    <span style="color:${e.color};font-weight:700;min-width:60px;display:inline-block">${e.op}</span>
    <span style="color:${e.nodeColor}">${e.node}</span>
    <span style="color:#e4edf6">${esc(e.name)}</span>
    <span style="color:#5a7a96">${e.detail || ''}</span>
    ${e.lat!=null ? `<span style="color:#ffb020">${e.latLabel || '延迟'} ${e.lat}μs</span>` : ''}
    ${e.hit ? `<span style="color:#00d0f0">hit=${e.hit}</span>` : ''}
    ${e.err ? `<span style="color:#ff4050">err: ${esc(e.err)}</span>` : ''}
  </div>`;
}

// ------------------------------------------------------------
// A/B 各自的操作面板
// ------------------------------------------------------------
function d3RenderOpPanel(node) {
  const color     = node === 'A' ? '#00e888' : '#00d0f0';
  const peerColor = node === 'A' ? '#00d0f0' : '#00e888';
  const f         = D3_STATE.forms[node];
  return `<div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid ${color}40">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};box-shadow:0 0 6px ${color}88"></span>
      <div style="font-size:1.2rem;font-weight:700;color:${color}">节点 ${node}</div>
      <div style="color:#5a7a96;font-size:0.95rem">数据平面 ${node}</div>
    </div>
    <div class="ctrl-row" style="margin-bottom:6px">
      <span class="ctrl-label" style="min-width:48px">对象名</span>
      <input id="d3-name-${node}" class="ctrl-input" style="flex:1;min-width:0"
             value="${escAttr(f.name)}"
             oninput="D3_STATE.forms['${node}'].name=this.value">
    </div>
    <div class="ctrl-row" style="margin-bottom:8px">
      <span class="ctrl-label" style="min-width:48px">数据</span>
      <input id="d3-data-${node}" class="ctrl-input" style="flex:1;min-width:0"
             value="${escAttr(f.data)}"
             oninput="D3_STATE.forms['${node}'].data=this.value">
    </div>
    <div class="ctrl-row" style="gap:6px">
      <button class="btn btn-success btn-sm" onclick="d3Op('${node}','write')">写入</button>
      <button class="btn btn-outline btn-sm" onclick="d3Op('${node}','read')">读取</button>
    </div>
  </div>`;
}

function d3NodeOnline(c) {
  return !!(c && c.ok && c.dp_online);
}

function d3RenderClusterSummary(cA, cB) {
  const aOn = d3NodeOnline(cA);
  const bOn = d3NodeOnline(cB);
  const online = (aOn ? 1 : 0) + (bOn ? 1 : 0);
  return `<div class="g3" style="gap:10px">
    ${d3RenderNodeStatCard('A', cA)}
    ${d3RenderNodeStatCard('B', cB)}
    <div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid #2d4a6630">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        ${dot(online === 2 ? 'online' : 'warning')}
        <div style="font-size:1.3rem;color:#c0d8f0;font-weight:700">节点数量</div>
      </div>
      ${metric('在线 / 总数', `${online} / 2`, '', online === 2 ? '#00e888' : '#ffb020')}
    </div>
  </div>`;
}

function d3RenderNodeStatCard(node, c) {
  const color = node === 'A' ? '#00e888' : '#00d0f0';
  const online = d3NodeOnline(c);
  if (!c) {
    return `<div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid ${color}30">
      <div style="display:flex;align-items:center;gap:8px">
        ${dot('offline')}
        <div style="font-size:1.3rem;color:${color};font-weight:700">节点 ${node}</div>
        <div style="color:#5a7a96;margin-left:auto">加载中...</div>
      </div>
    </div>`;
  }
  return `<div style="padding:12px;background:#1b2a3d;border-radius:6px;border:1px solid ${color}30">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      ${dot(online ? 'online' : 'warning')}
      <div style="font-size:1.3rem;color:${color};font-weight:700">节点 ${node}</div>
      <div style="margin-left:auto">${tag(online ? '在线' : '离线', online ? '#00e888' : '#ff4050')}</div>
    </div>
    ${metric('节点状态', online ? 'ONLINE' : 'OFFLINE', '', online ? color : '#ff4050')}
  </div>`;
}

function d3RenderObjTable(node) {
  const list = D3_STATE.objects[node] || [];
  if (list.length === 0) {
    return `<div style="color:#5a7a96;text-align:center;padding:20px;font-size:1.1rem">
      该节点尚无对象；先点击上方【写入】即可同步观察</div>`;
  }
  const color = node === 'A' ? '#00e888' : '#00d0f0';
  const rows = list.map(o => {
    const hit = o.last_hit || '-';
    const hitColor = hit === 'local' ? '#00e888'
                   : hit === 'remote'? '#ffb020'
                   : hit === 'nvme'  ? '#4488ff'
                   : hit === 'hdd'   ? '#a060ff' : '#5a7a96';
    const selected = D3_STATE.detail &&
      D3_STATE.detail.node === node && D3_STATE.detail.name === o.name;
    return `<tr data-node="${escAttr(node)}" data-name="${escAttr(o.name)}" onclick="d3RowClick(event)"
      style="cursor:pointer;${selected ? 'background:#00e0ff10' : ''}">
      <td class="mono" style="color:${color}">${esc(o.name)}</td>
      <td class="mono" style="color:#c0d8f0">v${o.version}</td>
      <td class="mono" style="color:#ffb020">${o.size}B</td>
      <td class="mono" style="color:${hitColor}">${hit}</td>
      <td class="mono" style="color:#5a7a96">${o.ts}</td>
    </tr>`;
  }).join('');
  return `<table class="dtable">
    <thead><tr><th>NAME</th><th>VER</th><th>SIZE</th><th>LAST HIT</th><th>TS</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function d3RenderDetail() {
  const d = D3_STATE.detail;
  if (!d) return '';
  const color = d.node === 'A' ? '#00e888' : '#00d0f0';
  if (d.loading) {
    return `<div class="d3-popover card" id="d3-detail-panel">${chead('对象详情', '✎', color, tag('加载中', '#ffb020'))}
      <div class="card-body" style="color:#5a7a96">正在读取 ${esc(d.name)} ...</div>
    </div>`;
  }
  if (d.error) {
    return `<div class="d3-popover card" id="d3-detail-panel">${chead('对象详情', '✎', color, tag('读取失败', '#ff4050'))}
      <div class="card-body">
        <div style="color:#ff9aa3">${esc(d.error)}</div>
        <div style="margin-top:10px"><button class="btn btn-outline btn-sm" onclick="d3CloseDetail()">关闭</button></div>
      </div>
    </div>`;
  }
  const meta = d.meta || {};
  const syncTag = d.syncOk == null ? ''
    : tag(d.syncOk ? '两端一致' : '等待同步确认', d.syncOk ? '#00e888' : '#ffb020');
  const content = d.editing
    ? `<textarea id="d3-detail-data" class="ctrl-textarea mono"
        oninput="if(D3_STATE.detail)D3_STATE.detail.editData=this.value">${esc(d.editData || '')}</textarea>
      <div class="ctrl-row" style="justify-content:flex-end;margin-top:10px">
        <button class="btn btn-outline btn-sm" onclick="d3CancelDetailEdit()">取消</button>
        <button class="btn btn-warning btn-sm" onclick="d3SaveDetail()" ${d.saving?'disabled':''}>
          ${d.saving ? '保存中...' : '保存修改'}
        </button>
      </div>`
    : `<pre class="d3-detail-data mono">${esc(d.data || '')}</pre>
      <div class="ctrl-row" style="justify-content:flex-end;margin-top:10px">
        <button class="btn btn-outline btn-sm" onclick="d3CloseDetail()">关闭</button>
        <button class="btn btn-danger btn-sm" onclick="d3DeleteDetail()" ${d.deleting?'disabled':''}>
          ${d.deleting ? '删除中...' : '删除'}
        </button>
        <button class="btn btn-warning btn-sm" onclick="d3EditDetail()">修改</button>
      </div>`;
  return `<div class="d3-popover card" id="d3-detail-panel">${chead('对象详情', '✎', color,
      `${tag('节点 ' + d.node, color)}${syncTag}`)}
    <div class="card-body">
      <div class="g3" style="gap:10px;margin-bottom:10px">
        ${metric('KEY', esc(shrink(meta.name || d.name)), '', color)}
        ${metric('VERSION', 'v' + (meta.version || '-'), '', '#c0d8f0')}
        ${metric('SIZE', (meta.size || 0) + 'B', '', '#ffb020')}
      </div>
      ${content}
    </div>
  </div>`;
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
  const nameEl = document.getElementById('d3-name-' + node);
  const dataEl = document.getElementById('d3-data-' + node);
  const name = (nameEl && nameEl.value || '').trim() || 'demo_obj';
  const data = (dataEl && dataEl.value) || '';
  D3_STATE.forms[node] = { name, data };
  D3_STATE.busy = true;

  const api = d3ApiFor(node);
  const nodeColor = node === 'A' ? '#00e888' : '#00d0f0';
  try {
    let url, init;
    if (op === 'read') {
      url = `${api}/read?name=${encodeURIComponent(name)}`;
      init = { method: 'GET' };
    } else {
      url = `${api}/${op}`;
      init = { method: 'POST', headers: {'Content-Type':'application/json'},
               body: JSON.stringify({ name, data }) };
    }
    const res = await fetch(url, init);
    const j = await res.json();
    const latency = d3LatencyFields(op, j);
    d3PushEvent({
      ts:        j.ts || TS(),
      op:        op.toUpperCase(),
      color:     ({ write:'#00e888', modify:'#ffb020',
                    read:'#00d0f0' })[op] || '#c0d8f0',
      node:      `节点${node}`,
      nodeColor, name,
      detail:    j.ok
        ? (op === 'read' ? `size=${j.size} data="${shrink(j.data)}"`
                         : `size=${j.size||'-'} ver=v${j.version||'-'} hash=${j.hash||'-'}`)
        : '',
      lat:       latency.lat,
      latLabel:  latency.label,
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
  D3_STATE.busy = true;
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

function d3RowClick(ev) {
  const row = ev.currentTarget;
  if (!row) return;
  d3ShowDetail(row.dataset.node, row.dataset.name);
}

async function d3ShowDetail(node, name) {
  D3_STATE.detail = { node, name, loading:true, data:'', editData:'', meta:null, error:null, editing:false };
  D3_STATE.forms[node].name = name;
  const el = document.getElementById('d3-name-' + node);
  if (el) el.value = name;
  d3UpdatePartial();
  try {
    const r = await fetch(`${d3ApiFor(node)}/object?name=${encodeURIComponent(name)}`);
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || 'not found');
    D3_STATE.detail = {
      node, name, loading:false, data:j.data || '', editData:j.data || '',
      meta:j, error:null, syncOk:null, editing:false,
    };
  } catch (e) {
    D3_STATE.detail = { node, name, loading:false, data:'', editData:'', meta:null, error:e.message, editing:false };
  }
  d3UpdatePartial();
}

function d3CloseDetail() {
  D3_STATE.detail = null;
  d3UpdatePartial(true);
}

function d3EditDetail() {
  if (!D3_STATE.detail) return;
  D3_STATE.detail.editing = true;
  D3_STATE.detail.editData = D3_STATE.detail.data || '';
  d3UpdatePartial(true);
  const txt = document.getElementById('d3-detail-data');
  if (txt) txt.focus();
}

function d3CancelDetailEdit() {
  if (!D3_STATE.detail) return;
  D3_STATE.detail.editing = false;
  D3_STATE.detail.editData = D3_STATE.detail.data || '';
  d3UpdatePartial(true);
}

async function d3SaveDetail() {
  const d = D3_STATE.detail;
  if (!d || d.loading || d.error) return;
  const txt = document.getElementById('d3-detail-data');
  const data = txt ? txt.value : (d.editData || '');
  d.saving = true;
  d.syncOk = null;
  d3UpdatePartial(true);
  try {
    const res = await fetch(`${d3ApiFor(d.node)}/modify`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name:d.name, data }),
    });
    const j = await res.json();
    if (!j.ok) throw new Error(j.error || 'save failed');
    const latency = d3LatencyFields('modify', j);
    d3PushEvent({
      ts:j.ts || TS(), op:'SAVE', color:'#ffb020',
      node:`节点${d.node}`, nodeColor:d.node === 'A' ? '#00e888' : '#00d0f0',
      name:d.name, detail:`size=${j.size} ver=v${j.version} hash=${j.hash}`,
      lat:latency.lat, latLabel:latency.label,
      err:null,
    });
    await sleep(450);
    await d3Refresh();
    const peer = d.node === 'A' ? 'B' : 'A';
    const [selfObj, peerObj] = await Promise.all([
      fetch(`${d3ApiFor(d.node)}/object?name=${encodeURIComponent(d.name)}`).then(r => r.json()).catch(() => null),
      fetch(`${d3ApiFor(peer)}/object?name=${encodeURIComponent(d.name)}`).then(r => r.json()).catch(() => null),
    ]);
    const ok = !!(selfObj && selfObj.ok && peerObj && peerObj.ok && selfObj.data === peerObj.data);
    D3_STATE.detail = {
      node:d.node, name:d.name, loading:false,
      data:(selfObj && selfObj.data) || data,
      editData:(selfObj && selfObj.data) || data,
      meta:(selfObj && selfObj.ok) ? selfObj : j,
      error:null, syncOk:ok, editing:false,
    };
  } catch (e) {
    D3_STATE.detail = { ...d, loading:false, saving:false, error:e.message };
  }
  d3UpdatePartial(true);
}

async function d3DeleteDetail() {
  const d = D3_STATE.detail;
  if (!d || d.loading || d.error) return;
  if (!confirm(`确定删除对象 ${d.name} 吗？`)) return;
  d.deleting = true;
  d3UpdatePartial(true);
  try {
    const res = await fetch(`${d3ApiFor(d.node)}/delete`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name:d.name }),
    });
    const j = await res.json();
    if (!j.ok) throw new Error(j.error || 'delete failed');
    d3PushEvent({
      ts:j.ts || TS(), op:'DELETE', color:'#ff4050',
      node:`节点${d.node}`, nodeColor:d.node === 'A' ? '#00e888' : '#00d0f0',
      name:d.name, detail:'已删除并同步对端',
      err:null,
    });
    D3_STATE.detail = null;
    await d3Refresh();
  } catch (e) {
    D3_STATE.detail = { ...d, loading:false, deleting:false, error:e.message };
    d3UpdatePartial(true);
  }
}

function d3PushEvent(ev) {
  ev.uid = ++D3_STATE.uidSeq;
  D3_STATE.latestUid = ev.uid;
  D3_STATE.events.unshift(ev);
  if (D3_STATE.events.length > 50) D3_STATE.events.pop();

  // 直接对 DOM 操作：移除旧的 .latest 类、prepend 新节点
  const box = document.getElementById('d3-events');
  if (!box) return;    // 页面还没渲染完，d3Refresh 会在下一轮兜底
  // 移除 "暂无操作" 占位
  const emptyTip = document.getElementById('d3-events-empty');
  if (emptyTip) emptyTip.remove();
  // 清掉上一条的 latest 类（避免多个在闪）
  box.querySelectorAll('.eitem.latest')
     .forEach(el => el.classList.remove('latest'));
  // 新建元素并 prepend
  const wrapper = document.createElement('div');
  wrapper.innerHTML = d3EventHTML(ev, true);
  const node = wrapper.firstChild;
  box.insertBefore(node, box.firstChild);
  // 控制条数
  while (box.children.length > 50) box.removeChild(box.lastChild);
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
  // 骨架已建好 → 增量更新子区域；否则（首次或被切走过）完整 renderM3
  if (document.getElementById('d3-cluster-summary')) {
    d3UpdatePartial();
  } else {
    renderM3();
  }
}

function d3SyncDetailDraft() {
  const d = D3_STATE.detail;
  const txt = document.getElementById('d3-detail-data');
  if (d && d.editing && txt) d.editData = txt.value;
}

function d3ShouldPreserveDetail() {
  const d = D3_STATE.detail;
  return !!(d && d.editing && !d.saving && !d.deleting && !d.error);
}

function d3UpdatePartial(forceDetail = false) {
  d3SyncDetailDraft();
  const cA = D3_STATE.cluster.A, cB = D3_STATE.cluster.B;
  // 顶栏 status
  const st = document.getElementById('d3-status');
  if (st) {
    const ok = d3NodeOnline(cA) && d3NodeOnline(cB);
    st.className = 'ctrl-status ' + (ok ? 'running' : 'idle');
    st.innerHTML = `<div class="dot ${ok?'dot-pulse':''}" style="background:${ok?'#00e888':'#ff4050'};width:6px;height:6px"></div>` +
                   (ok ? '双节点在线' : '等待节点就绪');
  }
  const summary = document.getElementById('d3-cluster-summary');
  if (summary) summary.innerHTML = d3RenderClusterSummary(cA, cB);
  // 对象列表 + 计数 tag（重建 card 头部里的 tag 比较麻烦，直接替换整个 head）
  const ha = document.getElementById('d3-head-A');
  if (ha) ha.innerHTML = chead('节点 A 对象列表', '🅰', '#00e888',
            tag(`${D3_STATE.objects.A.length} 对象`, '#00e888'));
  const hb = document.getElementById('d3-head-B');
  if (hb) hb.innerHTML = chead('节点 B 对象列表', '🅱', '#00d0f0',
            tag(`${D3_STATE.objects.B.length} 对象`, '#00d0f0'));
  const la = document.getElementById('d3-list-A');
  if (la) la.innerHTML = d3RenderObjTable('A');
  const lb = document.getElementById('d3-list-B');
  if (lb) lb.innerHTML = d3RenderObjTable('B');
  const detail = document.getElementById('d3-detail');
  if (detail && (forceDetail || !d3ShouldPreserveDetail())) {
    detail.innerHTML = d3RenderDetail();
  }
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
function sleep(ms)  { return new Promise(resolve => setTimeout(resolve, ms)); }
function d3LatencyFields(op, j) {
  if ((op === 'write' || op === 'modify') && j && j.repl_ns != null) {
    return { lat: Number(j.repl_ns / 1000).toFixed(1), label: 'RDMA' };
  }
  return {
    lat: j && j.latency_us != null ? j.latency_us : null,
    label: op === 'read' ? '读取' : '延迟',
  };
}
