# TV1 — Linux C++ Core: chuẩn bị và bàn giao nghiệm thu native

**Linux native x86_64: CHƯA CHẠY. Task chưa được nghiệm thu.** Phần chuẩn bị dưới
đây được thực hiện trên Windows ngày 18/11/2026. CI, WSL, Docker, VM hoặc chỉ thấy
`uname` báo Linux không thay thế lần chạy trên máy cài Linux trực tiếp của nhóm.
Không cần VS Code để build/test. Task này không tạo notebook.

## Hiện trạng đã khảo sát

- Repo: `https://github.com/anhtuan0806/distinct-elements-cvm-analysis.git`.
  Nhánh task `feat/linux-core-smoke` tách từ `origin/develop` sau fetch, commit nền
  `76c179960fa617eb9dc588ae8995247280f9f640`. Workspace ban đầu sạch; không có
  AGENTS.md trong repo hoặc thư mục cha áp dụng. Worktree `cvm-runner-check` có sẵn
  được giữ nguyên. CONTRIBUTING yêu cầu PR vào develop, không tự merge.
- `src/cvm/a1.{hpp,cpp}` dùng C++17, thư viện chuẩn, `uint64_t`, `unordered_set`,
  `mt19937_64` và nguồn `RandomDecision` sẵn có cho test. Không sửa thuật toán.
- `src/cvm/build.py::build_cvm_core()` đã là quy trình build cho Runner. Nó chọn
  g++ rồi clang++; Windows có thể dùng cl.exe. GCC/Clang: `-O3 -std=c++17 -Isrc`;
  MSVC: `/O2 /std:c++17 /EHsc /Isrc`. Nó liên kết `peak_rss.cpp` trên Linux/Windows
  và tự ghi receipt chứa hash binary, compiler, flags. Không tạo build system khác.
- Runner tìm `build/a1/cvm_core` trên Linux, `build/a1/cvm_core.exe` trên Windows.
  Receipt cùng tên `cvm_core.build.json` được dùng để xác nhận byte binary.
- Đã có 14 unit C++, CLI/threshold smoke trong `tests/cpp/check_cvm_core.py`, fixture
  `cvm_abort_fixture.cpp` và test `check_tv1_runner.py` đi qua Core → Runner → RAW.
  Bổ sung tối thiểu vào CLI smoke: all-duplicate, all-distinct chưa halving và
  all-distinct có halving thực sự (`halving_count > 0`, peak = s).
- Đã sửa mô tả adapter lỗi thời trong `docs/README.md`: adapter hiện đối chiếu s
  giữa threshold-v1 và csv-v2, rồi ghi ngưỡng hiệu lực; không còn bỏ cột s.

## Contract thực tế với TV3

Chạy từ project root. Thứ tự option có thể đổi; mỗi option chỉ xuất hiện một lần,
theo cặp tên/giá trị, không dùng `--name=value`.

| Tham số Core | Kiểu và miền |
|---|---|
| `--m` | uint64 thập phân, 0..2^64-1, tổng lượt đọc gồm ID lặp. |
| `--eps`, `--delta` | Số thực hữu hạn thuộc (0,1); ngưỡng phải biểu diễn được/sức chứa hợp lệ. |
| `--seed` | uint64 thập phân, 0..2^64-1. |
| `--output-format` | Bỏ option = legacy; hoặc `csv-v2`, `threshold-v1`. |

Không có n ở Core. stdin: mỗi dòng một ID uint64 thập phân; chấp nhận khoảng trắng
ASCII quanh ID, không chấp nhận dòng trống, dấu +/- hoặc nhiều ID cùng dòng. Đọc
tối đa m dòng, dừng ngay khi abort; phần còn lại không được xử lý. Core m=0 trả
success/estimate=0/s=0, nhưng **Runner yêu cầu m>0 và s nguyên dương**. Đây là khác
biệt miền đầu vào đã có, không sửa trong task này.

stdout chỉ dành cho protocol, một dòng, không header:

| Chế độ | Thứ tự trường/hành vi |
|---|---|
| legacy | `estimate,abort,max_buffer_size,halving_count`; abort là TRUE/FALSE, estimate **trống khi abort** ở code hiện tại. |
| csv-v2 | `status,estimate,algorithm_runtime_ms,peak_sample_size,halving_count,s`. |
| threshold-v1 | `threshold-v1,<s>`; chỉ khởi tạo A1, không đọc stdin. |

Trong v2: status `success` có estimate số; `algorithm_abort` có estimate trống;
cả hai exit 0. s là ngưỡng từ constructor theo paper; peak tính cả lúc mẫu vừa đầy
trước thinning; halving đếm cả lượt gây abort. Timer steady_clock cộng constructor,
từng update của ID đã parse và result, đơn vị ms, loại chờ stdin/parse/xuất CSV.
Lỗi tham số, ID hoặc EOF thiếu m khi chưa abort: exit 1, stderr có
`cvm_core: execution_error: ...`, stdout trống trước khi xuất kết quả.

Adapter `src/cvm/executor.py` truy vấn threshold-v1, sau đó gửi stream qua stdin với
csv-v2, kiểm 6 cột, metric và s khớp truy vấn. Runner không có option chọn binary;
không thêm option mới vào TV3. Runner CLI dùng `--n`, `--f0`, `--workload`, seed-gen/
seed-algo để tạo stream, không chuyển n vào Core. Chỉ dùng cùng input/seed/bản build
để so determinism; không so runtime/RSS hoặc giả định MSVC/GCC/Clang giống kết quả.

Hook RSS chỉ bật khi Runner đặt `CVM_TV3_PEAK_RSS=1`; nó ghi marker vào **stderr**,
không đổi stdout. Linux đọc VmHWM KiB rồi nhân 1024 thành bytes; Windows dùng
PeakWorkingSetSize đã là bytes. Cả hai đo resident/working set của tiến trình, không
phải số ID của tập mẫu. Không dùng số đo Windows làm số đo Linux. End-to-end của
Runner gồm tạo chuỗi stdin và thực thi tiến trình, khác algorithm_runtime_ms.

## Dependencies và build

Bắt buộc: Git, Python >=3.10, g++ hỗ trợ C++17/`from_chars(double)` hoặc clang++ với
thư viện chuẩn phù hợp. Core, smoke và Runner hiện dùng thư viện chuẩn; không cần
NumPy, Matplotlib, Jupyter hoặc VS Code cho task này. Trên máy Debian/Ubuntu đã cài
đầy đủ, nếu thiếu công cụ, thành viên vận hành có thể cài:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends git g++ python3
# Tùy chọn: clang; python3-venv và pytest cho regression Python.
sudo apt-get install --no-install-recommends clang python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install pytest
```

Ưu tiên script bàn giao bên dưới: nó gọi build helper hiện có, tạo workspace nguồn
riêng dưới output mới, giữ đường dẫn Runner quen thuộc trong workspace đó. Binary,
receipt và RAW smoke đều mới; không ghi đè `build/a1`/RAW/chứng cứ Windows của
checkout nguồn. Nó chỉ sao chép file nguồn/test có theo dõi trong Git và ghi SHA256.
Không sửa .gitignore hoặc sidecar/schema: chỉ Runner nguyên bản tự tạo các file thử
mới trong thư mục của lượt này.

Để đối chiếu lệnh GCC/Clang thủ công cho **CLI smoke**, từ root checkout:

```bash
set -euo pipefail
mkdir -p build
BIN=$(mktemp -d "$PWD/build/linux-core-manual.XXXXXX")
CXX=g++  # đổi thành clang++ cho một lượt Clang riêng
"$CXX" -O3 -std=c++17 -Isrc src/cvm/a1.cpp src/cvm_core.cpp src/cvm/peak_rss.cpp -o "$BIN/cvm_core"
"$CXX" -O3 -std=c++17 -Wall -Wextra -Werror -pedantic -Isrc src/cvm/a1.cpp tests/cpp/test_a1.cpp -o "$BIN/test_a1"
"$CXX" -O3 -std=c++17 -Isrc src/cvm/a1.cpp tests/cpp/cvm_abort_fixture.cpp -o "$BIN/cvm_abort_fixture"
"$BIN/test_a1"
python3 -m tests.cpp.check_cvm_core "$BIN/cvm_core" --log "$BIN/cli-smoke.json"
python3 -m tests.cpp.check_tv1_runner "$BIN/cvm_core" "$BIN/cvm_abort_fixture"
printf '10\n20\n10\n30\n' | "$BIN/cvm_core" --m 4 --eps 0.05 --delta 0.01 --seed 42 --output-format csv-v2
```

Binary build thủ công không có receipt do helper tạo; không đặt nó vào đường dẫn
managed để Runner dùng trực tiếp. Script và ví dụ Runner dùng helper để có receipt
đúng byte binary. Helper chọn g++ trước clang++; không suy diễn rằng biến CXX đổi
compiler của helper. GCC/Clang trên Linux native trong task này đều **CHƯA CHẠY**.

## Lấy đúng commit và chạy trên máy Linux native của nhóm

1. TV1 bàn giao local commit đã review cùng `linux-core-smoke.bundle`,
   `linux-core-smoke.commit`, `handoff.json` (hash bundle và commit). Không lấy tên
   branch/develop thay cho SHA nghiệm thu. Nếu dùng PR, lấy SHA thật chứa script
   và test này sau review; không dùng commit nền 76c1799 vốn chưa có chúng.
   Xuất `.commit` bằng UTF-8 không BOM, chỉ SHA và một ký tự LF cuối dòng; với
   Python dùng `write_bytes((sha + "\n").encode("utf-8"))` để tránh chuyển thành
   CRLF trên Windows. Xuất JSON bằng `write_bytes` với UTF-8 tương tự;
   `json.dumps(manifest, ensure_ascii=True, indent=2)` giữ nguyên Unicode khi đọc
   lại, tránh mất dấu qua pipeline PowerShell. `native_acceptance` phải đọc lại
   thành `CHƯA CHẠY`. Giữ SHA thật của log Windows nếu không chạy lại build/test
   khi chỉ sửa tài liệu hoặc cách xuất gói.
2. Trên máy Linux **cài trực tiếp/dual boot đã được thành viên xác nhận**, lấy một
   checkout riêng theo bundle/SHA. Ví dụ Bash với bộ bàn giao đã chép sang máy:

```bash
set -euo pipefail
TRANSFER=/duong/dan/bo-ban-giao
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
git clone --no-checkout https://github.com/anhtuan0806/distinct-elements-cvm-analysis.git cvm-source
cd cvm-source
git bundle verify "$TRANSFER/linux-core-smoke.bundle"
git fetch "$TRANSFER/linux-core-smoke.bundle" refs/heads/feat/linux-core-smoke
git worktree add --detach ../cvm-linux-task "$SMOKE_SHA"  # phải là đường dẫn mới
cd ../cvm-linux-task
test "$(git rev-parse HEAD)" = "$SMOKE_SHA"
test -z "$(git status --porcelain --untracked-files=all)"
```

3. Từ root worktree sạch vừa tạo, chạy (nếu dùng venv, thay python3 bằng python của
   venv đó; thêm `--python-regressions` khi đã cài pytest):

```bash
set -euo pipefail
RUN_DIR="$PWD/build/linux-core-smoke/native-$(date -u +%Y%m%dT%H%M%SZ)"
python3 scripts/verify_core_checkout.py \
  --expected-commit "$SMOKE_SHA" \
  --output-dir "$RUN_DIR" \
  --environment linux-native \
  --native-note 'TEN_THANH_VIEN; distro/version; Linux installed on physical x86_64 machine, direct/dual boot'
```

Điền mô tả máy thật vào native-note. Script từ chối sai SHA, dirty checkout native,
output cũ và dấu hiệu WSL/container/virtualization đã biết. Không có dấu hiệu ảo hóa
không chứng minh bare metal: native-note là xác nhận của người vận hành, nhóm vẫn
phải review môi trường. Báo cáo không tự chốt nghiệm thu native.

Script tái sử dụng build helper, 14 unit C++, CLI smoke, fixture abort/Runner, rồi
chạy `runner.py` thật với workload all-distinct 4096 ID và kiểm halving thực sự.
Không áp estimate phải bằng F0 khi đã sampling. Abort kiểm bằng executable fixture
dùng A1/serializer thật và RNG điều khiển, không thêm cờ ép vào Core production;
không khẳng định đã tìm được seed production gây abort tự nhiên.

4. Giữ toàn bộ RUN_DIR để bàn giao log. `report.json` ghi UTC bắt đầu/kết thúc,
   commit/status nguồn, loại môi trường, xác nhận máy, distro/kernel/kiến trúc,
   CPU/count, Python, compiler/banner, hash nguồn/binary, flags, cwd/lệnh và exit
   code từng bước. `compiler_version.*.log` lưu version độc lập; receipt MSVC hiện
   có thể chỉ ghi heading `C/C++ COMPILER OPTIONS`, nên không dùng heading làm version.
   Không dump toàn bộ environment hoặc credential. Từng bước có stdout/stderr riêng;
   build/test lỗi làm script exit 1, các bước chưa tới giữ CHƯA CHẠY. Regression
   không được yêu cầu ghi SKIP. Không có pipeline tee làm mất exit code.
5. TV3 có thể dùng Python/Jupyter cùng helper/adapter hiện có (không cần viết
   notebook), hoặc chạy CLI từ **workspace đã được script build**:

```bash
cd "$RUN_DIR/workspace"
python3 runner.py --m 4096 --n 4096 --f0 4096 --workload all_distinct --eps 0.9 --delta 0.9 --seed 42 --out "$RUN_DIR/real/tv3-second-run.csv"
```

Tên output phải mới. `runner_cli` trong report đã ghi lệnh tương đương và RAW riêng.
Đường dẫn executable trong report là `workspace/build/a1/cvm_core`; script không
thêm option binary vào Runner. Adapter callable là
`run_cvm_a1_core(config, stream, binary_path=...)`; config/stream tuân hợp đồng TV3.
Không sửa RAW/sidecar cũ, không copy binary Linux vào `build/a1` của Windows.

## Kết quả Windows và trạng thái còn thiếu

Windows preparation thực tế dùng MSVC 19.41.34120 x64, Developer PowerShell 17.11.3,
Python 3.14.1. Log mới tách riêng dưới `build/linux-core-smoke/`, không thay log P0.

- Lượt chuẩn bị ngày 18/11: unit C++ **14/14 PASS**; CLI **45 ca + delayed input PASS**;
  Core → Runner → RAW success/fixture abort/replay PASS; Runner CLI thật có halving;
  regression threshold/adapter/e2e **39 PASS, 5 subtests PASS**.
- Ví dụ MSVC: `success,3,0.018200000000000001,3,0,55891`; legacy `3,FALSE,3,0`.
  All-distinct 4096, eps=.9, delta=.01: h=4, peak=s=321, estimate=3712 (không ép 4096).
  Hai lượt seed lặp cho estimate=1984, peak=s=321, h=3; runtime thay đổi.
- Fixture abort thật qua Runner: estimate trống, h=1, peak=s=166, exit 0.
- Các con số trên thuộc Windows và bản build của lượt đó; không là golden value
  giữa compiler/stdlib. Chi tiết commit/hash và log của lượt bàn giao cuối xem
  `handoff.json`/report đi kèm.

| Tiêu chí nghiệm thu trên máy Linux native mục tiêu | Trạng thái |
|---|---|
| Máy cài trực tiếp x86_64 được thành viên xác nhận, checkout sạch đúng SHA | **CHƯA CHẠY** |
| Build GCC/Clang và unit/CLI smoke, sampling/halving/determinism | **CHƯA CHẠY** |
| Fixture abort và Core → TV3 Runner trên native | **CHƯA CHẠY** |
| Log native cùng câu lệnh, môi trường, commit và exit code được nhóm review | **CHƯA CHẠY** |

Nếu mở PR trước khi thành viên chạy native, phải giữ rõ trạng thái trên. Không suy
đoán nguyên nhân Live USB treo và không yêu cầu cài lại/chia ổ trong task code này.
