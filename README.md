# ACDI Check — backend thống kê ẩn danh

Ứng dụng bài tự đánh giá ACDI và dashboard dùng Python, PostgreSQL và HTML tĩnh. Backend cần Psycopg 3 để kết nối Neon PostgreSQL. Render Blueprint `render.yaml` mô tả một Web Service gói Free tại Singapore; dữ liệu được lưu trong Neon, không phụ thuộc filesystem tạm của Render.

## Chạy local

Yêu cầu Python 3.9 trở lên và một cơ sở dữ liệu PostgreSQL. Cài dependency:

```bash
python3 -m pip install -r requirements.txt
```

Đặt `DATABASE_URL` bằng chuỗi kết nối PostgreSQL có SSL (`sslmode=require`) trong môi trường shell cục bộ hoặc môi trường secret của bạn, rồi chạy:

```bash
python3 server.py
```

Không commit URL kết nối, mật khẩu hoặc tệp `.env`. Nếu chuỗi kết nối từng bị chia sẻ ngoài môi trường bảo mật, hãy xoay mật khẩu và cập nhật giá trị mới trong Render.

Mở các đường dẫn local:

- Bài tự đánh giá: <http://127.0.0.1:8000/>
- Dashboard: <http://127.0.0.1:8000/dashboard>
- Health check: <http://127.0.0.1:8000/health>
- API thống kê: <http://127.0.0.1:8000/api/stats>
- API nhận điểm: `POST http://127.0.0.1:8000/api/submit`

Server ưu tiên biến `PORT` do Render cung cấp; nếu không có thì dùng `ACDI_PORT` hoặc cổng `8000`. `ACDI_HOST` mặc định là `127.0.0.1`; `ACDI_MIN_GROUP_SIZE` mặc định là 1, tức là không quy định số lượt tối thiểu.

## Triển khai Render + Neon

Tạo/đồng bộ Blueprint từ nhánh `main` trong repository. `render.yaml` dùng Render Web Service gói Free, runtime Python, region Singapore, build command cài `requirements.txt` rồi biên dịch `server.py`, start command `python3 server.py`, health check `/health`, `ACDI_HOST=0.0.0.0` và `ACDI_MIN_GROUP_SIZE=5`.

`DATABASE_URL` được khai báo là secret (`sync: false`), không có giá trị trong repository. Đặt chuỗi kết nối Neon trong Render Dashboard tại **Environment → Environment Variables** với key `DATABASE_URL`. Dùng Neon Free và Render Free để tránh phí; không nâng cấp gói hoặc bật dịch vụ tính phí. Neon Free hiện niêm yết 1 GB PostgreSQL storage và 100 giờ compute mỗi tháng cho mỗi project; quota và điều kiện có thể thay đổi, nên theo dõi trang Pricing chính thức. Render Free có thể ngủ khi không có traffic; dữ liệu vẫn nằm ở Neon, không phải filesystem tạm của Render.

Neon Free có thể scale compute về 0 khi nhàn rỗi. Request đầu tiên sau một thời gian có thể chậm hơn do database cần khởi động lại. `/health` chỉ kiểm tra tiến trình web để tránh đánh thức database liên tục; `/api/stats` và `/api/submit` sẽ trả HTTP 503 nếu database tạm thời không sẵn sàng.

Sau deploy, kiểm tra `/health`, `/`, `/dashboard` và `/api/stats`. Render cung cấp HTTPS cho URL dịch vụ. Không cấu hình Render Persistent Disk hoặc Render Postgres riêng cho Blueprint này; Neon là PostgreSQL datastore.

## Đồng ý và dữ liệu

Người làm bài phải chủ động đánh dấu ô đồng ý để điểm được gửi. Nếu không đồng ý, bài vẫn hoạt động và kết quả chỉ hiện trên thiết bị; frontend không gọi API ghi nhận. Backend từ chối yêu cầu không có `consent: true` và từ chối các trường ngoài payload điểm được quy định.

Database chỉ lưu cộng dồn theo ngày UTC: số lượt, tổng điểm ACDI, tổng điểm bốn thành phần ID/CPD/JD/IPL, tổng điểm tình huống và số lượng cộng dồn theo mức ACDI. Không tạo bản ghi từng người, không lưu câu trả lời từng câu, tên, lớp, email, số điện thoại, IP hoặc mã định danh. Ứng dụng không ghi log request/IP. Nhà cung cấp hosting, proxy hoặc Neon có thể có nhật ký vận hành riêng; chính sách đó không do ứng dụng kiểm soát.

`GET /api/stats` trả về thống kê tổng quan, theo từng mức và từng ngày ngay từ lượt đầu tiên (chỉ dành cho quản trị, cần mật khẩu). Đặt `ACDI_MIN_GROUP_SIZE` lớn hơn 1 nếu muốn bật lại ngưỡng ẩn nhóm nhỏ.

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

Yêu cầu không có đồng ý bị trả HTTP 400. `GET /api/stats` trả JSON thống kê (cần mật khẩu quản trị); `GET /health` trả JSON trạng thái `ok`.

## Lưu ý khi dùng với học sinh

Trước khi thu thập dữ liệu, hãy xem xét yêu cầu chấp thuận của nhà trường/phụ huynh, chính sách bảo vệ dữ liệu của đơn vị triển khai, thời hạn lưu trữ và cách sao lưu/khôi phục. Không dùng kết quả tổng hợp để gắn nhãn hoặc đánh giá cá nhân. Dữ liệu tổng hợp chỉ có thể xóa theo ngày hoặc xóa toàn bộ; không thể xóa riêng một lượt đã được cộng dồn.

## Cấu trúc

```text
server.py
requirements.txt
render.yaml
README.md
.gitignore
static/index.html
static/dashboard.html
data/.gitkeep       # không chứa SQLite; database nằm ở Neon
```
