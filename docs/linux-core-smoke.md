# Linux C++ Core

## Môi trường và dependencies

Môi trường nghiệm thu: Linux native x86_64 cài trực tiếp hoặc dual boot trên máy
vật lý, có xác nhận của người chạy. WSL, container, VM và CI không thay thế môi trường này.

Cần Git, Python >= 3.10 và compiler C++17 hỗ trợ `from_chars(double)`.
Script chọn g++ trước clang++, build với `-O3 -std=c++17 -Isrc`.
Core, smoke và Runner dùng thư viện chuẩn; không cần VS Code hoặc Jupyter để chạy.

Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends git g++ python3
```

Tùy chọn: Clang khi không có g++; pytest nếu chạy thêm `--python-regressions`.

## Lấy đúng commit bàn giao

Bộ bàn giao gồm `linux-core-smoke.bundle`, `linux-core-smoke.commit` và
`handoff.json`. Dùng SHA trong bộ bàn giao, không dùng commit nền hoặc tên branch.
File `.commit` dùng UTF-8 không BOM và LF; lệnh dưới cũng đọc được bản CRLF.
Dùng đường dẫn tuyệt đối cho `TRANSFER`; hai thư mục checkout phải chưa tồn tại.
Chạy các khối Bash dưới đây trong cùng một phiên shell, theo thứ tự.

```bash
set -euo pipefail
TRANSFER=/duong/dan/tuyet/doi/bo-ban-giao
SMOKE_SHA=$(tr -d '\r\n' < "$TRANSFER/linux-core-smoke.commit")
python3 - "$TRANSFER" "$SMOKE_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1])
manifest = json.loads((folder / 'handoff.json').read_text(encoding='utf-8'))
assert manifest['commit'] == sys.argv[2]
actual_hash = hashlib.sha256((folder / 'linux-core-smoke.bundle').read_bytes()).hexdigest()
assert actual_hash == manifest['bundle_sha256']
PY
git clone --no-checkout https://github.com/anhtuan0806/distinct-elements-cvm-analysis.git "$HOME/cvm-source"
cd "$HOME/cvm-source"
git bundle verify "$TRANSFER/linux-core-smoke.bundle"
git fetch "$TRANSFER/linux-core-smoke.bundle" refs/heads/feat/linux-core-smoke
git worktree add --detach "$HOME/cvm-linux-task" "$SMOKE_SHA"
cd "$HOME/cvm-linux-task"
test "$(git rev-parse HEAD)" = "$SMOKE_SHA"
test -z "$(git status --porcelain --untracked-files=all)"
```

## Build và chạy smoke

Từ root checkout sạch `"$HOME/cvm-linux-task"`, điền thông tin máy vào `--native-note`:

```bash
RUN_DIR="$PWD/build/linux-core-smoke/native-$(date -u +%Y%m%dT%H%M%SZ)"
python3 scripts/verify_core_checkout.py \
  --expected-commit "$SMOKE_SHA" \
  --output-dir "$RUN_DIR" \
  --environment linux-native \
  --native-note 'TEN_THANH_VIEN; distro/version; physical x86_64; direct install/dual boot'
```

Script tạo output mới và workspace riêng; binary, receipt và RAW tách khỏi chứng cứ
Windows. Executable nằm tại `$RUN_DIR/workspace/build/a1/cvm_core`.
Các bước gồm build, unit C++, CLI smoke, fixture abort và Runner với workload có halving.
Thêm `--python-regressions` vào lệnh trên nếu đã cài pytest.

Script trả `0` khi các bước bắt buộc PASS, `1` khi lỗi hoặc timeout. Bước chưa chạy
không được ghi PASS; regression tùy chọn ghi SKIP nếu không yêu cầu.

## TV3 gọi Runner và lấy output/log

Từ workspace vừa build, dùng tên CSV mới:

```bash
(
  cd "$RUN_DIR/workspace"
  python3 runner.py --m 4096 --n 4096 --f0 4096 --workload all_distinct \
    --eps 0.9 --delta 0.9 --seed 42 --out "$RUN_DIR/real/tv3-second-run.csv"
) > "$RUN_DIR/tv3-runner.stdout.log" 2> "$RUN_DIR/tv3-runner.stderr.log"
```

Runner dùng binary và build receipt trong workspace. Contract CLI, threshold-v1,
csv-v2, metric, mã thoát và RAW/sidecar xem [Runner TV3](tv3-runner.md).

- `$RUN_DIR/report.json`: SHA, môi trường, timestamp, compiler, hash, lệnh và kết quả từng bước.
- `$RUN_DIR/*.stdout.log`, `$RUN_DIR/*.stderr.log`: log từng bước, gồm output dở dang khi timeout.
- `$RUN_DIR/cli-smoke.json`: kết quả CLI và kiểm tra timer với input có khoảng chờ.
- `$RUN_DIR/real/runner-smoke.csv`: RAW của smoke; lệnh TV3 trên ghi CSV riêng cùng sidecar.

Giữ toàn bộ `RUN_DIR` để review. `algorithm_runtime_ms` tính bằng ms, loại thời gian
chờ stdin; RSS trong RAW tính bằng bytes. Chi tiết phép đo theo OS xem contract TV3.

## Kết quả kiểm tra

Windows/MSVC, commit `6f09c9b`: 14 unit C++, CLI smoke, fixture abort/Runner và
regression Python PASS. SHA và log gốc nằm trong `handoff.json` → `windows_report`;
chúng là bằng chứng Windows, không phải số đo Linux. Log thuộc SHA ghi trong report.

**Linux native x86_64: CHƯA CHẠY.** Cần chạy build/smoke và Runner trên máy mục tiêu,
sau đó review `report.json`, log và xác nhận môi trường của người chạy.
