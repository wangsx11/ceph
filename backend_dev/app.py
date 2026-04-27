# -*- coding: utf-8 -*-
"""backend_dev Flask entrypoint."""
import os

from flask import Flask, jsonify
from flask_cors import CORS

from ceph_manager import ceph
from config import CURRENT_NODE, CEPH_CONF
from m3_sync import m3_bp
from m4_snapshot import m4_bp
from m5_perf import m5_bp
from m6_tiering import m6_bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(m3_bp)
app.register_blueprint(m4_bp)
app.register_blueprint(m5_bp)
app.register_blueprint(m6_bp)


@app.route("/api/health", methods=["GET"])
def health():
    try:
        ceph.init()
        return jsonify({"ok": True, "ceph_connected": True,
                        "fsid": ceph.cluster.get_fsid(),
                        "node": CURRENT_NODE})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[backend_dev] starting on :{port} node={CURRENT_NODE} conf={CEPH_CONF}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
