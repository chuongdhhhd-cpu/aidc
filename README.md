# ACDI Check — backend thống kê ẩn danh

Ứng dụng bài tự đánh giá ACDI và dashboard dùng Python chuẩn, SQLite và HTML tĩnh; không cần cài thư viện Python bên thứ ba. Blueprint `render.yaml` mô tả một Render Web Service chạy Python tại Singapore, gắn persistent disk cho SQLite và bật HTTPS do Render quản lý.

## Chạy local

Yêu cầu Python 3.9 trở lên. Từ thư mục dự án:

```bash
python3 server.py
```

Mở các đường dẫn:

- Bài tự đánh giá: <http://127.0.0.1:8000/>
- Dashboard: <http://127.0.0.1:8000/dashboard>
- Health check: <http://127.0.0.1:8000/health>
- API thống kê: <http://127.0.0.1:8000/api/stats>
- API nhận điểm: `POST http://127.0.0.1:8000/api/submit`

Server ưu tiên biến `PORT` do nền tảng cung cấp; nếu không có thì dùng `ACDI_PORT` hoặc cổng `8000`. Có thể đặt `ACDI_HOST` (mặc định local là `127.0.0.1`), `ACDI_DB_PATH` (mặc định `data/acdi.sqlite3`) và `ACDI_MIN_GROUP_SIZE` (mặc định 5, không thể đặt thấp hơn 5).

Ví dụ kiểm thử local với database riêng:

```bash
ACDI_HOST=127.0.0.1 ACDI_PORT=8000 ACDI_DB_PATH=/tmp/acdi-test.sqlite3 python3 server.py
```

## Triển khai Render

Tạo dịch vụ bằng Blueprint từ `render.yaml`, nhánh `main`. Cấu hình định trước gồm runtime Python, lệnh build `python3 -m py_compile server.py`, lệnh chạy `python3 server.py`, health check `/health`, `ACDI_HOST=0.0.0.0`, `ACDI_DB_PATH=/var/data/acdi.sqlite3`, và `ACDI_MIN_GROUP_SIZE=5`.

Blueprint dùng gói web service trả phí hỗ trợ persistent disk. Disk `acdi-data` có kích thước 1 GB và mount tại `/var/data`; chỉ database nằm trong mount này mới bền vững qua restart/deploy. Không đổi `ACDI_DB_PATH` sang thư mục repository hoặc `/tmp` trên production. Không dùng free instance hoặc filesystem tạm cho dữ liệu production. Giá dịch vụ phụ thuộc bảng giá Render và workspace; xác nhận chi phí trong bản kế hoạch Blueprint trước khi áp dụng.

Render cấp URL HTTPS công khai. Kiểm tra `/health`, `/`, `/dashboard` và `/api/stats` sau deploy. HTTPS bắt buộc khi công khai; không tự đặt secret nào trong repository. Ứng dụng không cần API key.

## Đồng ý và dữ liệu

Người làm bài phải chủ động đánh dấu ô đồng ý để điểm được gửi. Nếu không đồng ý, bài vẫn hoạt động và kết quả chỉ hiện trên thiết bị; frontend không gọi API ghi nhận. Backend chỉ nhận yêu cầu có `consent: true`.

Database chỉ lưu số lượt cộng dồn, tổng điểm ACDI, điểm của bốn thành phần ID/CPD/JD/IPL, điểm tình huống, số lượng cộng dồn theo mức ACDI và ngày UTC. Không lưu câu trả lời từng câu, tên, lớp, email, số điện thoại, IP hoặc mã định danh. Ứng dụng không ghi log request/IP. Nhà cung cấp hosting, CDN hoặc proxy có thể có nhật ký mạng riêng; chính sách đó không do ứng dụng kiểm soát.

`GET /api/stats` chỉ công bố thống kê tổng quan khi có ít nhất 5 lượt. Số liệu theo từng mức và từng ngày chỉ được trả về nếu nhóm tương ứng đạt ngưỡng ít nhất 5; giá trị phân bố dưới ngưỡng được ẩn. Ngưỡng có thể tăng bằng `ACDI_MIN_GROUP_SIZE`, không thể giảm dưới 5.

## API ghi nhận

`POST /api/submit` nhận JSON sau khi người tham gia đã đồng ý:

```json
{
  "consent": true,
  "acdi": 3.1,
  "components": {"ID": 3.0, "CPD": 3.4, "JD": 3.2, "IPL": 2.8},
  "scenario": 2.5,
  "level": 3
}
```

Yêu cầu không có đồng ý bị trả HTTP 400. API không chấp nhận các trường định danh hoặc câu trả lời từng câu. `GET /api/stats` trả JSON đã áp dụng ngưỡng ẩn nhóm nhỏ; `GET /health` trả JSON trạng thái `ok`.

## Lưu ý khi dùng với học sinh

Trước khi thu thập dữ liệu, hãy xem xét yêu cầu chấp thuận của nhà trường/phụ huynh, chính sách bảo vệ dữ liệu của đơn vị triển khai, thời hạn lưu trữ và cách sao lưu/khôi phục. Không dùng kết quả tổng hợp để gắn nhãn hoặc đánh giá cá nhân. SQLite chứa dữ liệu cộng dồn nên không thể xóa riêng một lượt; xóa dữ liệu thử nghiệm cần reset toàn bộ database theo quy trình được phê duyệt.

## Cấu trúc

```text
server.py
render.yaml
README.md
.gitignore
static/index.html
static/dashboard.html
data/.gitkeep       # giữ thư mục; không chứa database
```
