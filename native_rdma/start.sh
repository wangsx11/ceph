# 1) 同步开发机代码到 xfusion3
rsync -av --exclude 'build/' --exclude 'logs/' --exclude '__pycache__/' \
    /data/workspace/ceph/ceph/native_rdma/ ~/ceph-web/native_rdma/

# 2) xfusion3 重新编译
cd ~/ceph-web/native_rdma && cmake --build build -j

# 3) 推到 xfusion4
rsync -avz --exclude 'build/' --exclude 'logs/' \
    --exclude '*.pyc' --exclude '__pycache__/' \
    ~/ceph-web/ wangshouxin@xfusion4:~/ceph-web/

# 4) xfusion4 重建（带 rm -rf build 免路径陷阱）
ssh xfusion4 "cd ~/ceph-web/native_rdma && rm -rf build && \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -GNinja && \
    cmake --build build -j"

# 5) 清理旧的冷层目录残留（它之前是目录，没有数据文件，没有意义的残留都删）
rm -rf /home/wangshouxin/nr_cold/* 2>/dev/null || true
ssh xfusion4 "rm -rf /tmp/nr_cold/* 2>/dev/null || true"

# 6) 重启两端
bash ~/ceph-web/native_rdma/scripts/demo_down.sh 2>/dev/null || true
ssh xfusion4 "cd ~/ceph-web/native_rdma && bash scripts/demo_down.sh" 2>/dev/null || true

ssh xfusion4 "cd ~/ceph-web/native_rdma && ROLE=B bash scripts/demo_up.sh"
sleep 3
cd ~/ceph-web/native_rdma && ROLE=A bash scripts/demo_up.sh