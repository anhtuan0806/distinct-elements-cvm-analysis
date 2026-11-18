# TV4 · Phân tích kết quả trong Jupyter

Chạy kernel từ thư mục gốc repo với Python ≥3.10 và các thư viện trong
`requirements.txt`. Cell dùng IPython để hiển thị Markdown, bảng và PNG.
Mỗi lần gọi API tạo một thư mục con `tv4-*` trong `out_dir`.

## Cell dành cho TV2

```python
from IPython.display import Image, Markdown, display

from scripts.jupyter_analysis import analyze_jupyter_results

report = analyze_jupyter_results(
    "results/real/tv4_timespace_p0_20261113.csv",
    "results/figures/jupyter",
)
display(Markdown(f"**RAW** · {len(report.raw)} bản ghi · xem 10 dòng đầu"))
display(report.raw.head(10))
table = report.summary.assign(
    rss_median_mib=report.summary["ram_median"].div(1024**2),
    core=report.summary["binary_sha256"].str[:12],
    source=report.summary["source_tree_sha256"].str[:12],
)
columns = (
    "workload m n F0 epsilon delta s env_os python cpu core source run_count success_count "
    "abort_count execution_error_count resource_failure_count halving_run_count runtime_mean "
    "runtime_median rss_median_mib sample_median"
).split()
labels = {
    "runtime_mean": "Runtime mean (ms)",
    "runtime_median": "Runtime median (ms)",
    "rss_median_mib": "Peak RSS median (MiB)",
    "sample_median": "Peak sample median (phần tử)",
}
display(table[columns].rename(columns=labels))
display(Markdown("\n".join(f"- {note}" for note in report.notes)))
for path in report.png_paths:
    display(Image(filename=str(path), width=900))
print(f"CSV {report.summary_path}\nMarkdown {report.markdown_path}")
```

Khi notebook đã có kết quả từ TV3, truyền `benchmark.csv_path` làm đối số
đầu tiên và `metadata_path=benchmark.sidecar_path`. Mở
`report.markdown_path` để đọc chú giải và số liệu dùng trong báo cáo.
Các giá trị thiếu xuất hiện dưới dạng ô trống hoặc `NaN` trong bảng.

## Giao diện

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
| `raw` | DataFrame chứa 24 cột RAW đã được kiểm tra |
| `summary` | DataFrame theo cấu hình và môi trường, dùng cùng thống kê với CLI |
| `summary_path` | CSV tổng hợp của lượt phân tích |
| `png_paths` | Tuple đường dẫn PNG được tạo trong lượt này |
| `markdown_path` | Báo cáo Markdown, kèm bảng số liệu và liên kết tương đối tới CSV/PNG |
| `provenance` | Đường dẫn RAW và sidecar, SHA-256 từng tệp, phân loại và metadata đã xác thực |
| `notes` | Ghi chú về số mức m, RSS, ngưỡng chưa xác định và cảnh báo từ validator |

Sidecar mặc định có cùng tên gốc với RAW và đuôi `.metadata.json`. API
báo `ValueError` khi validator từ chối đầu vào, hoặc khi dữ liệu chỉ chứa
lỗi thực thi/tài nguyên. Dữ liệu chỉ có algorithm abort vẫn xuất bảng và báo
cáo, với danh sách PNG rỗng. Với thiếu RSS, cell hiển thị các biểu đồ có dữ liệu.

## Quy ước thống kê

Lỗi thực thi và lỗi tài nguyên có thể khiến `s` trống. CLI và API
gộp lượt này vào nhóm tương ứng khi các lượt hoàn tất xác định duy nhất một
ngưỡng cho cùng cấu hình, nguồn, binary và môi trường. Nếu ngưỡng chưa thể
xác định duy nhất, nhóm `s` trống vẫn xuất hiện trong CSV và báo cáo.
Runtime, RSS và sample dùng các lượt success. Runtime abort được xuất riêng.
Cột tỷ lệ dùng số attempt trong nhóm làm mẫu số.

Peak RSS đo tiến trình C++ và xuất trong CSV theo byte. Biểu đồ quy đổi theo
`1 MiB = 1.048.576 byte`. Peak sample đếm số phần tử lớn nhất trong tập mẫu.
Với một mức `m`, biểu đồ biểu diễn số đo tại điểm đó. Phân tích Big-O cần lập
luận riêng về chi phí cập nhật, thinning và sức chứa mẫu.

## Đối chiếu từ terminal

```bash
python -m scripts.validate_results results/real/tv4_timespace_p0_20261113.csv
python -m scripts.analyze_results results/real/tv4_timespace_p0_20261113.csv \
  --out /tmp/tv4-windows-p0-cli.csv
python -m pytest tests/test_tv4_results.py tests/test_timespace_plan.py
```

Dùng đường dẫn `report.summary_path` để đối chiếu CSV từ API với CSV của
CLI. Notebook chung được nghiệm thu khi TV2 đưa cell vào và chạy bằng Linux
với đầu vào do TV3 tạo hoặc một cặp RAW/sidecar TV4 công bố.
