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

- Trước mỗi trial cần thực thi, Runner gọi cùng executable và tham số với
  `--output-format threshold-v1`. Core khởi tạo A1 và trả một dòng
  `threshold-v1,<s>` trước khi đọc stdin. Truy vấn nằm ngoài thời gian đo
  trial. Runner kiểm `csv-v2` có đúng một dòng và sáu trường, kiểm status,
  estimate, giới hạn sample/halving và đối chiếu chính xác `s` với kết quả
  truy vấn. Hai giao thức yêu cầu ngưỡng nguyên dương trong miền uint64.
  Nếu `s` từ lượt chạy khác kết quả truy vấn, trial là `execution_error`
  và cột `s` để trống. RAW của trial hợp lệ ghi `s` từ `csv-v2`.
- Python lưu `configuration.s` làm tham chiếu. Caller Python truyền ngưỡng
  khác tham chiếu phải khớp giá trị Core. Hai chế độ C++ dùng cùng constructor
  và cho phép các toolchain có độ chính xác `long double` khác nhau. Kiểm tra
  này xác nhận hai phản hồi nhất quán với nhau. Lỗi chung trong công thức C++
  cần kiểm thử Core hoặc đối chứng độc lập.
- Với lượt chạy thật, resume nhận diện trial bằng phiên bản binary/generator/Python,
  cấu hình đầu vào và hai seed. `s` trong RAW là kết quả của Core nên nằm ngoài
  khóa resume. Sidecar vẫn giữ `configuration.s` làm giá trị tham chiếu.
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
  Lượt real yêu cầu build receipt có compiler, cờ build và SHA-256 khớp
  executable. Với mỗi trial mới, Runner kiểm SHA-256 của byte đọc từ binary,
  rồi dùng một bản sao tạm riêng cho cả query và lượt đo. Việc sao chép nằm
  ngoài thời gian đo. Runner đối chiếu lại hash bản sao và binary gốc trước
  khi ghi record để phát hiện thay đổi trong batch.
  Receipt cung cấp định danh byte và nhãn build. Xác nhận nguồn của receipt
  và executable là trách nhiệm của quy trình build. Cùng byte binary và cùng
  cấu hình vẫn resume khi chỉ nhãn receipt đổi, giữ nhãn đo gốc trong RAW.
- Runner giữ khóa file trong suốt batch. Mỗi append ghi trước bản ghi dự kiến
  trong sidecar, sau đó flush CSV và chốt sidecar bằng thay file nguyên tử.
  Trước khi index hoặc khôi phục, Runner kiểm `batch.version` khớp SHA-256
  binary, SHA-256 Generator và phiên bản Python trong batch. Nó đối chiếu
  cấu hình, trial, seed và nhãn build với các dòng RAW. Metadata mâu thuẫn
  làm lệnh thoát lỗi và giữ hai tệp để kiểm tra. Sau gián đoạn, chạy lại cùng
  lệnh để khôi phục phần ghi dở khớp với byte đã lưu trong sidecar.
  Trial đã hoàn tất bằng binary cũ vẫn có thể được nhận diện theo hash gốc.
  Nếu dùng binary mới, chỉ dùng cùng tệp khi muốn ghi batch với version mới.

Mã thoát `0` cho batch hợp lệ, kể cả algorithm abort và trial đã được bỏ qua.
Mã thoát `1` khi cấu hình, dữ liệu, build hoặc một trial bị lỗi. Lỗi cú pháp CLI trả `2`. Runner ghi stderr
của Core kèm chỉ số trial vào log. Runner chỉ dùng `resource_failure` khi có
bằng chứng rõ như Python ném `MemoryError`.

## Kiểm thử

```powershell
python -m pytest tests/test_tv3_contract.py tests/test_tv3_platform.py tests/test_csv_writer_safety.py
```

Auto-build chạy compiler với đường dẫn nguồn tương đối từ project root, bao gồm
đường dẫn Windows có dấu và dấu cách. Binary cũ thiếu `threshold-v1` cần build lại bằng
`python -c "from src.cvm.build import build_cvm_core; build_cvm_core(force=True)"`. Runner ghi dữ liệu thử vào thư mục tạm trong
test. Workflow Ubuntu chạy pytest trên Python 3.10–3.12 và chạy bộ C++
standalone trên Python 3.12, gồm CLI và fixture abort.
