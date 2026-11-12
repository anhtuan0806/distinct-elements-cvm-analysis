# QUY ĐỊNH BẮT BUỘC: CI QUALITY GATE & MERGE TESTS

> **MỤC TIÊU**: Đảm bảo tất cả Pull Request (PR) và commit đều vượt qua 100% các bước kiểm tra tự động trên GitHub Actions CI, tránh tình trạng bị chặn merge (`Merging is blocked`).

---

## 1. NGUYÊN NHÂN CI FAIL VỪA GẶP TRÊN GITHUB ACTIONS

Qua log thực tế của CI trên nhánh `feature/runner-pipeline-final` (Job `CI / lint-and-test`):
- CI chạy ma trận song song trên 3 phiên bản Python: **Python 3.10, 3.11, 3.12**.
- Thứ tự thực thi trong `.github/workflows/ci.yml`:
  1. `ruff check .` (Kiểm tra linting: `E`, `F`, `I`, `W`)
  2. `ruff format --check .` (Kiểm tra format và độ dài dòng `line-length <= 100`)
  3. `pytest` (Chạy toàn bộ 64+ test cases)
  4. `commitlint` (Kiểm tra chuẩn Conventional Commits cho từng commit message)
- **Lỗi thực tế xảy ra**:
  - `runner.py`: Định nghĩa trùng lặp hàm `run_single_trial` (`F811`) và thiếu các import `CSV_COLUMNS`, `datetime`, `timezone`, `json`.
  - `tests/test_schema_io.py`: Thừa import không dùng `json` (`F401`) và giá trị mặc định của `--out` chưa cập nhật theo phân tách output (`results/real/raw_benchmark.csv`).
  - Linter Ruff trả về exit code `1` ngay tại bước `Lint with ruff`, khiến toàn bộ test suite bị dừng và GitHub Actions đánh dấu **Failing / Merging is blocked**.

---

## 2. QUY TRÌNH BẮT BUỘC SAU MỖI LẦN VIẾT HOẶC SỬA CODE

Trước khi tạo commit và push lên GitHub, lập trình viên/agent **BẮT BUỘC** phải thực hiện tuần tự 4 bước sau tại môi trường cục bộ:

### Bước 1: Kiểm tra và sửa lỗi Linting với Ruff
```bash
# Kiểm tra lỗi linting
ruff check .

# (Tùy chọn) Tự động sửa các lỗi cú pháp/import cơ bản
ruff check --fix .
```
- **Quy tắc bắt buộc**: Không để sót bất kỳ cảnh báo hoặc lỗi nào:
  - `E` / `W`: Lỗi chuẩn PEP 8.
  - `F`: Biến chưa định nghĩa (`F821`), import thừa không dùng (`F401`), redefinition hàm/biến (`F811`).
  - `I`: Thứ tự import (isort) phải đúng chuẩn (`from __future__` $\to$ standard library $\to$ third-party $\to$ local modules).

### Bước 2: Kiểm tra định dạng mã nguồn (Formatting)
```bash
# Kiểm tra xem mã nguồn đã đúng chuẩn format chưa (line-length <= 100)
ruff format --check .

# Nếu có file chưa đúng chuẩn, tự động format:
ruff format .
```

### Bước 3: Chạy toàn bộ Test Suite (Pytest & C++)
```bash
# Chạy toàn bộ unit tests và integration tests
python3 -m pytest

# Chạy test suite C++ Algorithm 1 (nếu có chỉnh sửa hoặc build C++)
./build/test_a1
```
- **Tiêu chí**: 100% tests phải PASS (hiện tại là 64/64 Python tests và 14/14 C++ tests).

### Bước 4: Kiểm tra thông điệp Commit (Conventional Commits)
GitHub Actions workflow `commitlint` kiểm tra nghiêm ngặt format của từng commit theo regex:
```regex
^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-zA-Z0-9_\-\/]+\))?: .+$
```
- **Ví dụ hợp lệ**:
  - `fix(runner): resolve duplicate function and unused imports for ruff check`
  - `feat(cli): add workload and seed options to runner CLI`
  - `test(schema): update default output path to results/real/raw_benchmark.csv`
  - `docs(task): document mandatory quality gate workflow`
- **Các commit không hợp lệ (sẽ bị CI từ chối)**:
  - `fixed bugs`
  - `update runner`
  - `WIP`

---

## 3. CHECKLIST KIỂM SOÁT CHẤT LƯỢNG (QUALITY GATE CHECKLIST)

Mỗi lần chuẩn bị commit code, đánh dấu hoàn thành:
- [ ] Đã chạy `ruff check .` $\to$ **All checks passed!**
- [ ] Đã chạy `ruff format --check .` $\to$ **All files formatted!**
- [ ] Đã chạy `pytest` $\to$ **100% tests pass (0 failure, 0 error)**.
- [ ] Đã kiểm tra C++ `./build/test_a1` $\to$ **14/14 tests pass**.
- [ ] Thông điệp commit tuân thủ đúng chuẩn Conventional Commits `<type>(<scope>): <subject>`.
