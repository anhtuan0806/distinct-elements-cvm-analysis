# API Jupyter Adapter

TV3 cung cấp `run_jupyter_benchmark(...)` để notebook gọi Runner/C++ và ghi RAW CSV cùng sidecar provenance. Notebook TV2 gọi API theo từng cấu hình P0 từ [kế hoạch benchmark](../experiments/benchmark_plan_timespace.csv), sau đó chuyển các cặp dữ liệu qua API TV4.

## Ví dụ smoke

```python
from pathlib import Path
from src.jupyter_adapter import run_jupyter_benchmark

result = run_jupyter_benchmark(
    preset="smoke",
    output_dir=Path("run/real"),
    verbose=False,
)
```

Preset smoke chỉ chạy khi notebook chọn `SMOKE_LINUX`; chế độ Run All mặc định đọc P0 đã lưu. Các giá trị P0 không được khai báo lại trong tài liệu này.

## Kết quả trả về

- `csv_path`: đường dẫn RAW CSV.
- `sidecar_path`: sidecar JSON cùng checksum, cấu hình, phiên bản và môi trường đo.
- `records_count`: số lượt được ghi.
- `configs_count`: số cấu hình của lần gọi.
- `to_dataframe`: DataFrame đọc từ RAW CSV.

Khi gọi API độc lập, thư mục mặc định là `results/real/jupyter/`. Notebook TV2 chỉ định thư mục đầu ra bên ngoài kho mã. API phân tích TV4 xác thực RAW và sidecar trước khi tổng hợp hoặc vẽ.
