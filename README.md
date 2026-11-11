# Phân tích độ phức tạp và cận sai số của thuật toán CVM trong bài toán đếm phần tử phân biệt trên luồng dữ liệu

Dự án nghiên cứu, thực nghiệm và phân tích lý thuyết thuật toán CVM (Chakraborty, Vinodchandran, Meel) cho bài toán đếm số lượng phần tử phân biệt ($F_0$) trên luồng dữ liệu (Data Streams).

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

`stdout` chỉ có **một dòng CSV, không có header**, đúng thứ tự:

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

Còn chờ TV3/nhóm: ghép bốn trường vào CSV thí nghiệm, mapping ID sang `uint64_t`,
quy ước luồng rỗng và cấu hình CI.

## Đóng góp
Xem chi tiết tại [CONTRIBUTING.md](CONTRIBUTING.md).
