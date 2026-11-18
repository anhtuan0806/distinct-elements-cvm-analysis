# HƯỚNG DẪN SỬ DỤNG JUPYTER ADAPTER (TV2 & TV4)
> **Dành cho TV2 (Notebooks)** và **TV4 (Phân tích Time/Space Complexity)**  
> **Module**: `src/jupyter_adapter.py`  
> **Môi trường**: Linux Native, C++ CVM-A1 thật 100%, không mock/dry-run.

---

## 1. TỔNG QUAN

`src/jupyter_adapter.py` cung cấp function API `run_jupyter_benchmark(...)` giúp các thành viên chạy thực nghiệm trực tiếp từ cell trong Jupyter Notebook mà **không cần dùng lệnh terminal (`!python runner.py`)**, tự động xuất dữ liệu RAW CSV 24 cột chuẩn và file đồng hành `.metadata.json` đạt chứng nhận `verified_real` của Validator TV4.

---

## 2. HƯỚNG DẪN DÀNH CHO TV2 (NOTEBOOK INTEGRATION)

### 2.1. Chế độ Smoke (Mặc định — Bảo vệ "Run All" Notebook)
Khi người chấm hoặc TV2 bấm **"Run All"** toàn bộ Notebook, hàm mặc định chạy cấu hình siêu nhẹ ($m = 256$, $\sim 50\text{ ms}$) giúp notebook chạy thông suốt từ đầu đến cuối mà **không bao giờ bị đơ/treo Kernel**:

```python
from src.jupyter_adapter import run_jupyter_benchmark

# Cách 1: Không truyền tham số gì -> Tự động kích hoạt preset="smoke"
result = run_jupyter_benchmark()
print(f"Đã hoàn thành! File CSV: {result.csv_path}")

# Cách 2: Gọi rõ ràng preset="smoke", có thể tăng số trials
smoke_res = run_jupyter_benchmark(preset="smoke", trials=3)
```

### 2.2. Chạy Thực Nghiệm Cấu Hình Đơn Lẻ (Single Run)
```python
res = run_jupyter_benchmark(
    m=10000,
    workload="uniform",
    trials=5,
    seed=42,
    tag="uniform_10k",
)
print(f"Số bản ghi đã ghi: {res.records_count}")
```
*Lưu ý: Nếu không truyền `n` hoặc `f0`, adapter sẽ tự động tính toán hợp lệ ($n = 2m$, $F_0 = m/2$).*

### 2.3. Chạy Quét Tham Số (Parameter Sweep Big-O)
Hỗ trợ truyền danh sách nhiều $m$, nhiều workload và nhiều trials:

```python
sweep_res = run_jupyter_benchmark(
    m=[1000, 5000, 10000],
    workload=["uniform", "skewed", "zipf"],
    trials=3,
    epsilon=0.05,
    delta=0.01,
    tag="timespace_sweep",
)
print(
    f"Đã hoàn thành {sweep_res.configs_count} cấu hình, tổng cộng {sweep_res.records_count} trials."
)
```

### 2.4. Quy Tắc Tự Động Suy Diễn (Auto-Inference)
Khi bạn sweep $m$ mà không truyền $n$ và $F_0$:
- Với `all_distinct`: Tự động gán $F_0 = m$ và $n = \max(m, 1000)$ (đảm bảo $n \ge m$).
- Với `all_duplicate`: Tự động gán $F_0 = 1$ và $n = \max(m \times 2, 1000)$.
- Với các phân phối khác (`uniform`, `skewed`, `zipf`): Tự động gán $n = \max(m \times 2, 1000)$ và $F_0 = \max(1, m // 2)$.

---

## 3. HƯỚNG DẪN DÀNH CHO TV4 (PHÂN TÍCH TIME & SPACE COMPLEXITY)

### 3.1. Vị Trí Dữ Liệu RAW & Metadata
Mỗi phiên chạy sinh ra một cặp file duy nhất tại `results/real/jupyter/`:
- **File RAW CSV**: `results/real/jupyter/run_<YYYYMMDD_HHMMSS>_<session_id>_<tag>.csv`
- **File Sidecar**: `results/real/jupyter/run_<YYYYMMDD_HHMMSS>_<session_id>_<tag>.metadata.json`

> **Bảo vệ dữ liệu P0**: Adapter **tuyệt đối không bao giờ ghi đè** lên các file kết quả cũ của Windows (`results/real/raw_benchmark.csv`, `phase1.csv`, hay các figures trong `results/summary/`).

### 3.2. Nạp Dữ Liệu Vào Pandas
```python
import pandas as pd

# Cách 1: Nạp trực tiếp qua thuộc tính của kết quả
df = result.to_dataframe

# Cách 2: Nạp qua đường dẫn file CSV
df = pd.read_csv(result.csv_path)

# Xem 24 cột chuẩn
print(
    df[
        [
            "workload",
            "m",
            "F0",
            "algorithm_runtime_ms",
            "end_to_end_runtime_ms",
            "process_peak_memory_bytes",
        ]
    ]
)
```

### 3.3. Các Trường Đo Lường Quan Trọng Cho Space & Time Analysis
1. `algorithm_runtime_ms`: Thời gian chạy thực tế của lõi C++ (đo bằng `std::chrono::steady_clock` quanh vòng lặp `A1::update`).
2. `end_to_end_runtime_ms`: Thời gian wall-clock toàn bộ chu trình pipe từ Python sang C++ và parse kết quả.
3. `process_peak_memory_bytes`: Peak RSS thực tế của tiến trình C++ (đọc từ `/proc/self/status` `VmHWM`), **không bị dính RAM của Jupyter Kernel**.
4. `peak_sample_size`: Dung lượng buffer tập mẫu $X$ của thuật toán CVM ($|X| \le s$).

### 3.4. Kiểm Định Bằng Validator Của TV4
Dữ liệu sinh ra từ Adapter đáp ứng 100% các tiêu chí kiểm định của `scripts/validate_results.py`:
- `protocol_version == "cvm-a1-tv3-v1"`
- `execution_mode == "real"` và `data_source == "real"`
- Mã băm SHA-256 khớp từng byte với file CSV.
- Khối `batches` ghi đầy đủ `git_commit`, `source_tree_sha256`, `generator_sha256`, `binary_sha256` và thông số môi trường Linux.
- Đạt kết quả: **`verified_real`**.
