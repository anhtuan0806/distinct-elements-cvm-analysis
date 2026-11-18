# Chạy notebook phân tích time/space

Notebook chính: `BIG_O_TimeSpace.ipynb`. Notebook tích hợp API chạy thực nghiệm của TV3 và API phân tích của TV4. Các phép đo mới chỉ được chạy trên Linux native Ubuntu.

## Yêu cầu

- Ubuntu Linux native; không dùng WSL, máy ảo hoặc Colab để xác nhận phép đo Linux.
- Python 3.10 trở lên.
- GCC hoặc Clang có hỗ trợ C++17 để biên dịch CVM-A1.
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

Trong JupyterLab, mở `notebooks/BIG_O_TimeSpace.ipynb`, chọn kernel **Python (CVM analysis)**, rồi chọn **Run → Run All Cells**. Notebook dùng `sys.executable` của kernel hiện hành và dò thư mục gốc qua `pyproject.toml`; không cần sửa đường dẫn theo máy.

## Chế độ chạy

Cell cấu hình mặc định đặt `MODE = "READ_EXISTING_P0"`. Run All chỉ đọc bộ P0 đã lưu, xác thực RAW/sidecar qua API TV4, rồi hiển thị 135 bản ghi, 15 nhóm thống kê và ba hình được tạo từ dữ liệu đã xác thực. Sidecar P0 hiện ghi môi trường phép đo Windows; hệ điều hành của kernel được hiển thị riêng.

- `READ_EXISTING_P0`: đọc và phân tích P0 đã lưu. Chế độ này không chạy benchmark.
- `SMOKE_LINUX`: gọi `src.jupyter_adapter.run_jupyter_benchmark(preset="smoke")`, sau đó gửi RAW/sidecar cho TV4.
- `CUSTOM_SWEEP`: xem trước số cấu hình và lượt khi `RUN_CUSTOM = False`. Đặt `RUN_CUSTOM = True` để gọi TV3 với `CUSTOM_M`, `CUSTOM_N`, `CUSTOM_F0`, `CUSTOM_EPSILON`, `CUSTOM_DELTA`, workload, seed và số trial đã cấu hình.

TV2 kiểm tra miền giá trị cấu hình custom; TV3 kiểm tra lại các ràng buộc trước khi chạy. Với phép đo mới, notebook xác nhận Ubuntu, Linux, WSL và môi trường máy ảo/container trước khi gọi TV3. TV4 xác thực dữ liệu và sidecar; notebook dừng nếu kết quả không được phân loại `verified_real`.

## Kết quả và tệp xuất

Mỗi lượt tạo thư mục riêng dưới `notebooks/exports/`. TV3 lưu RAW CSV và sidecar trong thư mục `real/`. TV4 tạo thư mục phân tích riêng bên dưới `analysis/`, gồm CSV tổng hợp, báo cáo Markdown và các PNG runtime, RSS, peak sample. Notebook hiển thị trạng thái các lượt, bảng RAW, bảng tổng hợp, provenance, đường dẫn và hình. Số PNG phụ thuộc dữ liệu đầu vào; bộ P0 có ba hình.

Để xuất CSV hoặc PNG, mở đường dẫn được notebook in ra và sao chép tệp cần dùng. RAW và sidecar của mỗi lần chạy được giữ cùng nhau để có thể kiểm định lại. Mỗi thư mục lượt chạy có tên riêng, không ghi đè kết quả trước.

## Nhật ký xác minh

### Nhật ký ngày 18/11/2026

- Checkout sạch tại commit `5a3ef09`; cài mới từ `requirements-jupyter.txt` trong virtual environment bằng các lệnh ở trên. `pip check` không báo dependency lỗi.
- Máy kiểm tra: Ubuntu 26.04.1 LTS, Linux `7.0.0-43-generic`, Python 3.14.4, GCC 15.2.0. Bộ kiểm tra notebook nhận diện Ubuntu/Linux; không phát hiện WSL, máy ảo hoặc container (`systemd-detect-virt --vm/--container`: `none`). Trạng thái dual boot vật lý không được xác minh độc lập.
- Phiên bản môi trường: JupyterLab 4.6.6, ipykernel 7.4.0, NumPy 2.5.5, SciPy 1.18.1, Matplotlib 3.11.2, pandas 3.1.1. Đã đăng ký và chọn kernel `Python (CVM analysis)` trong JupyterLab.
- **Run All trên giao diện JupyterLab:** chế độ mặc định `READ_EXISTING_P0` hoàn tất; TV4 báo `verified_real`, 135/135 success, 15 nhóm và ba hình runtime/RSS/peak sample. Đây là phân tích trên Linux đối với RAW P0 có provenance Windows.
- **Chạy bằng kernel mới trong checkout sạch:** `READ_EXISTING_P0`, `SMOKE_LINUX`, `CUSTOM_SWEEP` ở chế độ xem trước và custom sweep nhỏ đều hoàn tất. Smoke tạo 2 bản ghi Linux `verified_real` và ba hình. Custom tạo 4 bản ghi Linux `verified_real` và sáu hình cho hai lát cắt cấu hình.
- Dùng kernel notebook qua `nbclient` cho bốn chế độ trong checkout sạch; kiểm định độc lập của TV3/TV4 xác nhận RAW và sidecar. CSV, báo cáo và PNG của lần kiểm tra được ghi vào thư mục tạm, không đưa vào kho mã.

Kết quả P0 trên Linux chỉ xác nhận việc đọc và phân tích dữ liệu. Không dùng P0 Windows để báo cáo số đo Linux.
