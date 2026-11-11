# Phân tích độ phức tạp và cận sai số của thuật toán CVM trong bài toán đếm phần tử phân biệt trên luồng dữ liệu

Dự án nghiên cứu, thực nghiệm và phân tích lý thuyết thuật toán CVM (Chakraborty, Vinodchandran, Meel) cho bài toán đếm số lượng phần tử phân biệt ($F_0$) trên luồng dữ liệu (Data Streams).

Lõi CVM-A1 được viết bằng C++ để ước lượng số phần tử phân biệt khi đọc dữ liệu theo luồng. Phần thực nghiệm dùng Python để sinh dữ liệu, kiểm thử và ghi kết quả phục vụ phân tích sai số, thời gian chạy và kích thước tập mẫu.

## Cài đặt môi trường

Dự án dùng Python 3.10 trở lên và trình biên dịch hỗ trợ C++17 như GCC, Clang hoặc MSVC. Tạo môi trường Python bằng Bash như sau.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Chạy kiểm thử

Chạy bộ kiểm thử Python trên Linux bằng lệnh sau.

```bash
pytest
```

## Tài liệu

- [Cài đặt, build, chạy và kiểm thử CVM-A1](docs/README.md)
- [Kết quả kiểm thử P0 GĐ1](docs/cvm-a1-p0-evidence.md)

## Đóng góp

Xem chi tiết tại [CONTRIBUTING.md](CONTRIBUTING.md).
