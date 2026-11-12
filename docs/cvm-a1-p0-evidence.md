# Kiểm thử CVM-A1 GĐ1

Kết quả ban đầu từ nhánh `feature/cvm-a1-metrics`. Phần xác minh ngày 12/11/2026
dùng `develop` tại `85d6599` cùng thay đổi TV1 cục bộ.

## Phạm vi

Bản này bổ sung phép đo thời gian và đầu ra `csv-v2` cho CVM-A1. Các ca kiểm thử đối chiếu việc xóa ID cũ trước khi lấy mẫu lại, giảm mẫu, cập nhật `p` và abort theo Algorithm 1.

| Chỉ số | Cách tính |
|---|---|
| `algorithm_runtime_ms` | Cộng thời gian khởi tạo A1, xử lý từng ID và lấy kết quả. Việc đọc và parse ID, khởi động tiến trình và ghi CSV nằm ngoài khoảng đo. |
| `peak_sample_size` | Số ID lớn nhất trong tập mẫu, tính cả lúc vừa chạm ngưỡng trước khi giảm mẫu. |
| `halving_count` | Số lần giảm mẫu, tính cả lần dẫn đến abort. |
| `s` | Ngưỡng thực dùng, tính từ `m`, `epsilon` và `delta` theo paper. |

Xem [hướng dẫn CVM-A1](README.md) để build, chạy và xem thứ tự các trường `csv-v2`.

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

## Xác minh ngày 12/11/2026

Windows, Python 3.14.3 và MinGW GCC 12.1.0. Các binary được build với
`-std=c++17 -Wall -Wextra -Werror -pedantic -Isrc`.

| Phép kiểm | Kết quả |
|---|---|
| C++ unit test | 14/14 đạt. Trước bản sửa serializer, regression abort legacy lỗi vì nhận `0` thay cho ô trống. |
| CLI suite | 21/21 đạt. Luồng `10,20,10,30` trả `success,3,0.016199999999999999,3,0,55891`. Khoảng chờ stdin `400,478 ms` nằm ngoài thời gian thuật toán báo `0,030 ms`. |
| `runner.py` với binary chuẩn, `m = n = F0 = 4`, seed 42 | RAW có 24 cột. Dòng `success` ghi estimate `4.00`, thời gian thuật toán `0.014 ms`, peak `4`, halving `0`, `s = 55891`. |
| Fixture C++ qua Runner | Tiến trình exit `0`, stdout `algorithm_abort,,0.11360000000000001,166,1,166`. Cả hai lượt Runner ghi `algorithm_abort`, estimate và hai sai số rỗng, peak `166`, halving `1`, `s = 166`. |
| Full pytest trong bản sao đường dẫn ASCII | `64 passed, 3 failed, 1 skipped`, thêm `12 subtests passed`. Ba lỗi Windows ở `msvcrt.LK_UNLCK` thuộc CSV writer của TV3. |

Với `m = 256`, `epsilon = delta = 0.9`, `s = 166`. Binary chuẩn chạy luồng `0..255`
với seed `42` trả `success`, estimate `274`, peak `166` và halving `1`. Theo
[Claim 3 của paper](https://arxiv.org/html/2301.10191v2#S2.SS1), với các coin độc lập,
cận hợp của xác suất abort ở cấu hình này là `256 × 2⁻¹⁶⁶`, xấp xỉ `2,74 × 10⁻⁴⁸`.
Fixture dùng callback test hiện có để tái hiện kết quả giữ lại toàn bộ mẫu. Abort
với RNG mặc định của binary phát hành chưa được quan sát.

## Nghiệm thu với runner

TV3 cần xác nhận hợp đồng `csv-v2` và dùng hoặc đối soát `s` từ stdout của lõi.
`src/cvm/executor.py` hiện bỏ giá trị cột thứ sáu. `src/csv_writer.py` ghi `s` từ
`ExperimentConfig`, nên giá trị có thể lệch ngưỡng thực tế khi dùng API trực tiếp.
