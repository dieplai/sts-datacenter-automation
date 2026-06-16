
# Hướng dẫn setup và chạy first-run

Tài liệu này dùng cho trường hợp vừa `git clone` project về máy mới và muốn chạy local bằng Docker.

## 1. Yêu cầu trước khi chạy

Cần có sẵn:

- Docker Desktop hoặc Docker Engine có hỗ trợ `docker compose`
- Python local để chạy script lấy Google OAuth token
- `uv` để chạy Python script trong project
- File Google OAuth client secret: `client_secret.json`(https://console.cloud.google.com/) 
- Lấy trong link trên sau đó tạo Project -> Enable google drive api service
Kiểm tra nhanh:

```bash
docker --version
docker compose version
uv --version
```

## 2. Chuẩn bị file `.env`

Project chỉ dùng một file môi trường duy nhất:

```text
.env
```

Tạo file `.env` ở root project: Copy nội dung từ `example.env` qua rồi chỉnh sửa


Lưu ý:

- `POSTGRES_HOST=postgres`, không dùng `localhost` khi chạy trong Docker.
- `MONGO_HOST=mongo`, không dùng `localhost` khi chạy trong Docker.
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` phải trỏ tới host `postgres`.
- `GOOGLE_CREDENTIALS_PATH` trong container là `/opt/airflow/client_secret.json`.

## 3. Chuẩn bị Google Drive credentials

Đặt file OAuth client secret vào một trong hai vị trí sau:

```text
client_secret.json
```

hoặc:

```text
google_tokens/client_secret.json
```

Khuyến nghị dùng root project:

```bash
cp /path/to/client_secret.json ./client_secret.json
```

## File này không commit lên git.

## 4. Chạy first-run

Chạy:

```bash
./docker/first-run.sh
```

Script sẽ làm các bước:

1. Tạo folder `google_tokens/`
2. Copy `client_secret.json` vào đúng vị trí cần mount
3. Chạy ``
4. Mở Google consent screen để lấy token lần đầu
5. Lưu token vào `google_tokens/client_secret.token.json`
6. Build Docker image Airflow local
7. Start Postgres và MongoDB
8. Chạy `docker/init-dbs.sql`
9. Chạy `docker/init-mongo.js`
10. Chạy Airflow init
11. Start Airflow webserver, scheduler, dag-processor

Khi browser Google consent hiện lên:

1. Chọn Google account có quyền đọc Drive folder
2. Accept permission
3. Đợi terminal báo token valid

Sau khi xong, truy cập:

```text
http://localhost:8080
```

Login mặc định:

```text
admin / admin
```

## 5. Chạy các lần sau

Sau first-run, không cần init lại DB nữa. Chỉ chạy:

```bash
./docker/start.sh
```

Script này sẽ:

- `docker compose up -d postgres mongo`
- health-check Postgres
- health-check MongoDB
- start Airflow runtime services
- health-check Airflow API

## 6. Reset sạch local Docker state

Nếu muốn xoá sạch container, volume, DB local:

```bash
docker compose down --volumes --remove-orphans
```

Sau đó chạy lại:

```bash
./docker/first-run.sh
```

Nếu muốn reset ngay trong first-run:

```bash
RESET_LOCAL_DATA=1 ./docker/first-run.sh
```

## 7. Các file local không commit

Các file sau là local config/secret, không commit:

```text
.env
client_secret.json
client_secret.token.json
google_tokens/
service_settings.json
```

## 8. Lỗi thường gặp

### Lỗi `could not translate host name "airflow-postgres"`

Nguyên nhân: `.env` đang trỏ sai host DB.

Sửa:

```env
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://stsbeyond:1@postgres/airflow
```

Sau đó chạy lại:

```bash
docker compose down --volumes --remove-orphans
./docker/first-run.sh
```

### Không login được `admin/admin`

Kiểm tra file:

```text
config/simple_auth_manager_passwords.json
```

Nội dung local mong muốn:

```json
{"admin": "admin"}
```

Sau đó restart:

```bash
docker compose restart airflow-webserver airflow-scheduler airflow-dag-processor
```

Nếu vẫn không vào được, mở tab ẩn danh hoặc clear site data cho `localhost:8080`.

### Lỗi Google token expired hoặc revoked

Xoá token cũ:

```bash
rm -f google_tokens/client_secret.token.json client_secret.token.json
```

Chạy lại:

```bash
./docker/first-run.sh
```

Google consent screen sẽ mở lại để lấy token mới.

### Port đã bị dùng

Các port mặc định:

- Airflow UI: `8080`
- Postgres host port: `5434`
- MongoDB host port: `27017`

Kiểm tra process đang chiếm port:

```bash
lsof -i :8080
lsof -i :5434
lsof -i :27017
```

### Kiểm tra container

```bash
docker compose ps
```

Xem log:

```bash
docker compose logs -f airflow-webserver
docker compose logs -f airflow-scheduler
docker compose logs -f airflow-dag-processor
docker compose logs -f postgres
docker compose logs -f mongo
```

## 9. Kiểm tra sau khi chạy thành công

Airflow UI:

```text
http://localhost:8080
```

PostgreSQL app DB từ host:

```text
localhost:5434
database: data_ingestion
user: stsbeyond
password: 1
```

MongoDB từ host:

```text
localhost:27017
database: etl_pipeline_db
```

Kiểm tra nhanh Airflow health:

```bash
curl http://localhost:8080/api/v2/monitor/health
```
