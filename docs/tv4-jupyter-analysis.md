# API phân tích kết quả trong Jupyter

Notebook TV2 gọi `scripts.jupyter_analysis.analyze_jupyter_results` cho từng cặp RAW/sidecar do TV3 tạo hoặc được liệt kê trong manifest P0. Hàm xác thực đầu vào, trả DataFrame và gọi pipeline TV4 để tổng hợp và vẽ.

## Giao diện

```python
from scripts.jupyter_analysis import analyze_jupyter_results

report = analyze_jupyter_results(
    benchmark.csv_path,
    output_dir,
    metadata_path=benchmark.sidecar_path,
)
```

```python
analyze_jupyter_results(
    raw_path: str | Path,
    out_dir: str | Path,
    *,
    metadata_path: str | Path | None = None,
) -> JupyterAnalysisResult
```

| Trường | Nội dung |
| --- | --- |
| `raw` | DataFrame chứa các record đã được kiểm tra |
| `summary` | Thống kê theo cấu hình và môi trường, cùng quy ước với CLI |
| `summary_path` | CSV tổng hợp |
| `png_paths` | Đường dẫn tới các hình TV4 được tạo |
| `markdown_path` | Báo cáo Markdown của lần phân tích |
| `provenance` | RAW, sidecar, checksum, phân loại và metadata đã xác thực |
| `notes` | Ghi chú về dữ liệu thiếu và cảnh báo validator |

Sidecar mặc định có cùng tên gốc với RAW và đuôi `.metadata.json`. API báo lỗi nếu validator từ chối đầu vào hoặc dữ liệu không có lượt hoàn tất để phân tích. Các lượt thành công được dùng cho runtime, RSS và peak sample; runtime abort được giữ riêng. RSS thiếu được để trống, không diễn giải thành 0.

`verified_real` cho biết RAW và sidecar khớp giao thức kiểm tra. Kết luận thống kê và Big-O vẫn cần được diễn giải theo thiết kế thí nghiệm và mô hình thuật toán.

Notebook xuất `analysis/report.md` cho mỗi lượt, cùng CSV tổng hợp, hình có số
đo và liên kết tới từng cặp RAW/sidecar đã xác thực. Các báo cáo chi tiết của TV4
nằm trong `analysis/datasets/`. Khi RSS thiếu, hàng số liệu vẫn xuất cùng các
biểu đồ còn lại. [Hướng dẫn notebook](../notebooks/README.md)
