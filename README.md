# Phân tích độ phức tạp và cận sai số của thuật toán CVM trong bài toán đếm phần tử phân biệt trên luồng dữ liệu

Dự án nghiên cứu, thực nghiệm và phân tích lý thuyết thuật toán CVM (Chakraborty, Vinodchandran,
Meel) cho bài toán đếm số lượng phần tử phân biệt ($F_0$) trên luồng dữ liệu (Data Streams).

Lõi CVM-A1 được viết bằng C++ để ước lượng số phần tử phân biệt khi đọc dữ liệu theo luồng.
Phần thực nghiệm dùng Python để sinh dữ liệu, điều phối benchmark và ghi kết quả RAW CSV
phục vụ phân tích Time/Space complexity và sai số.

## Cài đặt môi trường

Dự án dùng Python 3.10 trở lên và trình biên dịch hỗ trợ C++17 như GCC, Clang hoặc MSVC.
Tạo môi trường Python bằng Bash như sau:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Chạy kiểm thử

Chạy toàn bộ bộ kiểm thử tích hợp (Python + C++) bằng lệnh:

```bash
pytest
```

## Chạy Benchmark thực nghiệm (Runner CLI)

Chương trình `runner.py` tự động biên dịch lõi C++ (nếu chưa có), sinh luồng dữ liệu theo
phân phối yêu cầu và ghi nhận kết quả vào file CSV chuẩn 24 cột.

### 1. Chạy một cấu hình đơn lẻ
```bash
python3 runner.py --m 10000 --n 5000 --f0 3000 --eps 0.05 --delta 0.01 --workload uniform --out results/raw_benchmark.csv
```

### 2. Chạy hàng loạt thử nghiệm (Multi-trial batch)
```bash
python3 runner.py --m 10000 --n 5000 --f0 3000 --trials 5 --workload zipf --out results/raw_benchmark.csv
```

### 3. Chạy chế độ kiểm thử schema nhanh (Dry-run)
```bash
python3 runner.py --dry-run --out results/schema_check.csv
```

## Cấu trúc dữ liệu RAW CSV (24 Cột Chuẩn P0)
Dữ liệu benchmark được ghi nhận với đầy đủ 24 trường:
`run_id,algorithm,workload,trial,m,n,F0,epsilon,delta,s,seed_generator,seed_algorithm,status,estimate,algorithm_runtime_ms,end_to_end_runtime_ms,peak_sample_size,halving_count,process_peak_memory_bytes,signed_rel_error,abs_rel_error,env_os,compiler,build_flags`.

- `algorithm_runtime_ms`: C++ cộng thời gian khởi tạo A1, xử lý từng ID đã parse và lấy kết quả.
- `end_to_end_runtime_ms`: Do Python đo wall-clock toàn bộ chu trình khởi tạo và truyền pipe.
- `peak_sample_size`: Số phần tử lớn nhất trong bộ nhớ đệm tập mẫu ($|X| \le s$).
- `process_peak_memory_bytes`: Peak Resident Set Size (RSS) của tiến trình C++ đo qua OS API.
- `signed_rel_error` & `abs_rel_error`: Sai số tương đối có dấu và trị tuyệt đối; để rỗng khi thất bại hoặc $F_0=0$.

## Tự đánh giá hạn chế của phép đo (Measurement Limitations)
1. **IPC Overhead**: Việc truyền luồng số qua đường ống `stdin` giữa Python và C++ tạo ra chi
   phí chuyển đổi chuỗi $\to$ số (dù `algorithm_runtime_ms` đã đo riêng, chi phí này vẫn
   ảnh hưởng đến `end_to_end_runtime_ms`).
2. **RAM Footprint (Allocator buffer)**: `process_peak_memory_bytes` (RSS) phản ánh bộ nhớ của cả
   tiến trình (gồm runtime, glibc heap/allocator), chứ không thuần túy chỉ có `std::unordered_set`.
3. **Độ phân giải thời gian ngắn**: Với $m$ nhỏ ($< 10^3$), runtime dưới 0.1ms có thể dao động
   do nhiễu context switch của CPU và hiệu ứng cache miss.

## Tài liệu

- [Cài đặt, build, chạy và kiểm thử CVM-A1](docs/README.md)
- [Kết quả kiểm thử P0 GĐ1](docs/cvm-a1-p0-evidence.md)
- [Kiến trúc & Luồng dữ liệu (Current Flow)](README_CURRENT_FLOW.md)
- [Bảng tiến độ công việc (Task Roadmap)](README_TASKS.md)

## Đóng góp

Xem chi tiết tại [CONTRIBUTING.md](CONTRIBUTING.md).
