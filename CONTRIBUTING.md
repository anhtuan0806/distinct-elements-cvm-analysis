# Hướng dẫn đóng góp

## Quy trình
1. Tách nhánh từ `develop`
2. Commit theo Conventional Commits
3. Mở PR vào `develop`
4. Cần 1 approve và CI xanh mới được merge
5. Dùng squash merge

## Đặt tên nhánh
- `feature/<mô-tả>`
- `fix/<mô-tả>`
- `hotfix/<mô-tả>`
- `chore/<mô-tả>`
- `docs/<mô-tả>`

## Cài đặt môi trường phát triển (Python / C)
```bash
# Tạo và kích hoạt môi trường ảo
python3 -m venv .venv
source .venv/bin/activate

# Cài đặt thư viện phát triển
pip install -r requirements-dev.txt

# Cài đặt Git hooks (tùy chọn)
pre-commit install --hook-type commit-msg --hook-type pre-commit

# Kiểm tra code
ruff check .
pytest
```

## Commit message
`<type>(<scope>): <mô tả ngắn>`

Type: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`
Ví dụ: `feat(cvm): implement core streaming estimator`

## Pull Request
- Nhỏ, tập trung một mục đích
- Điền đầy đủ PR template
- Dùng Draft PR nếu chưa sẵn sàng review