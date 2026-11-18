# Thiết kế thực nghiệm Time/Space của CVM-A1

## Ma trận P0

Ma trận chuẩn nằm trong [benchmark_plan_timespace.csv](../experiments/benchmark_plan_timespace.csv). Notebook TV2 đọc trực tiếp các dòng P0 từ tệp này; số tham số không được khai báo lại trong notebook.

Thiết kế giữ cố định miền giá trị `n`, `ε`, `δ` và lịch seed theo kế hoạch. Độ dài `m` tăng theo hệ số 4 để tạo các mức cách đều trên thang log₂. Workload `all_duplicate` dùng `F₀=1`, `uniform` dùng `F₀=m/4`, và `all_distinct` dùng `F₀=m`. `n` bằng `m` lớn nhất trong P0 để mọi cấu hình `all_distinct` thỏa `n ≥ m`. Vì `F₀` thay đổi theo workload, so sánh workload phản ánh kết hợp phân bố và số phần tử phân biệt, không cô lập riêng ảnh hưởng của phân bố. Ngưỡng `s` được tính bằng `compute_cvm_threshold`; cột `s_reference` trong kế hoạch được kiểm tra với công thức này.

P0 gồm 15 cấu hình, mỗi cấu hình có 9 trial. Đây là giao thức đo đã định trước, không phải chứng minh rằng 9 lượt đủ cho suy luận thống kê. Báo cáo kết quả P0 nên mô tả số đo và độ phân tán quan sát được; mọi kết luận xác suất cần thiết kế cỡ mẫu riêng.

## Dữ liệu và phân tích

Bộ dữ liệu P0 Linux được liệt kê tại [manifest](../notebooks/data/linux_p0/manifest.json). Manifest chứa đường dẫn tương đối, thông số cấu hình, số record và SHA-256 của mỗi RAW/sidecar. Giữ nguyên các tệp này để validator TV4 có thể đối chiếu checksum và protocol.

Notebook dùng API `run_jupyter_benchmark` của TV3 cho phép đo mới. TV4 xác thực từng RAW/sidecar, tổng hợp các lượt và tạo hình runtime lõi, peak RSS tiến trình C++ và peak sample. `verified_real` xác nhận dữ liệu khớp protocol và provenance đã khai báo; nhãn này không tự xác thực độc lập nguồn tạo dữ liệu.

Runtime lõi, thời gian đầu-cuối, RSS và peak sample là các đại lượng riêng. RSS đo tiến trình C++, không gồm Python/Jupyter. Bảng và hình mô tả các cấu hình đã đo; kết luận về độ phức tạp tiệm cận cần lập luận riêng về chi phí cập nhật, thinning và sức chứa mẫu.

## Chạy và xuất

Cài môi trường, mở notebook và chọn chế độ theo [hướng dẫn notebook](../notebooks/README.md). `READ_EXISTING_P0` đọc manifest nêu trên. `SMOKE_LINUX` và `CUSTOM_SWEEP` gọi Runner thật; phép đo mới chỉ chạy khi kiểm tra môi trường Ubuntu/Linux đạt yêu cầu.
