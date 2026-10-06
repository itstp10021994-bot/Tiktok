# TikTok Auto Poster

Ứng dụng tự động lấy video từ **một thư mục trên máy** và đăng lên **TikTok** vào các **khung giờ cố định** (ví dụ 08:00, 12:00, 19:30 mỗi ngày).

Ứng dụng dùng **TikTok Content Posting API chính thức** (không giả lập trình duyệt), nên không cần lưu mật khẩu và ít có nguy cơ bị khóa tài khoản.

## Cách hoạt động

```
videos/                      ← thư mục bạn bỏ video vào
├── 01_intro.mp4
├── 02_review.mp4
├── 02_review.txt            ← caption cho 02_review.mp4 (tùy chọn)
├── posted/                  ← video đã đăng được chuyển vào đây
└── failed/                  ← video lỗi quá số lần thử
```

* Đến mỗi khung giờ, app lấy video **đầu tiên** trong thư mục (theo tên A→Z hoặc theo file cũ nhất), upload lên TikTok rồi chuyển file sang `posted/`.
* **Caption** lấy từ file `.txt` trùng tên với video. Nếu không có file này thì dùng `default_caption` trong cấu hình.
* Nếu đăng lỗi, video sẽ được thử lại ở khung giờ sau. Lỗi quá `max_attempts` lần thì video bị chuyển sang `failed/`.
* File vừa mới copy vào (sửa đổi trong vòng 15 giây) sẽ chưa được đăng, để tránh upload file đang copy dở.
* Token đăng nhập được tự động làm mới (access token hết hạn sau 24h, refresh token sau 365 ngày).
* Log được ghi vào `.tiktok_data/tiktok_scheduler.log`, lịch sử đăng ở `.tiktok_data/state.json`.

## 1. Tạo app trên TikTok for Developers (làm một lần)

1. Vào <https://developers.tiktok.com>, đăng nhập và chọn **Manage apps → Connect an app**.
2. Thêm các sản phẩm **Login Kit** và **Content Posting API**.
   * Trong Content Posting API, bật **Direct Post** nếu muốn đăng thẳng.
3. Thêm các scope: `user.info.basic`, `video.publish`, `video.upload`.
4. Khai báo **Redirect URI**:
   * App loại **Desktop**: `http://127.0.0.1:8765/callback/` (giữ đúng như trong `config.toml`).
   * App loại **Web**: TikTok bắt buộc URL `https://...`. Đặt `app_type = "web"`. Sau khi đăng nhập, bạn chỉ cần copy URL trên thanh địa chỉ rồi dán vào cửa sổ dòng lệnh.
5. Copy **Client key** và **Client secret**.

> ⚠️ **Lưu ý quan trọng:** khi app **chưa được TikTok duyệt (audit)**, mọi video đăng qua API chỉ ở chế độ
> **riêng tư (`SELF_ONLY`)**, và tối đa 5 tài khoản được đăng mỗi ngày. Muốn đăng công khai, bạn cần gửi app cho
> TikTok duyệt (mục *Content Posting API → Audit*). Cách khác là đặt `mode = "inbox"`: video sẽ được gửi vào hộp
> thư TikTok trên điện thoại dưới dạng bản nháp, bạn mở app và bấm **Đăng**.

## 2. Cài đặt

Cần **Python 3.11** trở lên.

```bash
git clone <repo này> && cd Tiktok
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp config.example.toml config.toml     # Windows: copy config.example.toml config.toml
```

Mở `config.toml` rồi điền `client_key`, `client_secret`, đường dẫn thư mục video (`folders.watch`) và các khung giờ (`schedule.times`).

## 3. Sử dụng

```bash
python -m tiktok_scheduler auth        # đăng nhập TikTok (mở trình duyệt), chỉ cần làm 1 lần
python -m tiktok_scheduler check       # kiểm tra kết nối, xem quyền riêng tư được phép
python -m tiktok_scheduler queue       # xem danh sách video và giờ dự kiến đăng
python -m tiktok_scheduler post-now    # đăng ngay 1 video (thử nghiệm)
python -m tiktok_scheduler run         # chạy liên tục, tự đăng theo lịch
```

Dùng `-c đường/dẫn/config.toml` nếu file cấu hình nằm ở chỗ khác.

Ví dụ kết quả của lệnh `queue`:

```
Khung giờ: 08:00, 12:00, 19:30 (mon, ..., sun), 1 video/slot, múi giờ Asia/Ho_Chi_Minh

2 video chờ đăng:
  Tue 06/10 08:00  01_intro.mp4  |  01_intro #fyp #xuhuong
  Tue 06/10 12:00  02_review.mp4  |  Video review hay #review
```

## 4. Chạy nền tự động

App chỉ đăng được khi máy đang bật. Nếu máy ngủ và lỡ khung giờ quá 30 phút, khung giờ đó sẽ bị bỏ qua để tránh đăng dồn.

**Cách A: chạy `run` liên tục**

* Windows: nhấp đúp `start_windows.bat`. Để tự chạy khi bật máy, nhấn `Win+R`, gõ `shell:startup`, rồi đặt shortcut của file `.bat` vào thư mục vừa mở.
* macOS/Linux: `./start.sh` (có thể dùng `tmux`, `systemd` hoặc `launchd`).

**Cách B: dùng bộ hẹn giờ của hệ điều hành gọi `post-now`**

* Windows Task Scheduler: tạo task chạy hằng ngày vào từng khung giờ, với
  Program: `C:\đường\dẫn\Tiktok\.venv\Scripts\python.exe`,
  Arguments: `-m tiktok_scheduler post-now`,
  Start in: `C:\đường\dẫn\Tiktok`.
* cron (Linux/macOS):
  ```cron
  0 8,12 * * *  cd /path/to/Tiktok && .venv/bin/python -m tiktok_scheduler post-now
  30 19 * * *   cd /path/to/Tiktok && .venv/bin/python -m tiktok_scheduler post-now
  ```

## Yêu cầu video của TikTok

* Định dạng MP4 (khuyên dùng H.264), MOV hoặc WebM. Dung lượng tối đa 4GB.
* Thời lượng không vượt quá giới hạn của tài khoản (lệnh `check` sẽ hiển thị).
* Caption tối đa 2200 ký tự, có thể chứa `#hashtag` và `@mention`.

## Phát triển

```bash
pip install pytest
python -m pytest
```
