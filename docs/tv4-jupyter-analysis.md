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
    plot_workloads: bool = True,
) -> JupyterAnalysisResult
```

| Trường | Nội dung |
| --- | --- |
| `raw` | DataFrame chứa các record đã được kiểm tra |
| `summary` | Thống kê theo cấu hình và môi trường, cùng quy ước với CLI |
| `summary_path` | CSV tổng hợp |
| `png_paths` | Hình theo workload cho từng metric có số đo khi bật `plot_workloads` |
| `markdown_path` | Báo cáo Markdown của lần phân tích |
| `provenance` | RAW, sidecar, checksum, phân loại và metadata đã xác thực |
| `notes` | Ghi chú về dữ liệu thiếu và cảnh báo validator |
| `benchmark_summary`, `benchmark_summary_path` | Bảng số liệu dùng cho hình, đơn vị ms, MiB và %, sắp xếp theo m. Cột `run_ids` liên kết các lượt trong RAW. |
| `verified_rows` | Các record parser trả về cùng định danh môi trường và nguồn từ sidecar. Notebook dùng chúng để tổng hợp nhiều cặp RAW mà vẫn tính median trên từng trial. |

Sidecar mặc định có cùng tên gốc với RAW và đuôi `.metadata.json`. API báo lỗi nếu validator từ chối đầu vào hoặc dữ liệu không có lượt hoàn tất để phân tích. Bảng chi tiết dùng median qua các lượt success có số đo. Sai số (%) được tính từ estimate và F₀ trong từng trial với F₀ dương. RSS và sai số thiếu để trống. CSV `summary.csv` giữ schema TV4, gồm RSS theo byte, peak sample và runtime abort riêng.

`verified_real` cho biết RAW và sidecar khớp giao thức kiểm tra. Kết luận thống kê và Big-O vẫn cần được diễn giải theo thiết kế thí nghiệm và mô hình thuật toán.

Notebook gọi API với `plot_workloads=False` cho từng cặp RAW/sidecar, sau đó
gom các trial đã xác thực để tính bảng `aggregate_summary.csv` theo m. Một
trung bình không trọng số của median workload tạo mỗi điểm. Bảng ghi độ
bao phủ theo metric. `analysis/report.md` liên kết hình chính, bảng chi tiết
và các cặp nguồn. Bật `SHOW_WORKLOAD_DETAILS` trong notebook để xuất hình theo
workload. [Hướng dẫn notebook](../notebooks/README.md)
