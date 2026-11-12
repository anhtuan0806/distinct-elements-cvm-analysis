# Runner TV3 Giai đoạn 1

Runner giữ header RAW P0 gồm 24 cột. Dùng đường dẫn CSV mới cho lượt đầu tiên.
Những file RAW hoặc sidecar của phiên bản cũ được giữ để đối chiếu lịch sử. Runner
từ chối append vào chúng vì thiếu bằng chứng provenance và không tự chuyển đổi.

## Chạy và tiếp tục batch

Từ thư mục gốc dự án, dùng Python 3.10 trở lên và compiler C++17.

```powershell
python runner.py --m 256 --n 256 --f0 256 --workload all_distinct --eps 0.9 --delta 0.9 --seed 42 --trials 2 --out results/real/phase1-smoke.csv
python runner.py --m 256 --n 256 --f0 256 --workload all_distinct --eps 0.9 --delta 0.9 --seed 42 --trials 2 --out results/real/phase1-smoke.csv
python runner.py --dry-run --out results/synthetic/phase1-schema.csv
```

Lệnh real thứ hai bỏ qua hai trial đã hoàn tất. Runner dùng khóa logic gồm phiên
bản protocol, SHA-256 binary, SHA-256 generator, phiên bản Python, algorithm,
workload, cấu hình, chỉ số trial và hai seed. Mỗi lần thử có UUID riêng. Success
và algorithm abort hoàn tất trial. Lỗi thực thi hoặc tài nguyên được giữ trong lịch
sử và có thể chạy lại cùng lệnh. Dùng file khác khi cần bộ đo độc lập trên máy khác.

Runner chuẩn hóa đường dẫn, bảo vệ thư mục real/synthetic và từ chối đổi chế độ
của CSV đã có. Dry-run xuất hai dòng gắn nhãn `CVM-A1-dryrun`. Các ô thời gian
và RAM mô phỏng để trống. `--out` mặc định theo mode. Các đường dẫn mặc định
trong checkout này có dữ liệu lịch sử, vì vậy hãy dùng một tên file mới.

## RAW và sidecar

- `s` lấy từ cột thứ sáu của C++ `csv-v2`. Nếu ngưỡng Python và C++ khác nhau,
  trial có status `execution_error`, ghi ngưỡng thực đã xác định và log cả hai
  giá trị. Khi Core chưa báo ngưỡng, cột `s` của lần lỗi để trống.
- `estimate`, signed RE và ARE để trống khi status khác success.
- `algorithm_runtime_ms` là thời gian từ C++ tính bằng ms.
  `end_to_end_runtime_ms` đo thêm chuẩn bị input và thực thi tiến trình.
  `peak_sample_size` là số ID tối đa trong tập mẫu. `halving_count` đếm số lần giảm mẫu.
- `process_peak_memory_bytes` là peak RSS của child. Auto-build liên kết hook
  TV3 để Core đọc `VmHWM` từ `/proc/self/status` trên Linux và đổi KiB sang bytes,
  hoặc gọi `GetProcessMemoryInfo` trên Windows ngay trước khi thoát. Chỉ số gồm
  working set của Core, runtime và allocator, loại bộ nhớ của Generator Python.
  Binary tự build thiếu hook, tiến trình chết trước khi báo số đo và nền tảng
  chưa hỗ trợ sẽ ghi ô trống.
- Sidecar ghi mode, schema, SHA-256 RAW, kích thước, số dòng và khoảng dòng của
  từng batch. Khoảng dòng đếm từ 1 và bỏ header. Mỗi batch có UUID, thời gian,
  cấu hình/seed, commit gốc, hash các file nguồn đang chạy, hash binary và
  thông tin OS, Python, CPU, compiler/build flags khi xác định được.
  Với binary ngoài auto-build, compiler và cờ build để `unknown` nếu thiếu receipt.
- Runner giữ khóa file trong suốt batch. Mỗi append ghi trước bản ghi dự kiến
  trong sidecar, sau đó flush CSV và chốt sidecar bằng thay file nguyên tử.
  Sau gián đoạn, chạy lại cùng lệnh. Runner chỉ nối tiếp phần ghi dở khi khớp
  với byte đã lưu trong sidecar. Nếu dữ liệu lệch, Runner báo lỗi và giữ file
  để kiểm tra. Không sửa thủ công sidecar để hợp thức hóa dữ liệu cũ.

Mã thoát `0` cho batch hợp lệ, kể cả algorithm abort và trial đã được bỏ qua.
Mã thoát `1` khi cấu hình, dữ liệu, build hoặc một trial bị lỗi. Lỗi cú pháp CLI trả `2`. Runner ghi stderr
của Core kèm chỉ số trial vào log. Runner chỉ dùng `resource_failure` khi có
bằng chứng rõ như Python ném `MemoryError`.

## Kiểm thử

```powershell
python -m pytest tests/test_tv3_contract.py tests/test_tv3_platform.py tests/test_csv_writer_safety.py
```

Auto-build chạy compiler với đường dẫn nguồn tương đối từ project root, bao gồm
đường dẫn Windows có dấu và dấu cách. Nếu đã có binary cũ, build lại bằng
`python -c "from src.cvm.build import build_cvm_core; build_cvm_core(force=True)"`. Runner ghi dữ liệu thử vào thư mục tạm trong
test. Các kết quả smoke ở đây dùng để xác nhận pipeline và đơn vị.
