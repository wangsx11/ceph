# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
分布式共享数据管理系统 - 后端API服务
基于Flask + Ceph RADOS，提供三个模块的真实后端:
  M3: 基于RDMA跨节点对象读写与数据同步
  M5: 系统吞吐量及实体数量增加对性能影响
  M6: 分级存储能力演示
"""
import os

from flask import Flask, jsonify
from flask_cors import CORS

from ceph_manager import ceph_mgr
from config import CEPH_CONF, CURRENT_NODE
from m3_sync import m3_bp
from m5_perf import m5_bp
from m6_tiering import m6_bp
from utils import ts

# ============================================================
# Flask App
# ============================================================
app = Flask(__name__)
CORS(app)

app.register_blueprint(m3_bp)
app.register_blueprint(m5_bp)
app.register_blueprint(m6_bp)


# ============================================================
# 健康检查
# ============================================================

@app.route('/api/health', methods=['GET'])
def health():
    try:
        ceph_mgr.init()
        return jsonify({
            "ok": True,
            "ceph_connected": True,
            "fsid": ceph_mgr.cluster.get_fsid(),
            "node": CURRENT_NODE,
            "timestamp": ts(),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================================
# 入口
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"[Server] 启动分布式存储后端 on :{port}")
    print(f"[Server] 节点: {CURRENT_NODE}, Ceph配置: {CEPH_CONF}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
