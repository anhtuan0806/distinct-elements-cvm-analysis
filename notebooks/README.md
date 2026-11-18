# Chạy notebook phân tích time/space

Notebook chính: `BIG_O_TimeSpace.ipynb`. Notebook dùng Python để đọc P0 đã lưu hoặc gọi API thực nghiệm TV3 và API phân tích TV4 khi các mô-đun đó có trong checkout.

## Yêu cầu

- Linux native Ubuntu; không dùng WSL, máy ảo hoặc Colab để xác nhận phép đo Linux.
- Python 3.10 trở lên theo khai báo của dự án.
- GCC hoặc Clang hỗ trợ C++17 khi chạy benchmark thật. TV1 cung cấp lõi và bước build.
- Kết nối Internet khi cài các gói Python.

## Cài đặt và mở notebook

Chạy từ thư mục gốc của bản clone:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-jupyter.txt
python -m ipykernel install --user --name distinct-elements-cvm --display-name "Python (CVM analysis)"
jupyter lab
```

Trong JupyterLab, mở `notebooks/BIG_O_TimeSpace.ipynb` và chọn kernel **Python (CVM analysis)**. Chọn **Run → Run All Cells** để chạy theo chế độ đang đặt trong cell cấu hình.

Notebook dùng `sys.executable` của kernel hiện hành và tìm thư mục gốc dựa trên `pyproject.toml`; không cần sửa đường dẫn theo máy.

## Chế độ chạy

Cell cấu hình đặt `MODE = "READ_EXISTING_P0"` mặc định. Chế độ này đọc bộ P0 đã lưu trên Windows, kiểm tra RAW và sidecar bằng validator hiện có, sau đó hiển thị 135 bản ghi, 15 nhóm, ba hình đã lưu và thông tin môi trường Windows. Kết quả này không phải phép đo Linux.

- `READ_EXISTING_P0`: đọc bộ dữ liệu P0 có sẵn; an toàn cho **Run All**.
- `SMOKE_LINUX`: gọi `run_jupyter_benchmark(preset="smoke")` của TV3 để chạy CVM-A1 thật khi API TV3 đã có.
- `CUSTOM_SWEEP`: gọi API TV3 với cấu hình trong cell. Cần đặt `RUN_CUSTOM = True` để xác nhận chạy; cell mặc định chỉ kiểm tra và xem trước số lượt.

Nếu API TV3 hoặc TV4 chưa có trong checkout, notebook hiện trạng thái `CHỜ API TV3` hoặc `CHỜ API TV4` và không tạo dữ liệu giả. Khi API TV4 có mặt, notebook dùng `analyze_jupyter_results(...)`; trước đó chế độ P0 hiển thị các bảng và hình đã lưu cùng nhãn cho biết API chưa được tích hợp.

## Kết quả và xuất tệp

RAW CSV, sidecar, bảng tổng hợp và PNG được sao chép hoặc tạo trong `notebooks/exports/`. Notebook hiển thị đường dẫn và môi trường ghi trong provenance. P0 dùng nguyên hiện vật Windows đã lưu; smoke/custom ghi hiện vật riêng do API TV3 trả về.

## Trạng thái kiểm tra Linux

### Nhật ký kiểm tra ngày 18/11/2026

- Cơ sở: worktree sạch từ `origin/develop` tại `76c1799`.
- Môi trường: Linux x86_64, kernel `7.0.0-43-generic`; `systemd-detect-virt` trả `none`; Python `3.14.4`; GCC `15.2.0`.
- Gói đã cài từ `requirements-jupyter.txt`: NumPy `2.5.5`, SciPy `1.18.1`, Matplotlib `3.11.2`, pandas `3.1.1`, JupyterLab `4.6.6`, ipykernel `7.4.0`.
- Lệnh cài: `python3 -m venv /tmp/cvm-tv2-jupyter-venv`, kích hoạt môi trường, rồi `python -m pip install -r requirements-jupyter.txt`.
- Đã thực thi toàn bộ cell bằng `nbclient` trong kernel Python. `READ_EXISTING_P0` qua validator, hiển thị 135 bản ghi, 15 nhóm và ba PNG. `SMOKE_LINUX` hiện `CHỜ API TV3`; `CUSTOM_SWEEP` chỉ xem trước cấu hình khi `RUN_CUSTOM = False`.
- Hệ thống báo không phát hiện máy ảo; trạng thái máy vật lý Ubuntu dual boot và thao tác chọn kernel trong giao diện JupyterLab chưa được xác minh độc lập.

**CHƯA XÁC MINH end-to-end trên Linux native theo yêu cầu nhóm.** API chạy notebook TV3 chưa có trong checkout này; smoke/custom thật chưa chạy. Sau khi ghép API TV1/TV3/TV4, cần kiểm tra trên máy Ubuntu dual boot, xác thực sidecar và lưu log gồm phiên bản Python, GCC, lệnh chạy, trạng thái validator và đường dẫn đầu ra. Không dùng kết quả P0 Windows để báo cáo số đo Linux.
