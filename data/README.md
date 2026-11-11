# Dữ liệu thực nghiệm (Data)

Thư mục này dùng để lưu trữ các tập dữ liệu đầu vào phục vụ thực nghiệm thuật toán CVM và các thuật toán đối chứng.

> [!NOTE]
> Các tệp dữ liệu lớn (log, csv, text stream thô) được cấu hình bỏ qua trong `.gitignore` để tránh làm nặng kho lưu trữ Git.
> Hãy lưu dữ liệu mẫu hoặc tài liệu mô tả cách sinh/tải dữ liệu tại đây.

## Sinh luồng kiểm thử

`src/stream_generator.py` cung cấp `StreamConfig`, `Distribution` và
`generate_stream(config)`. Generator trả về iterator các ID nguyên trong
`[0, n)`, mỗi ID có thể được ghi thành một dòng thập phân để đưa vào `cvm_core`.
Nó không lưu toàn bộ luồng trong bộ nhớ; trạng thái phụ thuộc vào `F0`.

Các phân bố khả dụng:

- `all_duplicate`: một ID lặp lại `m` lần; yêu cầu `F0=1`.
- `all_distinct`: `m` ID khác nhau; yêu cầu `F0=m` và `m≤n`.
- `uniform`: các ID phân biệt được chọn đồng xác suất.
- `skewed`: 80% xác suất thuộc `ceil(F0/5)` ID nhỏ nhất; 20% thuộc phần còn lại.
- `zipf`: xếp hạng ID tăng dần, trọng số theo thứ hạng `1/rank^1.2`.

Với uniform, skewed và Zipf, generator bảo đảm mỗi ID trong tập `F0` đã chọn
xuất hiện ít nhất một lần; các vị trí còn lại tuân theo trọng số phân bố. Vì vậy
ground truth của stream luôn đúng bằng cấu hình `F0`. Khi `F0=1`, các phân bố
này chỉ có một ID và cho cùng dạng stream.

Ví dụ:

~~~python
from src.stream_generator import Distribution, StreamConfig, generate_stream

config = StreamConfig(m=8, n=10, f0=3, distribution=Distribution.ZIPF, seed=42)
for item_id in generate_stream(config):
    print(item_id)  # Mỗi ID trên một dòng cho cvm_core
~~~

Cùng cấu hình và seed tạo cùng stream trong cùng môi trường Python. Để lặp lại
một thí nghiệm, lưu cả `m`, `n`, `F0`, phân bố và seed cùng kết quả.
