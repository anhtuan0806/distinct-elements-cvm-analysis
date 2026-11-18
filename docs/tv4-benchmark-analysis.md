# TV4 Giai đoạn 1 — Phân tích Time/Space của CVM-A1

Phép đo khảo sát runtime của lõi C++, peak RSS của tiến trình lõi và số phần tử tối đa trong tập mẫu khi độ dài luồng tăng. Thiết kế dùng ngưỡng mặc định của CVM-A1. [Thẻ nghiệm thu TV4](https://trello.com/c/kBDHp13f)

## Ma trận và thứ tự chạy

| Ưu tiên | Mục đích | m | n | Workload và F₀ | ε / δ | Lượt mỗi cấu hình |
|---|---|---|---:|---|---|---:|
| P0 | Đo xu hướng theo m và quan sát halving | 256, 1.024, 4.096, 16.384, 65.536 | 65.536 | all_duplicate với F₀=1, uniform với F₀=m/4, all_distinct với F₀=m | 0,5 / 0,05 | 9 |
| P1 | So sánh phân bố với cùng F₀/m | Như P0 | 65.536 | uniform và skewed với F₀=m/4 | 0,5 / 0,05 | 5 |
| P2 | Thử m lớn hơn và ngưỡng công thức khác | 65.536, 262.144 | 262.144 | all_distinct với F₀=m | 0,2 / 0,05 | 5 |

Trong P0, giữ n, ε, δ và lịch seed cố định. Tỷ lệ F₀/m cố định trong từng đường uniform và all_distinct. Với all_duplicate, F₀=1 nên tỷ lệ là 1/m. F₀ và s vì thế thay đổi theo quy luật đã ghi trong ma trận. So sánh giữa các workload P0 mô tả hiệu ứng gộp của phân bố và F₀. Uniform của Generator chọn ngẫu nhiên vị trí bảo đảm đủ F₀ rồi điền các vị trí còn lại bằng lấy mẫu đều.

P0 có 15 cấu hình × 9 lượt. Với trial t, seed Generator là 44.000+t−1 và seed CVM-A1 là 84.000+t−1. Các workload dùng chung lịch seed để tái lập thiết kế. Batch chạy tuần tự, thứ tự cấu hình được xáo trộn bằng seed 4404, trial tăng dần trong mỗi batch. Không chạy warm-up có tính vào P0. Smoke chạy riêng với 3 cấu hình ở m=256, 2 trial mỗi cấu hình. P1 và P2 là thiết kế bổ trợ chưa chạy.

| File | Vai trò |
|---|---|
| [benchmark_plan_timespace.csv](../experiments/benchmark_plan_timespace.csv) | Ma trận P0/P1/P2 và giá trị tham khảo s |
| [RAW smoke](../results/real/tv4_timespace_smoke_20261113.csv) · [sidecar](../results/real/tv4_timespace_smoke_20261113.metadata.json) | Xác nhận pipeline với 6 lượt thật |
| [RAW P0](../results/real/tv4_timespace_p0_20261113.csv) · [sidecar](../results/real/tv4_timespace_p0_20261113.metadata.json) | 135 lượt đo P0 |
| [Summary](../results/summary/timespace_summary.csv) | 15 nhóm thống kê |
| [Runtime](../results/summary/figures/timespace_runtime.png) · [RSS](../results/summary/figures/timespace_ram.png) · [Sample peak](../results/summary/figures/timespace_sample.png) | PNG 1.800 × 1.100 px, 200 DPI |

## Tái lập

Chạy tại thư mục gốc repo với Python ≥3.10 và compiler C++17 trong PATH. Cài thư viện theo README. Matplotlib đã được khai báo trong requirements. Với MinGW trên Windows, đặt TEMP và TMP tới một thư mục có quyền ghi và đường dẫn ASCII nếu gặp lỗi tạo tệp tạm của compiler.

~~~powershell
python -m pip install -r requirements-dev.txt
python -m scripts.generate_timespace_plan
python -m scripts.generate_timespace_plan --preview smoke --raw results/real/tv4_smoke_replay.csv
python -c "from src.cvm.build import build_cvm_core; build_cvm_core(force=True)"
python -m scripts.generate_timespace_plan --run smoke --raw results/real/tv4_smoke_replay.csv
python -m scripts.validate_results results/real/tv4_smoke_replay.csv
python -m scripts.generate_timespace_plan --preview P0 --raw results/real/tv4_p0_replay.csv
python -m scripts.generate_timespace_plan --run P0 --raw results/real/tv4_p0_replay.csv
python -m scripts.validate_results results/real/tv4_p0_replay.csv
python -m scripts.analyze_results results/real/tv4_p0_replay.csv --out results/summary/timespace_replay.csv
python -m scripts.plot_results results/real/tv4_p0_replay.csv --out-dir results/figures/replay
python -m pytest
~~~

Lệnh preview in mảng đối số thực thi. Dùng tên RAW mới cho mỗi bộ đo. Sidecar mặc định nằm cùng thư mục với RAW, hoặc chỉ định bằng --metadata trong validator, summary và plot. Giữ nguyên cặp RAW/sidecar theo tên đã ghi trong metadata và mở CSV bằng công cụ đọc giữ nguyên byte để bảo toàn checksum. Các bản hình bàn giao nằm ở results/summary/figures vì Git đang ignore results/figures.

## Môi trường và provenance

- Windows 11, build 26200, AMD Ryzen 7 8845H, 16 luồng logic. Windows báo 29.860.155.392 byte RAM khả dụng cho hệ điều hành tại mức tổng vật lý (27,81 GiB, GlobalMemoryStatusEx). Dung lượng DIMM lắp đặt chưa xác minh.
- Python 3.14.3, MinGW-w64 GCC 12.1.0, cờ -O3;-std=c++17;-Isrc, Matplotlib 3.11.2. Lõi được rebuild từ runner.py và src/ ở HEAD a4d6436aeb9736751e27d93edc383ed7590da7b5. git diff --exit-code HEAD -- runner.py src trả 0.
- SHA-256 Core 5887d9909d1811d3faaa2e7cdf1acd15abf5be93c030e6d3b0a11fbdf4c076a6.
- SHA-256 RAW P0 6f0e53217a217c8784419b0c800119660a6a43c9686fbaf3d6586dd368e4a726, 38.250 byte, 135 record, 15 batch.
- SHA-256 RAW smoke 500dc239bdfd9f1f6b2e14398e1fe4d5f9f865d1431b4b93bc990c83948cf9b4, 6 record, 3 batch.

Validator kiểm tra 24 cột TV3, status, kiểu và miền dữ liệu, UUID và trial trùng, giới hạn metric, null và RE. Đối chiếu sidecar theo protocol cvm-a1-tv3-v1, mode real, tên tệp, số byte, số record, SHA-256, khoảng batch, phiên bản, cấu hình, seed, compiler và flags. verified_real nghĩa là các kiểm tra nhất quán theo protocol đạt. Để xác lập nguồn của đợt chạy này, đối chiếu thêm log Runner, build receipt, hash binary và mã nguồn đã build. Sidecar và checksum có thể kiểm tra tính nhất quán nhưng không xác thực độc lập người tạo dữ liệu.

Ngưỡng s trong RAW lấy từ lõi. Validator cảnh báo nếu khác công thức Python, đặc biệt ở sát biên ceil. Summary và plot tự validate lại đầu vào. Hai RAW lịch sử có 33 record mỗi tệp. Tệp ở results/ thiếu sidecar, còn sidecar ở results/real/ dùng protocol cũ và khai 3 record. Validator đánh dấu cả hai là unverified và từ chối đưa vào phân tích. Dry-run hiện có được phân loại synthetic.

## Quy ước thống kê

- Group theo workload, m, n, F₀, ε, δ, s và định danh nguồn, binary, môi trường. Lấy các seed/trial lặp làm quan sát trong cùng nhóm.
- Runtime thuật toán, end-to-end, RSS và sample peak dùng lượt success. Runtime abort xuất ở cột abort_runtime riêng. Execution error và resource failure chỉ góp vào số đếm. Tỷ lệ success/abort dùng tổng số record làm mẫu số.
- RSS thiếu để rỗng và ram_count chỉ đếm phép đo hiện diện. Estimate và sai số của abort/error để rỗng. Khi F₀=0, cả hai relative error để rỗng. Stdev là độ lệch chuẩn mẫu, chỉ có khi đủ hai quan sát.
- Hình dùng median của các lượt success. Mỗi lát cắt n, ε, δ và môi trường có bộ hình riêng. Điểm RSS thiếu được bỏ trống. Đơn vị 1 MiB = 1.048.576 byte.

## Kết quả và giới hạn

| Workload | Median runtime ở m=256 → 65.536 (ms) | Peak sample median ở hai đầu | Lượt có halving / 45 |
|---|---:|---:|---:|
| all_duplicate | 0,0386 → 5,5356 | 1 → 1 | 0 |
| uniform | 0,0456 → 4,3376 | 64 → 1.120 | 27 |
| all_distinct | 0,0608 → 4,0469 | 256 → 1.120 | 36 |

Runtime trung vị tăng qua cả năm mức m ở từng workload. All_distinct bắt đầu halving từ m=1.024 và uniform từ m=4.096. Từ các mức này, peak sample của hai workload chạm s ở mỗi lượt đo. 135/135 lượt success, không ghi nhận abort hay lỗi. Phạm vi median peak RSS theo cấu hình là 4,617–4,691 MiB, chênh khoảng 76 KiB. Chênh lệch này được đo trên working set của cả tiến trình C++, gồm runtime và allocator. Sample peak đếm phần tử trong X trước thinning. Bộ nhớ Python sinh luồng và đóng gói stdin nằm ngoài RSS đã đo.

Timer C++ gồm khởi tạo, các lần update và lấy kết quả, bỏ qua parse/IPC. Ở m nhỏ, thời gian khởi tạo, timer, scheduling và cache dễ ảnh hưởng số đo. End-to-end còn bao gồm sinh luồng, tạo dữ liệu stdin và tiến trình con. P0 chạy trên một máy, với 9 trial mỗi cấu hình và một lát cắt ε/δ. Các kết quả mô tả phạm vi đã đo. Kết luận tiệm cận cần phân tích riêng chi phí cập nhật, các lần halving và sức chứa mẫu.

TV4 đã thu đủ P0 bằng Runner hiện có. TV2 cần xác nhận lát cắt nếu dùng bộ này làm chuẩn nhóm. TV3 có thể tiếp nhận RAW mới cùng sidecar để bàn giao theo quy trình nhóm. Các bước xác nhận này chưa được ghi nhận.
