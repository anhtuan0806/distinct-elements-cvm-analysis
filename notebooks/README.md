# Notebook CVM-A1 Time/Space trên Ubuntu native

Notebook đọc P0 Linux đã lưu hoặc chạy benchmark CVM-A1 bằng Runner và Core
C++ thật. Dùng Ubuntu cài trực tiếp, Python 3.11 trở lên, GCC hoặc Clang hỗ trợ
C++17 và `systemd-detect-virt`. [Thiết kế ma trận P0](../docs/tv4-benchmark-analysis.md)

## Cài đặt và mở notebook

Kiểm tra phiên bản bằng `python3 --version`. Nếu Ubuntu dùng Python 3.10 mặc
định, dùng Python 3.11 trở lên đã cài để chạy lệnh tạo venv bên dưới.

```bash
sudo apt update
sudo apt install -y python3 python3-venv build-essential systemd

git clone https://github.com/anhtuan0806/distinct-elements-cvm-analysis.git
cd distinct-elements-cvm-analysis
git fetch origin
git switch --detach origin/feat/tv2-jupyter-timespace-analysis-notebook

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-jupyter.txt
python -m ipykernel install --user --name distinct-elements-cvm --display-name "Python (CVM-A1)"
jupyter lab notebooks/BIG_O_TimeSpace.ipynb
```

Bước `git switch` ở trên chọn nhánh TV2 có notebook. Khi dùng bản diff
đang review, chạy các lệnh từ worktree đã áp dụng diff. Trong JupyterLab,
chọn kernel **Python (CVM-A1)** với tên nội bộ `distinct-elements-cvm`.
Chọn **Restart Kernel and Run All** sau khi đổi chế độ hoặc cấu hình.

## Chế độ chạy

| `MODE` | Hành vi |
| --- | --- |
| `READ_EXISTING_P0` | Mặc định. Kiểm checksum và đọc 15 cặp RAW/sidecar từ manifest P0 Linux, hiển thị 135 bản ghi, 15 nhóm và 3 biểu đồ. Báo cáo ghi môi trường đo trong sidecar gốc. Run All chỉ đọc và phân tích bộ dữ liệu đã lưu. |
| `SMOKE_LINUX` | Tạo RAW và sidecar mới qua preset smoke của TV3 và chuyển đúng cặp này qua TV4. |
| `CUSTOM_SWEEP` | Chọn `CUSTOM_PROFILE = "TV4_P0"` để dùng ma trận P0 hoặc `"MANUAL"` để đặt tham số. Khi `RUN_CUSTOM = False`, notebook chỉ hiện cấu hình và số lượt dự kiến. Đặt `RUN_CUSTOM = True` để bắt đầu đo. |

Với một sweep nhỏ, đặt `CUSTOM_PROFILE = "MANUAL"`, `CUSTOM_M = [256, 1024]`,
`CUSTOM_WORKLOADS = ["uniform", "all_distinct"]` và `CUSTOM_TRIALS = 2`.
Giữ các tham số manual khác theo giá trị mặc định để dự kiến 4 cấu hình và
8 bản ghi. Notebook kiểm tra Ubuntu native trước khi đo mới. [Manifest P0 Linux](data/linux_p0/manifest.json)

## Kết quả và xuất tệp

Notebook in vị trí `analysis/report.md` sau mỗi lượt phân tích. Mở tệp này
từ thư mục xuất để xem các liên kết tương đối tới RAW, sidecar, CSV, PNG và
báo cáo chi tiết của TV4. Giữ nguyên cấu trúc thư mục khi di chuyển kết quả.

- `analysis/summary.csv`, `analysis/raw_index.csv` và `analysis/provenance.json`
  chứa số liệu, danh mục cặp RAW/sidecar, checksum và môi trường. Đường dẫn
  tới dữ liệu trong danh mục tính từ thư mục `analysis/`.
- `analysis/datasets/` giữ các báo cáo TV4 và đầu ra của từng cặp đầu vào.
  Với P0 đã lưu, các cặp RAW/sidecar được chép nguyên byte vào
  `analysis/inputs/`. Với phép đo mới, chúng nằm trong `real/` của cùng lượt.
- Khi không có số đo RSS, bảng hiển thị `N/A`, ô RSS trong CSV để trống và
  notebook báo **Không có số đo RSS**. Hình runtime và kích thước tập mẫu
  vẫn xuất nếu có số đo.

Vị trí mặc định là
`${XDG_DATA_HOME:-$HOME/.local/share}/distinct-elements-cvm-analysis/exports`.
Đặt `BIG_O_EXPORT_DIR` trước khi mở JupyterLab để dùng đường dẫn khác. Mỗi lần
phân tích tạo một thư mục mới bên dưới vị trí này.
