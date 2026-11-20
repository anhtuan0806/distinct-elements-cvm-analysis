# Notebook benchmark CVM-A1 trên Ubuntu native

Notebook mặc định chạy mới 270 trial SCALE bằng Runner, Generator và Core
C++. Có thể chọn QUICK_LIVE hoặc một chế độ đọc dữ liệu lịch sử trong ô
cấu hình. Dùng Ubuntu native, Python 3.11 trở lên, GCC hoặc Clang hỗ trợ
C++17, `systemd-detect-virt`, GNU time và `prlimit`.
[Thiết kế ma trận P0](../docs/tv4-benchmark-analysis.md)

## Cài đặt và mở notebook

Từ thư mục gốc của checkout, kích hoạt môi trường Conda `big-o` rồi mở notebook.

```bash
conda activate big-o
python -m jupyterlab notebooks/BIG_O_TimeSpace.ipynb
```

Trên máy mới có Conda, tạo môi trường và cài dependencies nếu chưa có `big-o`.
Cài `build-essential`, `systemd`, `time` và `util-linux` trên Ubuntu nếu
cần chạy benchmark mới.

```bash
conda create --name big-o python=3.12 pip
conda activate big-o
python -m pip install -r requirements-jupyter.txt
python -m ipykernel install --user --name big-o --display-name "Python (BIG-O)"
```

Trong JupyterLab, chọn kernel **Python (BIG-O)** với tên nội bộ `big-o`.
Chọn **Restart Kernel and Run All** sau khi đổi chế độ hoặc cấu hình.

Runner tự build Core C++ cùng build receipt khi binary chưa tồn tại.
Để build riêng từ thư mục gốc mà chưa chạy benchmark, dùng:

```bash
python -c 'from src.cvm.build import build_cvm_core; print(build_cvm_core())'
```

## Chế độ chạy

| `MODE` | Hành vi |
| --- | --- |
| `RUN_LIVE_SCALE` | Mặc định. Mỗi Run All trực tiếp chạy Core qua Runner để đo 10 mốc từ 100k đến 100M, ba workload, chín trial mỗi cấu hình. Dự kiến hàng chục phút. |
| `QUICK_LIVE` | Chạy thật 100k và 200k, ba workload, hai trial đầu của mỗi cấu hình SCALE. |
| `READ_EXISTING_SCALE_FULL` | Đọc bộ SCALE tối ưu từ manifest và xác thực đúng 270 trial success thuộc 30 cấu hình và một phiên bản pipeline. |
| `READ_EXISTING_P0` | Đọc và kiểm checksum 15 cặp RAW/sidecar gồm 135 bản ghi, rồi hiển thị hình ghép và bảng tổng hợp ở năm mốc P0 lịch sử. |
| `READ_EXISTING_SCALE` | Đặt `SCALE_RAW` thành đường dẫn tới CSV của kế hoạch SCALE và giữ sidecar cạnh CSV. Notebook xác thực từng trial với giao thức và lịch seed SCALE, rồi phân tích phần đã chạy. |
| `SMOKE_LINUX` | Tạo RAW và sidecar mới qua preset smoke của TV3 và chuyển đúng cặp này qua TV4. |
| `CUSTOM_SWEEP` | Chọn `CUSTOM_PROFILE = "TV4_P0"` để dùng ma trận P0 hoặc `"MANUAL"` để đặt tham số. Khi `RUN_CUSTOM = False`, notebook chỉ hiện cấu hình và số lượt dự kiến. Đặt `RUN_CUSTOM = True` để bắt đầu đo. |

Các chế độ LIVE chạy ngay từ một checkout mới với môi trường đã cài.
Nếu chọn `READ_EXISTING_SCALE_FULL`, sao chép [manifest mẫu](data/scale_full/manifest.example.json)
và điền thông tin của bộ SCALE hoàn chỉnh đã có. `raw` có thể là đường dẫn
tương đối tính từ manifest hoặc đường dẫn tuyệt đối. Sidecar có cùng tên gốc
với RAW và đuôi `.metadata.json`.

- Lấy `raw_sha256` từ trường `sha256` của sidecar và tính `sidecar_sha256`
  bằng `sha256sum` trên chính tệp sidecar.
- Lấy `source_tree_sha256` và `generator_sha256` từ bản ghi batch trong
  sidecar. Lấy `binary_sha256` từ `environment` của batch đó.
- Đặt `BIG_O_SCALE_FULL_MANIFEST` thành đường dẫn tới manifest đã điền trước
  khi mở JupyterLab. Khi biến này chưa được đặt, notebook tìm cấu hình cục
  bộ `notebooks/data/scale_full/manifest.json`. Notebook báo lỗi khi thiếu
  manifest, RAW hoặc sidecar. Chọn `READ_EXISTING_P0` để xem bộ P0 có sẵn.

### Theo dõi hoặc dừng một lượt LIVE

Mỗi lượt LIVE tạo một thư mục timestamp và run ID riêng dưới
`BIG_O_EXPORT_DIR` hoặc vị trí xuất mặc định. Notebook cập nhật m,
workload, trial, số trial thành công, thời gian và mẫu RAM/swap.
`events.jsonl` ghi PID Runner và Core, thời điểm tiến trình bắt đầu, kết thúc
và run ID của trial. `run-provenance.json` ghi kế hoạch, fingerprint và trạng
thái. `logs/` giữ log Runner và GNU time theo batch.

Có thể chọn **Interrupt Kernel** để dừng. Bộ giám sát độc lập xử lý cả
trường hợp kernel kết thúc, dừng đúng nhóm tiến trình benchmark và giữ
các trial đã ghi. Nó giữ 4 GiB RAM dự phòng, kiểm tra swap, deadline và
khóa các lượt LIVE chạy đồng thời trong cùng tài khoản. Nếu dừng giữa
chừng, notebook phân tích phần RAW đã xác thực của lượt đó nếu còn chạy.
Mỗi Run All sau đó bắt đầu một run ID mới.

Với một sweep nhỏ, đặt `CUSTOM_PROFILE = "MANUAL"`, `CUSTOM_M = [256, 1024]`,
`CUSTOM_WORKLOADS = ["uniform", "all_distinct"]` và `CUSTOM_TRIALS = 2`.
Giữ các tham số manual khác theo giá trị mặc định để dự kiến 4 cấu hình và
8 bản ghi. Notebook kiểm tra Ubuntu native trước khi đo mới. [Manifest P0 Linux](data/linux_p0/manifest.json)

## Kết quả và xuất tệp

Notebook in vị trí `analysis/report.md` sau mỗi lượt phân tích. Mở tệp này
từ thư mục xuất để xem các liên kết tương đối tới RAW, sidecar, CSV, PNG và
báo cáo chi tiết của TV4. Giữ nguyên cấu trúc thư mục khi di chuyển kết quả.

- `analysis/aggregate_summary.csv` có một hàng mỗi m, theo thứ tự số.
  Mỗi metric có giá trị, số workload có dữ liệu, số trial hợp lệ và
  trạng thái `complete`, `partial`, `no_data` hoặc `mixed_configuration`.
- `analysis/benchmark_summary.csv` là bảng chi tiết theo cấu hình. Mỗi hàng ghi
  F₀ thực, median estimate, runtime (ms), peak RSS (MiB), relative error (%),
  số lượt success, tổng attempt, `s`, `F₀/m` và các `run_id` cách nhau bằng dấu
  cách. Cột `raw_sources` là danh sách đường dẫn RAW tính từ `analysis/`.
  `analysis/raw_index.csv` ghi đường dẫn sidecar và checksum của từng nguồn.
- `analysis/summary.csv` giữ schema TV4, gồm peak sample và RSS theo byte.
  `analysis/provenance.json` ghi hash đầu vào, môi trường, kế hoạch SCALE
  khi áp dụng và checksum bảng số liệu. Đường dẫn RAW trong danh mục tính
  từ thư mục `analysis/`.
- `analysis/datasets/` giữ các báo cáo TV4 và đầu ra của từng cặp đầu vào.
  Với P0 đã lưu, các cặp RAW/sidecar được chép nguyên byte vào
  `analysis/inputs/`. Với LIVE, `scale-live.csv` và sidecar nằm ở thư mục
  gốc của cùng lượt. Các lượt smoke và custom lưu trong `real/`.
- Khi không có RSS hoặc sai số hợp lệ, bảng hiện `N/A` và CSV để trống.
  Hình ghép hiện thông báo nếu cả một ô thiếu số đo.

Vị trí mặc định là
`${XDG_DATA_HOME:-$HOME/.local/share}/distinct-elements-cvm-analysis/exports`.
Đặt `BIG_O_EXPORT_DIR` trước khi mở JupyterLab để dùng đường dẫn khác. Mỗi lần
phân tích tạo một thư mục mới bên dưới vị trí này.

### Hình tổng hợp

`analysis/timespace_combined.png` có ba ô A (runtime lõi, ms), B (peak RSS
tiến trình C++, MiB) và C (relative error, %). Mặc định notebook hiện hình
ghép, bảng theo m và đường dẫn đầu ra. Hình được lưu ở 300 dpi.

Với mỗi m và mỗi metric, TV4 lấy median từ trial success có số đo cho từng
workload trong `all_duplicate`, `uniform`, `all_distinct`. TV4 tính trung
bình không trọng số của các median có dữ liệu. Đây là số tổng hợp từ nhiều
trial. Relative error được tính riêng theo `|estimate - F0| / F0 × 100`
từ estimate và F₀ trong RAW của mỗi trial success có F₀ dương. Peak RSS là
số đo của tiến trình C++, ngoài bộ nhớ dùng bởi Python.

Mỗi ô có nhãn và mốc kích thước riêng trên trục log₁₀. SCALE hiển thị đủ
10 mốc 1–2–5, còn P0 giữ năm mốc lịch sử. Peak RAM bắt đầu ở 0 MiB.
Trục sai số bắt đầu tại 0% và tự chọn giới hạn trên theo điểm lớn nhất
trên hình. Ví dụ, sai số lớn nhất 2,4% cho dải 0–3%. Giá trị trên 100%
làm trục mở rộng theo các mốc tròn. Hình mặc định hiển thị một trục sai
số duy nhất.

Chỉ m đo được mới có điểm. Đường dừng tại mốc thiếu. Khi một metric có ít hơn ba
workload, điểm có nhãn `k/3` và bảng ghi số trial đóng góp. Nếu tại cùng m
có nhiều cấu hình cho một workload, hoặc môi trường đo, n, ε, δ hay s
khác nhau giữa các nhóm có số đo, metric đó để trống và giữ số liệu trong
bảng chi tiết.

Đặt `SHOW_WORKLOAD_DETAILS = True` để xem và xuất thêm biểu đồ workload.
CLI cũng mặc định xuất hình tổng hợp và dùng `--workloads` để chọn hình
chi tiết.

```bash
python -m scripts.plot_results path/to/raw.csv --out-dir path/to/figures
python -m scripts.plot_results path/to/raw.csv --out-dir path/to/figures --workloads
python -m scripts.analyze_results path/to/raw.csv --out path/to/summary.csv \
  --benchmark-out path/to/benchmark_summary.csv --aggregate-out path/to/aggregate_summary.csv
```

## Benchmark SCALE (1–2–5)

[Ma trận mới](../experiments/benchmark_plan_timespace_scale.csv) có 30 cấu
hình và 270 lượt theo lịch đầy đủ. Mốc m đi từ 100.000 đến 100.000.000.
`n = 100.000.000`, `ε = 0,5` và `δ = 0,05` giữ cố định. `all_duplicate`
dùng F₀ = 1, `uniform` dùng F₀ = m/4, `all_distinct` dùng F₀ = m. Cố định n
cho phép so sánh cùng miền ID và bảo đảm n ≥ m cho mọi mốc. Ngưỡng tham chiếu
là `ceil(12 / ε² × log₂(8m / δ))`, tăng từ 1.149 đến 1.628 vì phụ thuộc m.
RAW lưu ngưỡng thực của Core. Mỗi cấu hình có trial 1–9 với seed generator
44000–44008 và seed Core 84000–84008 theo cùng chỉ số trial.

Trên Ubuntu native 64-bit, xem trước cấu hình, kiểm tra `free -h` và `df -h`
ở đích xuất, rồi đo một mốc nhỏ trước. Dùng `/usr/bin/time -v` để quan sát
bộ nhớ tối đa và thời gian đầu-cuối ngoài số liệu RSS/runtime của Core.
Executor truyền stdin theo khối tối đa 8.192 ID (tối đa 168 KiB văn bản
uint64 mỗi khối), đọc stdout/stderr đồng thời và đặt deadline 600 giây
cho mỗi trial Core. Generator giữ thứ tự theo seed và dùng mảng số gọn
với các mẫu đủ dày. `uniform` vẫn cần trạng thái phụ thuộc F₀ và bước
sắp xếp. Hãy đo RAM toàn pipeline ở các mốc thấp hơn trước khi tăng m.
CSV/sidecar lưu kết quả từng trial và mã băm nguồn. Dùng một cặp RAW/sidecar
mới khi đổi generator hoặc cách cấp stdin để truy vết riêng từng bộ đo.

```bash
out_dir=$(mktemp -d)
raw="$out_dir/scale.csv"
python -m scripts.generate_timespace_plan --preview SCALE --raw "$raw"
python -m scripts.generate_timespace_plan --run SCALE --m 100000 --workload uniform --raw "$raw"
python -m scripts.generate_timespace_plan --run SCALE --m 100000 --resume --raw "$raw"
```

Bỏ `--workload` để chọn cả ba workload hoặc lặp `--workload` và `--m` để
chọn một phần. `--run SCALE` yêu cầu nêu ít nhất một m. Lần đầu dùng tên CSV
mới. `--resume` xác thực RAW/sidecar cùng cấu hình và lịch seed, rồi Runner
bỏ qua trial đã hoàn tất với định danh tương thích. Dùng tệp mới khi đổi
máy hoặc môi trường để giữ bộ đo độc lập. Nếu sidecar báo `pending` do
tiến trình bị ngắt giữa lúc ghi, dùng đúng lệnh Runner từ `--preview` để
khôi phục theo [giao thức TV3](../docs/tv3-runner.md), rồi tiếp tục SCALE.

Để xem phần đã chạy, chọn `READ_EXISTING_SCALE`, đặt `SCALE_RAW` thành
đường dẫn RAW. Notebook ghi hình ghép và bảng vào một thư mục xuất mới
ở mỗi lượt phân tích.
