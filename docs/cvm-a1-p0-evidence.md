# Kiểm thử CVM-A1 GĐ1

Nhánh `feature/cvm-a1-metrics` ·

## Phạm vi

Bản này bổ sung phép đo thời gian và đầu ra `csv-v2` cho CVM-A1. Các ca kiểm thử đối chiếu việc xóa ID cũ trước khi lấy mẫu lại, giảm mẫu, cập nhật `p` và abort theo Algorithm 1.

| Chỉ số | Cách tính |
|---|---|
| `algorithm_runtime_ms` | Cộng thời gian khởi tạo A1, xử lý từng ID và lấy kết quả. Việc đọc và parse ID, khởi động tiến trình và ghi CSV nằm ngoài khoảng đo. |
| `peak_sample_size` | Số ID lớn nhất trong tập mẫu, tính cả lúc vừa chạm ngưỡng trước khi giảm mẫu. |
| `halving_count` | Số lần giảm mẫu, tính cả lần dẫn đến abort. |
| `s` | Ngưỡng thực dùng, tính từ `m`, `epsilon` và `delta` theo paper. |

Xem [README](../README.md) để build, chạy và xem thứ tự các trường `csv-v2`.

## Kết quả kiểm thử

| Môi trường | Kết quả |
|---|---|
| Windows, MSVC 19.41 x64 | 14/14 unit test C++ và 21/21 ca CLI pass. `ruff check .` và `ruff format --check .` đều pass. |
| Linux, GCC 14.2 | Build thành công, 14/14 unit test C++ và 21/21 ca CLI pass. |

Bộ test có luồng toàn ID trùng, toàn ID khác nhau và luồng lặp. Ca chạy lại cùng seed cho cùng kết quả và các chỉ số đếm.

| Ca kiểm tra | Kết quả |
|---|---|
| Chạy thật với `10, 20, 10, 30`, `m = 4`, `eps = 0.05`, `delta = 0.01`, seed `42` | `success,3,0.0235,3,0,55891` |
| Ép abort trong unit test | Dòng `csv-v2` có trạng thái `algorithm_abort` và ô `estimate` trống. |
| Chỉ gửi 3 ID khi khai báo `m = 4` | Mã thoát `1`, stdout trống, stderr báo `execution_error`. |
| Chủ động chờ giữa hai ID | Toàn lượt mất khoảng `410 ms`, phần xử lý A1 ghi nhận `0.0152 ms`. |

[Unit test C++](../tests/cpp/test_a1.cpp) · [Script kiểm thử CLI](../tests/cpp/check_cvm_core.py)

Full pytest trên Windows dừng ở bước import `fcntl` của bộ ghi CSV trên `develop`.

## Nghiệm thu với runner

TV3 xác nhận định dạng `csv-v2` và chạy một stream bằng runner thật. Bổ sung link log hoặc một dòng CSV từ lượt chạy đó vào mục này khi có kết quả.