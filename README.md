# Phân tích độ phức tạp và cận sai số của thuật toán CVM trong bài toán đếm phần tử phân biệt trên luồng dữ liệu

Dự án nghiên cứu, thực nghiệm và phân tích lý thuyết thuật toán CVM (Chakraborty, Vinodchandran, Meel) cho bài toán đếm số lượng phần tử phân biệt ($F_0$) trên luồng dữ liệu (Data Streams).

## Cài đặt môi trường

Yêu cầu: Python >= 3.10 và GCC/Clang.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Chạy kiểm thử

```bash
pytest
```

## Đóng góp
Xem chi tiết tại [CONTRIBUTING.md](CONTRIBUTING.md).