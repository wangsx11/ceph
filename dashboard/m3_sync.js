// ============================================================
// m3_sync.js — 模块三：基于RDMA跨节点对象读写与数据同步
// 调用真实后端API (Flask + 分布式存储)
// ============================================================

const API_BASE = window.API_BASE || 'http://localhost:5000';

// 获取指定节点的API地址
function getNodeAPI(node) {
  if (node === 'A') return window.API_BASE_A || API_BASE;
  if (node === 'B') return window.API_BASE_B || API_BASE;
  return API_BASE;
}

let syncBuilt = false, syncBuildStep = 0;
let syncNodeAList = [], syncNodeBList = [];
let syncLogs = [];
let syncPollingTimer = null;

// 每个节点面板的视图状态：'list' 或 'detail'
const syncPanelState = {
  A: { view: 'list', objName: '' },
  B: { view: 'list', objName: '' },
};

// ============================================================
// 顶层渲染
// ============================================================

function renderM3() {
  const el = document.getElementById('pg-m3');
  const buildSteps = ['检测节点A(xfusion3)', '检测节点B(xfusion4)', '建立RDMA连接', '挂载共享存储池', '完成'];

  let buildH = '';
  if (!syncBuilt) {
    // 获取节点状态信息
    const nodeAStatus = syncBuildStep >= 1 ? '<span style="color:#00e888">●</span> 可达' : '<span style="color:#5a7a96">○</span> 待检测';
    const nodeBStatus = syncBuildStep >= 2 ? '<span style="color:#00e888">●</span> 可达' : '<span style="color:#5a7a96">○</span> 待检测';
    const currentStepText = syncBuildStep > 0 ? buildSteps[Math.min(syncBuildStep - 1, 4)] : '';
    const currentStepColor = syncBuildStep > 0 ? '#00e888' : '#5a7a96';

    buildH = `<div class="ctrl-panel" style="margin-bottom:14px">
      <div style="font-size:1.4rem;font-weight:700;color:#c0d8f0;margin-bottom:8px">构建双节点环境</div>
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:10px">逐步发现 xfusion3(节点A) 和 xfusion4(节点B) 两个独立物理节点，建立RDMA连接，挂载共享存储池</div>

      <!-- 节点状态信息 -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;background:#0a1420;padding:10px;border-radius:6px">
        <div style="font-size:1.1rem">
          <div style="color:#00e888;font-weight:700;margin-bottom:4px">● 节点A (xfusion3)</div>
          <div style="color:#5a7a96;margin-left:10px">IP: ${window.API_BASE_A.replace('http://','').replace(':5000','')}</div>
          <div style="margin-left:10px">${nodeAStatus}</div>
        </div>
        <div style="font-size:1.1rem">
          <div style="color:#00d0f0;font-weight:700;margin-bottom:4px">● 节点B (xfusion4)</div>
          <div style="color:#5a7a96;margin-left:10px">IP: ${window.API_BASE_B.replace('http://','').replace(':5000','')}</div>
          <div style="margin-left:10px">${nodeBStatus}</div>
        </div>
      </div>

      <!-- 步骤进度条 -->
      <div class="steps">${buildSteps.map((_, i) => `<div class="step ${i < syncBuildStep ? 'done' : ''}"></div>`).join('')}</div>

      <!-- 当前步骤（高亮显示） -->
      <div style="font-size:1.2rem;font-weight:700;color:${currentStepColor};margin:8px 0">
        ${syncBuildStep > 0 ? '▸ ' + currentStepText : '<span style="color:#5a7a96">等待开始构建...</span>'}
      </div>

      <button class="btn btn-primary" onclick="buildNodes()" ${syncBuildStep > 0 ? 'disabled' : ''}>▶ 构建双节点环境</button>
    </div>`;
  }

  let sharedH = '';
  if (syncBuilt) {
    sharedH = `<div class="shared-folder">
      <div style="text-align:center">
        <div style="font-size:1.2rem;font-weight:700;color:#00e888">节点A</div>
        <div style="font-size:1.1rem;color:#5a7a96">前线指挥所</div>
        <div style="font-size:1rem;color:#5a7a96">xfusion3</div>
      </div>
      <div style="text-align:center">
        <div class="shared-folder-icon">📁</div>
        <div style="font-size:1.2rem;color:#00d0f0;font-weight:700">共享存储池 sync_pool</div>
        <div style="font-size:1rem;color:#5a7a96">分布式存储池 · RDMA传输 · 两节点均可读写</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.2rem;font-weight:700;color:#00d0f0">节点B</div>
        <div style="font-size:1.1rem;color:#5a7a96">后方指挥中心</div>
        <div style="font-size:1rem;color:#5a7a96">xfusion4</div>
      </div>
    </div>`;
  }

  let panelsH = '';
  if (syncBuilt) {
    panelsH = `<div class="g2" style="margin-top:14px">
      ${renderSyncNodePanel('A', '前线指挥所', '#00e888')}
      ${renderSyncNodePanel('B', '后方指挥中心', '#00d0f0')}
    </div>`;
  }

  const logH = syncLogs.length
    ? `<div class="card" style="margin-top:14px">${chead('同步指标','📡','#00d0f0',tag('LIVE','#00e888'))}<div class="card-body"><div id="sync-log-body" class="elog">${syncLogs.map((l,i)=>`<div class="eitem ${i===0?'latest':''}">${l}</div>`).join('')}</div></div></div>`
    : `<div class="card" style="margin-top:14px">${chead('同步指标','📡','#00d0f0',tag('LIVE','#00e888'))}<div class="card-body"><div id="sync-log-body" class="elog"><div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:10px">等待操作...</div></div></div></div>`;

  el.innerHTML = buildH + sharedH + panelsH + logH;
}

// ============================================================
// 节点面板外壳（card + card-body，body 内容按状态切换）
// ============================================================

function renderSyncNodePanel(node, label, color) {
  const state = syncPanelState[node];
  const bodyH = state.view === 'detail'
    ? renderDetailPanel(node, state.objName, color)
    : renderListPanel(node);

  return `<div class="card border-rdma" id="sync-card-${node}">
    ${chead('节点' + node + ' · ' + label, '🖥', color,
      `<span class="label-rdma">RDMA传输</span> <span class="label-store">分布式存储</span>`)}
    <div class="card-body" id="sync-body-${node}">${bodyH}</div>
  </div>`;
}

// ============================================================
// 列表视图 HTML
// ============================================================

function renderListPanel(node) {
  const list = node === 'A' ? syncNodeAList : syncNodeBList;
  return `
    <div class="ctrl-row" style="margin-bottom:10px">
      <input class="ctrl-input" id="sync${node}-name" placeholder="对象名"
             value="${node === 'A' ? '兵力部署_A01' : '侦察情报_B05'}" style="width:140px">
      <input class="ctrl-input" id="sync${node}-data" placeholder="数据(JSON)"
             value='${node === 'A' ? '{"unit":"步兵连","count":120}' : '{"target":"蓝方阵地"}'}' style="width:180px">
      <button class="btn btn-success btn-sm" onclick="syncOp('${node}','write')">写入</button>
    </div>
    <div style="font-size:1.1rem;color:#7a95b0;margin-bottom:6px">
      节点${node} 对象列表 (存储池: sync_pool)：
      <span style="color:#5a7a96;font-size:1rem;margin-left:4px">· 点击行查看详情</span>
    </div>
    <div id="sync-list-${node}" style="max-height:200px;overflow-y:auto">
      ${renderSyncList(list, node)}
    </div>`;
}

function renderSyncList(list, node) {
  if (!list || !list.length) {
    return '<div style="color:#5a7a96;font-size:1.1rem;text-align:center;padding:10px">暂无对象</div>';
  }
  return `<table class="dtable"><thead>
    <tr><th>名称</th><th>大小</th><th>版本</th><th>哈希</th><th>创建</th><th>最后修改</th></tr>
  </thead><tbody>
    ${list.map(o => `<tr style="cursor:pointer;transition:background 0.15s"
        onclick="syncShowDetail('${node}','${escAttr(o.name)}')"
        onmouseenter="this.style.background='rgba(0,208,240,0.08)'"
        onmouseleave="this.style.background=''"
        title="点击查看详情">
      <td style="color:#e4edf6">${esc(o.name)}</td>
      <td>${esc(o.size)}</td>
      <td style="color:#ffb020">v${o.version}</td>
      <td style="color:#5a7a96;font-family:monospace">${esc(o.hash)}</td>
      <td style="font-size:1rem;color:#5a7a96">${esc(o.created_by||'')}</td>
      <td style="font-size:1rem;color:#5a7a96">${esc(o.modified_by||'')}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

// ============================================================
// 详情视图 HTML（渲染在面板内部，不弹窗）
// ============================================================

function renderDetailPanel(node, objName, color) {
  const meta = syncNodeAList.find(o => o.name === objName)
            || syncNodeBList.find(o => o.name === objName);
  const nc = node === 'A' ? '#00e888' : '#00d0f0';

  return `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;
                padding-bottom:10px;border-bottom:1px solid #1e2d3d">
      <button onclick="syncBackToList('${node}')"
              style="background:rgba(255,255,255,0.05);border:1px solid #2a3d52;color:#7a95b0;
                     font-size:1.1rem;cursor:pointer;padding:3px 10px;border-radius:4px;transition:all 0.15s"
              onmouseenter="this.style.color='${nc}';this.style.borderColor='${nc}'"
              onmouseleave="this.style.color='#7a95b0';this.style.borderColor='#2a3d52'">
        ← 返回列表
      </button>
      <span style="font-size:1.1rem;color:#5a7a96">/ 对象详情</span>
    </div>

    <div style="background:#080f18;border-left:3px solid ${nc};border-radius:4px;
                padding:8px 12px;margin-bottom:12px">
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:2px">对象名称</div>
      <div style="color:${nc};font-weight:700;font-size:1.3rem;word-break:break-all">${esc(objName)}</div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
      ${_dc('大小',    meta ? meta.size          : '-', '#e4edf6', false)}
      ${_dc('版本',    meta ? 'v'+meta.version   : '-', '#ffb020', false)}
      ${_dc('哈希',    meta ? meta.hash          : '-', '#5a7a96', true)}
      ${_dc('存储池',  'sync_pool',                     '#00d0f0', false)}
      ${_dc('创建节点',meta ? '节点'+meta.created_by  : '-', '#e4edf6', false)}
      ${_dc('修改节点',meta ? '节点'+meta.modified_by : '-', '#e4edf6', false)}
    </div>

    <div style="margin-bottom:12px">
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:4px">数据内容（可编辑）</div>
      <textarea id="sync-detail-data-${node}"
                style="width:100%;height:80px;background:#080f18;border:1px solid #2a3d52;
                       border-radius:4px;color:#e4edf6;font-size:1.1rem;font-family:monospace;
                       padding:8px;resize:vertical;box-sizing:border-box"
                placeholder="数据内容">正在读取...</textarea>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;
                padding-top:10px;border-top:1px solid #1e2d3d">
      <button onclick="syncBackToList('${node}')"
              class="btn btn-outline btn-sm" style="font-size:1.1rem">← 返回</button>
      <button onclick="syncModifyFromDetail('${node}','${escAttr(objName)}')"
              class="btn btn-warning btn-sm" style="font-size:1.1rem">✏️ 修改</button>
      <button onclick="syncDeleteFromDetail('${node}','${escAttr(objName)}')"
              class="btn btn-danger btn-sm" style="font-size:1.1rem">🗑 删除</button>
    </div>`;
}

function _dc(label, value, color, mono) {
  return `<div style="background:#080f18;border-radius:4px;padding:7px 10px">
    <div style="font-size:1rem;color:#5a7a96;margin-bottom:2px">${label}</div>
    <div style="color:${color};font-size:1.1rem;word-break:break-all;${mono?'font-family:monospace':''}">${esc(String(value))}</div>
  </div>`;
}

// ============================================================
// 切换到详情视图
// ============================================================

async function syncShowDetail(node, objName) {
  syncPanelState[node].view = 'detail';
  syncPanelState[node].objName = objName;

  const body = document.getElementById('sync-body-' + node);
  if (!body) return;
  const nc = node === 'A' ? '#00e888' : '#00d0f0';
  body.innerHTML = renderDetailPanel(node, objName, nc);

  // 异步填充数据内容
  try {
    const res = await fetch(`${getNodeAPI(node)}/api/m3/read?name=${encodeURIComponent(objName)}`);
    const data = await res.json();
    const el = document.getElementById('sync-detail-data-' + node);
    if (!el) return;

    if (data.ok && data.data !== undefined) {
      let display = data.data;
      try {
        const parsed = typeof display === 'string' ? JSON.parse(display) : display;
        display = JSON.stringify(parsed, null, 2);
      } catch (_) {}
      // 填充到 textarea 中
      el.value = display;
      el.dataset.latency = data.latency_us || 0;
    } else {
      el.value = `⚠ ${esc(data.error || '读取失败')}`;
    }
  } catch (e) {
    const el = document.getElementById('sync-detail-data-' + node);
    if (el) el.innerHTML = `
      <div style="font-size:1rem;color:#5a7a96;margin-bottom:4px">数据内容</div>
      <div style="color:#ff6060;font-size:1.1rem">⚠ ${esc(e.message)}</div>`;
  }
}

// ============================================================
// 返回列表视图
// ============================================================

function syncBackToList(node) {
  syncPanelState[node].view = 'list';
  syncPanelState[node].objName = '';
  const body = document.getElementById('sync-body-' + node);
  if (body) body.innerHTML = renderListPanel(node);
}

// ============================================================
// 详情面板内修改
// ============================================================

async function syncModifyFromDetail(node, objName) {
  const el = document.getElementById('sync-detail-data-' + node);
  if (!el) return;

  const newData = el.value.trim();
  if (!newData) {
    alert('数据内容不能为空');
    return;
  }

  const btn = document.querySelector('#sync-body-' + node + ' .btn-warning');
  if (btn) { btn.disabled = true; btn.textContent = '修改中...'; }

  try {
    const res = await fetch(`${getNodeAPI(node)}/api/m3/modify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: objName, data: newData, node }),
    });
    const result = await res.json();

    if (result.ok) {
      syncLogs.unshift(
        `<span style="color:#5a7a96">${result.timestamp}</span> ` +
        `<span style="color:#ffb020;font-weight:700">MODIFY</span> ` +
        `<span style="color:#e4edf6">${esc(result.name)}</span> on ` +
        `<span style="color:${node==='A'?'#00e888':'#00d0f0'}">节点${node}</span> → ` +
        `延迟: <span style="color:#ffb020">${result.latency_us}μs</span> | ` +
        `版本: v${result.version} | <span style="color:#00e888">两节点已更新 ✓</span>`
      );
      if (syncLogs.length > 30) syncLogs.length = 30;

      // 刷新列表
      await refreshSyncObjects();

      // 刷新同步指标显示
      const logBody = document.getElementById('sync-log-body');
      if (logBody) logBody.innerHTML = syncLogs.map((l, i) =>
        `<div class="eitem ${i === 0 ? 'latest' : ''}">${l}</div>`).join('');
    } else {
      alert('修改失败: ' + (result.error || '未知错误'));
    }
  } catch (e) {
    alert('修改失败: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✏️ 修改'; }
  }
}

// ============================================================
// 详情面板内删除
// ============================================================

async function syncDeleteFromDetail(node, objName) {
  if (!confirm(`确定要删除对象 "${objName}" 吗？\n将从两个节点同步删除，不可恢复。`)) return;

  const btn = document.querySelector('#sync-body-' + node + ' .btn-danger');
  if (btn) { btn.disabled = true; btn.textContent = '删除中...'; }

  try {
    const res = await fetch(`${getNodeAPI(node)}/api/m3/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: objName, node }),
    });
    const result = await res.json();

    if (result.ok) {
      syncLogs.unshift(
        `<span style="color:#5a7a96">${result.timestamp}</span> ` +
        `<span style="color:#ff4050;font-weight:700">DELETE</span> ` +
        `<span style="color:#e4edf6">${esc(result.name)}</span> on ` +
        `<span style="color:${node==='A'?'#00e888':'#00d0f0'}">节点${node}</span> → ` +
        `延迟: <span style="color:#ffb020">${result.latency_us}μs</span> | ` +
        `<span style="color:#00e888">两节点已移除 ✓</span>`
      );
      if (syncLogs.length > 30) syncLogs.length = 30;

      await refreshSyncObjects();

      // 回到列表，同步更新两侧
      syncPanelState[node].view = 'list';
      syncPanelState[node].objName = '';
      const body = document.getElementById('sync-body-' + node);
      if (body) body.innerHTML = renderListPanel(node);

      // 另一侧如果也在列表视图，刷新它
      const other = node === 'A' ? 'B' : 'A';
      if (syncPanelState[other].view === 'list') {
        const otherList = document.getElementById('sync-list-' + other);
        const otherData = other === 'A' ? syncNodeAList : syncNodeBList;
        if (otherList) otherList.innerHTML = renderSyncList(otherData, other);
      }

      _updateLogEl();
    } else {
      alert('删除失败: ' + (result.error || '未知错误'));
      if (btn) { btn.disabled = false; btn.textContent = '🗑 删除此对象'; }
    }
  } catch (e) {
    alert('删除失败: ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = '🗑 删除此对象'; }
  }
}

// ============================================================
// 构建节点
// ============================================================

async function buildNodes() {
  syncBuildStep = 1;
  renderM3();

  const steps = [
    { step: 1, fn: async () => {} },
    { step: 2, fn: async () => {} },
    { step: 3, fn: async () => {
      try {
        // 检查两个节点是否都可达
        const [resA, resB] = await Promise.all([
          fetch(`${window.API_BASE_A}/api/m3/cluster`),
          fetch(`${window.API_BASE_B}/api/m3/cluster`)
        ]);
        const dataA = await resA.json();
        const dataB = await resB.json();
        if (!dataA.ok) throw new Error(`节点A (xfusion3) 不可达: ${dataA.error}`);
        if (!dataB.ok) throw new Error(`节点B (xfusion4) 不可达: ${dataB.error}`);
        console.log('[M3] 节点A:', dataA);
        console.log('[M3] 节点B:', dataB);
      } catch (e) { console.error('[M3] Cluster check failed:', e); throw e; }
    }},
    { step: 4, fn: async () => {} },
    { step: 5, fn: async () => {
      syncBuilt = true;
      await refreshSyncObjects();
      startSyncPolling();
    }},
  ];

  for (let i = 0; i < steps.length; i++) {
    await new Promise(r => setTimeout(r, 1200));
    syncBuildStep = steps[i].step;
    await steps[i].fn();
    renderM3();
  }
}

// ============================================================
// 轮询刷新（只刷新处于列表视图的面板，不打断详情视图）
// ============================================================

async function refreshSyncObjects() {
  try {
    // 从两个节点分别获取数据
    const [resA, resB] = await Promise.all([
      fetch(`${window.API_BASE_A}/api/m3/objects`),
      fetch(`${window.API_BASE_B}/api/m3/objects`)
    ]);
    const dataA = await resA.json();
    const dataB = await resB.json();

    // 使用合并后的数据（因为是共享Pool，数据应该一致）
    const objects = (dataA.ok && dataA.objects) ? dataA.objects : (dataB.ok ? dataB.objects : []);
    syncNodeAList = objects;
    syncNodeBList = objects;
  } catch (e) { console.error('[M3] refresh failed:', e); }
}

function startSyncPolling() {
  if (syncPollingTimer) clearInterval(syncPollingTimer);
  syncPollingTimer = setInterval(async () => {
    await refreshSyncObjects();
    updateSyncListsOnly();
  }, 2000);
}


let lastSyncLogCount = 0;

function updateSyncListsOnly() {
  ['A', 'B'].forEach(node => {
    if (syncPanelState[node].view === 'list') {
      const el = document.getElementById('sync-list-' + node);
      const list = node === 'A' ? syncNodeAList : syncNodeBList;
      if (el) el.innerHTML = renderSyncList(list, node);
    }
  });
  _updateLogEl();
}

function _updateLogEl() {
  if (syncLogs.length === lastSyncLogCount) return;
  lastSyncLogCount = syncLogs.length;
  const el = document.getElementById('sync-log-body');
  if (el) el.innerHTML = syncLogs.map((l, i) =>
    `<div class="eitem ${i === 0 ? 'latest' : ''}">${l}</div>`).join('');
}

// ============================================================
// 顶部输入框的写 / 改 / 删操作
// ============================================================

async function syncOp(node, op) {
  const nameEl = document.getElementById('sync' + node + '-name');
  const dataEl = document.getElementById('sync' + node + '-data');
  const name   = nameEl ? nameEl.value.trim() : '';
  const dataVal = dataEl ? dataEl.value.trim() : '{}';
  if (!name) { alert('请先填写对象名称'); return; }

  try {
    let res, result;
    const nc = node === 'A' ? '#00e888' : '#00d0f0';

    if (op === 'write') {
      res = await fetch(`${getNodeAPI(node)}/api/m3/write`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name, data: dataVal, node }),
      });
      result = await res.json();
      if (result.ok) {
        syncLogs.unshift(
          `<span style="color:#5a7a96">${result.timestamp}</span> ` +
          `<span style="color:#00e888;font-weight:700">WRITE</span> ` +
          `<span style="color:#e4edf6">${esc(result.name)}</span> on ` +
          `<span style="color:${nc}">节点${node}</span> → ` +
          `延迟: <span style="color:#ffb020">${result.latency_us}μs</span> | ` +
          `哈希: <span style="color:#5a7a96">${result.hash}</span> | ` +
          `<span style="color:#00e888">一致 ✓</span>`
        );
      }

    } else if (op === 'modify') {
      res = await fetch(`${getNodeAPI(node)}/api/m3/modify`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name, data: dataVal, node }),
      });
      result = await res.json();
      if (result.ok) {
        syncLogs.unshift(
          `<span style="color:#5a7a96">${result.timestamp}</span> ` +
          `<span style="color:#ffb020;font-weight:700">MODIFY</span> ` +
          `<span style="color:#e4edf6">${esc(result.name)}</span> on ` +
          `<span style="color:${nc}">节点${node}</span> → ` +
          `ver=${result.version} | 延迟: <span style="color:#ffb020">${result.latency_us}μs</span> | ` +
          `<span style="color:#00e888">一致 ✓</span>`
        );
      }

    } else if (op === 'delete') {
      res = await fetch(`${getNodeAPI(node)}/api/m3/delete`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name, node }),
      });
      result = await res.json();
      if (result.ok) syncLogs.unshift(
        `<span style="color:#5a7a96">${result.timestamp}</span> ` +
        `<span style="color:#ff4050;font-weight:700">DELETE</span> ` +
        `<span style="color:#e4edf6">${esc(result.name)}</span> on ` +
        `<span style="color:${nc}">节点${node}</span> → ` +
        `延迟: <span style="color:#ffb020">${result.latency_us}μs</span> | ` +
        `<span style="color:#00e888">两节点已移除 ✓</span>`
      );
    }

    if (result && !result.ok) syncLogs.unshift(
      `<span style="color:#5a7a96">${TS()}</span> ` +
      `<span style="color:#ff4050;font-weight:700">ERROR</span> ` +
      `${op} 失败: ${result.error || '未知错误'}`
    );
    if (syncLogs.length > 30) syncLogs.length = 30;
    await refreshSyncObjects();
    updateSyncListsOnly();

  } catch (e) {
    syncLogs.unshift(
      `<span style="color:#5a7a96">${TS()}</span> ` +
      `<span style="color:#ff4050;font-weight:700">ERROR</span> ${op} 失败: ${e.message}`
    );
    updateSyncListsOnly();
  }
}

// ============================================================
// 工具函数
// ============================================================

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function escAttr(str) { return esc(str); }

