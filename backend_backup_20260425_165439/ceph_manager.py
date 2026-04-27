# -*- coding: utf-8 -*-
"""Ceph 连接管理"""
import threading

import rados

from config import CEPH_CONF


class CephManager:
    """管理到Ceph集群的连接"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def init(self):
        if self._initialized:
            return
        try:
            self.cluster = rados.Rados(conffile=CEPH_CONF)
            self.cluster.connect()
            self._initialized = True
            print(f"[CephManager] 已连接到Ceph集群, fsid={self.cluster.get_fsid()}")
        except Exception as e:
            print(f"[CephManager] 连接Ceph失败: {e}")
            raise

    def open_ioctx(self, pool_name):
        """打开Pool的IO上下文"""
        self.init()
        return self.cluster.open_ioctx(pool_name)

    def pool_exists(self, pool_name):
        self.init()
        return self.cluster.pool_exists(pool_name)

    def create_pool(self, pool_name):
        self.init()
        if not self.pool_exists(pool_name):
            self.cluster.create_pool(pool_name)
            print(f"[CephManager] 创建Pool: {pool_name}")


ceph_mgr = CephManager()
