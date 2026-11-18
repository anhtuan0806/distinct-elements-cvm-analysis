# Hướng dẫn notebook CVM-A1 Time/Space

## Yêu cầu

- Ubuntu Linux cài trực tiếp trên máy, Python 3.10 trở lên và GCC hoặc Clang hỗ trợ C++17.
- Các gói hệ thống: `python3-venv`, `build-essential` và `systemd-detect-virt`.

## Cài đặt và mở notebook

```bash
sudo apt update
sudo apt install -y python3 python3-venv build-essential systemd

git clone https://github.com/anhtuan0806/distinct-elements-cvm-analysis.git
cd distinct-elements-cvm-analysis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-jupyter.txt
python -m ipykernel install --user --name cvm-timespace --display-name "Python (CVM Time-Space)"
jupyter lab notebooks/BIG_O_TimeSpace.ipynb
```

Trong JupyterLab, chọn kernel **Python (CVM Time-Space)** rồi chọn **Run All**. Cấu hình mặc định đọc dữ liệu P0 Linux; notebook không khởi chạy benchmark khi chạy toàn bộ các ô.

## Chế độ chạy

Sửa `MODE` trong ô cấu hình:

- `READ_EXISTING_P0`: đọc manifest `notebooks/data/linux_p0/manifest.json`. Notebook kiểm tra checksum, sidecar, cấu hình P0 và provenance trước khi gọi API TV4.
- `SMOKE_LINUX`: gọi preset smoke của API TV3 để xác nhận pipeline C++ thật và phân tích kết quả qua TV4.
- `CUSTOM_SWEEP`: xem trước hoặc chạy profile `TV4_P0` hay các tham số `MANUAL`. Chỉ đặt `RUN_CUSTOM = True` khi chủ động chạy đo trên Ubuntu native.

Thông số P0 được đọc từ [kế hoạch benchmark](../experiments/benchmark_plan_timespace.csv). Cơ sở chọn `m`, `n`, `F₀`, `ε`, `δ` và giới hạn diễn giải được ghi trong notebook và tài liệu TV4.

## Kết quả và xuất tệp

RAW CSV cùng sidecar giữ nguyên theo từng lượt. TV4 tạo `summary.csv`, `raw_index.csv`, `provenance.json` và ba hình runtime, peak RSS, peak sample. Notebook hiển thị đường dẫn và liên kết tải tệp.

Mặc định, đầu ra nằm ngoài kho mã tại thư mục dữ liệu người dùng `distinct-elements-cvm-analysis/exports` (dùng `XDG_DATA_HOME`, hoặc `~/.local/share` nếu biến này chưa đặt). Có thể đặt `BIG_O_EXPORT_DIR` trước khi mở JupyterLab để chọn vị trí khác. Giữ RAW và sidecar cùng nhau; checksum trong sidecar ràng buộc với nội dung RAW.

## Nhật ký xác minh

Ngày 18/11/2026, checkout sạch được cài từ `requirements-jupyter.txt` và kiểm tra trên Ubuntu 26.04.1 LTS, kernel 7.0.0-43-generic, Python 3.14.4, GCC 15.2.0, JupyterLab 4.6.6 và ipykernel 7.4.0. Bộ kiểm tra môi trường ghi Ubuntu; `systemd-detect-virt --vm` và `--container` không phát hiện môi trường ảo hóa. Run All mặc định tạo bảng 135/135 success, 15 nhóm và ba hình. `SMOKE_LINUX` và `CUSTOM_SWEEP` đều chạy 2/2 lượt thành công qua Runner/C++ và TV4.
