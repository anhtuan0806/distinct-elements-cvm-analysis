# Hướng dẫn sử dụng CVM-A1

Chạy các lệnh dưới đây từ thư mục gốc dự án. [Giới thiệu dự án](../README.md)

## Cài đặt môi trường

Yêu cầu: Python >= 3.10; phần C++ dùng compiler hỗ trợ C++17 (GCC/Clang hoặc MSVC).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Chạy kiểm thử

```bash
pytest
```

## Lõi CVM-A1 và kiểm thử C++ trên Windows

Lõi tại `src/cvm/a1.hpp` và `src/cvm/a1.cpp`, unit test tại `tests/cpp/test_a1.cpp`.
Chỉ dùng C++17 và thư viện chuẩn, theo Algorithm 1, trang 2 của
[paper arXiv:2301.10191v2](https://arxiv.org/pdf/2301.10191v2#page=2).

Chạy từ thư mục gốc repo trong terminal PowerShell của VS Code, với Visual Studio 2022
Community đã cài thành phần C++:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\Launch-VsDevShell.ps1' -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
New-Item -ItemType Directory -Force -Path build\a1 | Out-Null
cl /nologo /std:c++17 /EHsc /W4 /WX /permissive- /utf-8 /Isrc src\cvm\a1.cpp tests\cpp\test_a1.cpp /Fo:build\a1\ /Fe:build\a1\test_a1.exe
if ($LASTEXITCODE -ne 0) { throw 'CVM-A1 build failed' }
& .\build\a1\test_a1.exe
if ($LASTEXITCODE -ne 0) { throw 'CVM-A1 tests failed' }
```

File build nằm trong `build/a1/`, đã được Git bỏ qua. Đây là bộ test C++ độc lập;
`pytest` hiện chỉ chạy test Python. Chưa tích hợp C++ vào CI.

Build/test tương đương bằng GCC trên Linux hoặc shell có `g++` hỗ trợ C++17:

```bash
mkdir -p build/a1
g++ -std=c++17 -Wall -Wextra -Werror -pedantic -Isrc src/cvm/a1.cpp tests/cpp/test_a1.cpp -o build/a1/test_a1
./build/a1/test_a1
g++ -std=c++17 -Wall -Wextra -Werror -pedantic -Isrc src/cvm/a1.cpp src/cvm_core.cpp -o build/a1/cvm_core
python3 tests/cpp/check_cvm_core.py build/a1/cvm_core --log build/a1/metrics-smoke-gcc.json
```

Đã build và kiểm thử với MSVC 19.41.34120 x64 trên Windows và GCC 14.2 trên Linux. Cả hai dùng C++17.

Khởi tạo `cvm::A1(m, epsilon, delta, seed)`, gọi `update(id)` cho từng `std::uint64_t`,
rồi gọi `result()` sau đúng `m` lượt đọc (tính cả ID lặp), hoặc ngay khi `aborted()` là
`true`. Lõi chỉ giữ tập mẫu và trạng thái, không lưu toàn bộ luồng. `result()` trả
`A1Status::success` kèm `estimate`, hoặc `A1Status::aborted` và `estimate == std::nullopt`.
Không tự thử lại lượt giảm mẫu hay khởi động lại sau abort.

`epsilon` và `delta` phải hữu hạn và thuộc `(0, 1)`, kể cả khi `m = 0`; tham số sai
báo `std::invalid_argument`. Ngưỡng ngoài phạm vi biểu diễn/sức chứa tập mẫu, xác suất
bị underflow hoặc kết quả ngoài phạm vi `double` báo `std::overflow_error`, riêng với
abort của thuật toán. Gọi kết quả khi chưa đủ luồng hoặc update sau abort báo
`std::logic_error`; update vượt `m` báo `std::length_error`.

Với luồng rỗng (`m = 0`), kết quả là `0`: **đây là quy ước triển khai cần xác nhận với
nhóm**, không áp dụng công thức log của paper tại `m = 0`.

Nguồn mặc định là `std::mt19937_64` khởi tạo bằng `seed` và các quyết định Bernoulli
độc lập. Cùng dữ liệu, tham số và seed tái hiện kết quả trên cùng bản build; không
cam kết giống nhau giữa các thư viện chuẩn/compiler. Tham số tùy chọn `RandomDecision`
cho phép test điều khiển từng coin mà vẫn giữ nguyên công thức ngưỡng. Test ép nhánh
dùng `m = 256`, `epsilon = delta = 0.9`, cho `thresh = 166`.

## Chương trình `cvm_core` cho runner Python

`src/cvm_core.cpp` tái sử dụng lõi A1. Sau khi nạp Developer PowerShell ở trên, build
từ thư mục gốc repo:

```powershell
New-Item -ItemType Directory -Force -Path build\a1 | Out-Null
cl /nologo /std:c++17 /EHsc /W4 /WX /permissive- /utf-8 /Isrc src\cvm\a1.cpp src\cvm_core.cpp /Fo:build\a1\ /Fe:build\a1\cvm_core.exe
if ($LASTEXITCODE -ne 0) { throw 'cvm_core build failed' }
```

Bắt buộc truyền `--m`, `--eps`, `--delta`, `--seed` (mỗi tham số một giá trị).
`m` và `seed` là số nguyên không dấu 64 bit hệ thập phân. `stdin` có mỗi dòng một ID
`uint64_t` thập phân; chấp nhận khoảng trắng quanh ID, không chấp nhận dòng trống,
dấu `+`/`-` hoặc nhiều ID trên một dòng. Chương trình xử lý tối đa `m` lượt đọc, tính
cả ID lặp, và dừng ngay khi A1 abort; không đọc/kiểm tra phần dữ liệu còn lại.

Không truyền `--output-format`: giữ nguyên **một dòng CSV 4 cột, không có header**
cho runner TV3 hiện tại, đúng thứ tự:

```text
estimate,abort,max_buffer_size,halving_count
```

- `estimate`: số ước lượng; khi abort dùng `0` làm giá trị giữ chỗ cho runner.
- `abort`: `TRUE` hoặc `FALSE`; abort vẫn là kết quả hợp lệ, exit code `0`.
- `max_buffer_size`: số ID lớn nhất trong mẫu ngay sau khi thêm ID, **trước giảm mẫu**.
- `halving_count`: tổng số lần chia đôi `p`, kể cả lần dẫn đến abort.

Thiếu/sai tham số, ID sai định dạng/ngoài phạm vi, hoặc thiếu ID trước khi đủ `m`
trong một lượt chưa abort: ghi lỗi vào `stderr`, không in CSV, exit code khác `0`.
Lỗi số học của lõi cũng được báo qua `stderr` với exit code khác `0`.
Mọi thông báo lỗi có nhãn `execution_error`.

Ví dụ gọi từ Python tại thư mục gốc repo:

```python
import subprocess

result = subprocess.run(
    [r"build\a1\cvm_core.exe", "--m", "4", "--eps", "0.05", "--delta", "0.01", "--seed", "42"],
    input="10\n20\n10\n30\n",
    text=True,
    capture_output=True,
    check=True,
)
```

Chạy thử trực tiếp trong PowerShell:

```powershell
"10", "20", "10", "30" | & .\build\a1\cvm_core.exe --m 4 --eps 0.05 --delta 0.01 --seed 42
```

### Hợp đồng nghiệm thu P0: `--output-format csv-v2`

Thêm `--output-format csv-v2` để dùng hợp đồng mới. `stdout` in trực tiếp đúng một
dòng dữ liệu 6 cột, **không in header**, theo thứ tự:

```text
status,estimate,algorithm_runtime_ms,peak_sample_size,halving_count,s
```

| Trường | Ý nghĩa |
|---|---|
| `status` | `success` hoặc `algorithm_abort`; cả hai trả exit code `0`. |
| `estimate` | Số ước lượng khi success; **ô trống** khi algorithm_abort. |
| `algorithm_runtime_ms` | Tổng thời gian khởi tạo A1, các lần `update(id)` và `result()`, đơn vị ms. |
| `peak_sample_size` | Dùng `max_buffer_size()`: peak số ID trong mẫu, gồm lúc vừa đầy trước giảm mẫu. |
| `halving_count` | Dùng `halving_count()`: số lần chia đôi p, gồm lượt dẫn tới abort. |
| `s` | Dùng `threshold()`: `ceil((12 / epsilon²) * log2(8m / delta))` khi `m > 0`. |

Timer dùng `std::chrono::steady_clock`: cộng duration của ba phần rồi đổi sang ms.
Mỗi ID được đọc và parse **trước** khi bắt đầu đo `update`; phép đo `result()` kết
thúc **trước** chuyển đổi, định dạng CSV và ghi stdout. Thời gian sinh stream, chờ
stdin, mở tiến trình và ghi CSV của runner nằm ngoài metric này. Đây là elapsed time
của các đoạn thuật toán, có overhead lấy mốc clock; không phải thời gian CPU hoặc
thời gian toàn lượt chạy executable.

`execution_error` trả mã `1`, ghi `execution_error` kèm thông báo vào stderr. Lỗi
phát hiện trước khi xuất kết quả để stdout trống, không xuất một dòng CSV lỗi.
Ví dụ: thiếu tham số, ID không phải uint64 thập phân, vượt phạm vi, EOF trước đủ m
khi chưa abort hoặc lỗi số học. Chưa thêm `n`: hiện chỉ kiểm tra miền `uint64_t`,
không yêu cầu miền ID từ generator. `m = 0` vẫn theo quy ước trả success, estimate 0,
peak 0, halving 0 và s = 0; quy ước luồng rỗng còn cần nhóm xác nhận.

Ví dụ trên MSVC (sau build ở trên):

```powershell
"10", "20", "10", "30" | & .\build\a1\cvm_core.exe --m 4 --eps 0.05 --delta 0.01 --seed 42 --output-format csv-v2
python tests\cpp\check_cvm_core.py build\a1\cvm_core.exe --log build\a1\metrics-smoke.json
```

Ví dụ trên GCC:

```bash
printf '10\n20\n10\n30\n' | ./build/a1/cvm_core --m 4 --eps 0.05 --delta 0.01 --seed 42 --output-format csv-v2
```

Với bốn ID này, estimate = 3, peak = 3, halving = 0, s = 55891. Ví dụ dòng success
thực tế trên MSVC (thời gian sẽ thay đổi giữa các lượt):

```text
success,3,0.0235,3,0,55891
```

Bộ C++ test dùng nguồn ngẫu nhiên điều khiển được để ép abort, rồi kiểm tra chính
hàm xuất CSV dùng trong executable. Ví dụ fixture với runtime 1.25 ms:

```text
algorithm_abort,,1.25,166,1,166
```

`tests/cpp/check_cvm_core.py` chạy executable thật, kiểm tra 6 cột, lỗi EOF/tham số/ID,
tương thích 4 cột và lặp lại cùng input/seed. Script còn gửi input có khoảng chờ
giữa hai ID, log thời gian toàn lượt cùng `algorithm_runtime_ms` để kiểm tra phạm vi
timer; không dùng ngưỡng thời gian tuyệt đối sát trong unit test. Trên cùng bản build,
input/seed/epsilon/delta/m giống nhau phải cho cùng status, estimate, peak, halving
và s; chỉ thời gian được phép thay đổi.

### Chi phí thuật toán và bằng chứng P0

Với thao tác bảng băm `std::unordered_set` có chi phí trung bình O(1), mỗi lượt đọc
xóa/lấy mẫu lại tốn O(1) kỳ vọng. Mỗi lượt giảm mẫu duyệt tối đa s ID, tốn O(s).
Vì vậy tổng thời gian kỳ vọng là **O(m + h s)**, trong đó h là số lượt giảm mẫu,
kể cả lượt dẫn tới abort. Đây không phải cận worst-case cho bảng băm khi va chạm xấu.

Bộ nhớ **tập mẫu O(s) theo số ID** (thực tế tối đa min(m, s)), gồm cả peak ngay trước
giảm mẫu; không lưu toàn bộ stream. Đây không phải RSS hoặc số byte bộ nhớ tiến trình;
nếu mỗi ID cần log2(n) bit thì riêng phần lưu ID tương ứng O(s log n) bit.

Checklist, lệnh đã chạy và kết quả thực tế được ghi tại
[bằng chứng P0 GĐ1](cvm-a1-p0-evidence.md). Còn chờ TV3/nhóm ghép hợp đồng mới
vào CSV thí nghiệm, xác nhận quy ước luồng rỗng và thống nhất CI C++.
