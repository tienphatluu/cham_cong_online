# App Chấm công Online — Streamlit + Supabase

## Tính năng
- Đăng nhập bằng email/mật khẩu Supabase Auth.
- Nhân viên chấm công vào/ra; mỗi nhân viên có tối đa một bản ghi/ngày.
- Lịch sử chấm công cá nhân theo tháng.
- Quản trị viên tạo tài khoản, phân vai trò nhân viên/quản trị.
- Báo cáo tháng toàn công ty, lọc nhân viên, xuất Excel.
- Supabase PostgreSQL lưu dữ liệu cloud; RLS giới hạn nhân viên chỉ xem/sửa bản ghi của mình.

## Quy tắc tính công hiện tại
- Ngày thường: giờ làm thực tế = khoảng thời gian vào-ra trừ phần giao với nghỉ 10:00–10:10 và 12:20–13:00. Công chuẩn tối đa 8 giờ; phần vượt 8 giờ tính tăng ca theo mốc đủ 15 phút, làm tròn xuống. Ví dụ 22 phút tăng ca = 0,25 giờ; 30 phút = 0,50 giờ.
- Thứ 7: giờ làm thực tế sau khi trừ các khoảng nghỉ; tăng ca = max(0, tổng giờ thực tế - 6,33), làm tròn xuống theo mốc 15 phút. Công chuẩn tối đa 6,33 giờ.
- Chủ nhật: nếu giờ vào chính xác 07:30 và giờ ra chính xác 16:10, hệ thống tính cố định 8,0 giờ theo yêu cầu. Các khung giờ khác dùng cách tính thời gian thực tế trừ giờ nghỉ.
- Thời gian chấm công và hiển thị được xử lý theo múi giờ Việt Nam (Asia/Ho_Chi_Minh), không phụ thuộc múi giờ mặc định của máy chủ.

## 1. Tạo Supabase project
1. Vào https://supabase.com/ và tạo project.
2. Mở **Project Settings → API** (hoặc API Keys), lấy Project URL và anon/publishable key.
3. Lấy service_role/secret key chỉ để lưu trong Streamlit Secrets. **Không đưa service role key vào mã nguồn, GitHub hay giao diện trình duyệt.**
4. Mở **SQL Editor → New query**, dán toàn bộ nội dung `schema.sql`, rồi bấm Run.

## 2. Tạo tài khoản quản trị đầu tiên
1. Mở Supabase **Authentication → Users → Add user**.
2. Tạo user bằng email và mật khẩu mạnh, chọn xác nhận email nếu có tùy chọn.
3. Trong SQL Editor, chạy câu lệnh bên dưới và thay email bằng email quản trị vừa tạo:

```sql
insert into public.profiles (id, email, full_name, role)
select id, email, coalesce(raw_user_meta_data->>'full_name', 'Quản trị viên'), 'admin'
from auth.users
where email = 'admin@congty.com'
on conflict (id) do update set role = 'admin';
```

4. Không cần đặt email mẫu `admin@congty.com` nếu bạn dùng email khác; hãy sửa email trong câu SQL.

## 3. Chạy thử trên máy tính
Cài Python 3.10 hoặc mới hơn. Giải nén thư mục này, mở terminal/cmd tại thư mục dự án và chạy:

```bash
python -m venv .venv
```

Windows:
```bat
.venv\Scripts\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Cài thư viện:
```bash
pip install -r requirements.txt
```

Tạo file `.streamlit/secrets.toml` (tạo thư mục `.streamlit` nếu chưa có) với nội dung tương tự `secrets.example.toml`, thay bằng thông tin thật từ Supabase.

Chạy:
```bash
streamlit run app.py
```

## 4. Đưa lên Streamlit Community Cloud
1. Tạo repository GitHub riêng và tải lên `app.py`, `requirements.txt`, `schema.sql`, `README.md`. Không tải lên file chứa secret thật.
2. Vào https://share.streamlit.io/ và kết nối GitHub.
3. Chọn repository, nhánh, file chính `app.py`, bấm Deploy.
4. Mở **App settings → Secrets**, dán các khóa vào theo mẫu `secrets.example.toml`, thay giá trị thật rồi lưu.
5. Mở đường dẫn app, đăng nhập tài khoản quản trị đầu tiên, vào **Quản lý nhân viên** để tạo các tài khoản còn lại.

## Lưu ý bảo mật và vận hành
- `SUPABASE_SERVICE_ROLE_KEY` có quyền cao: chỉ lưu trong Secrets phía máy chủ Streamlit, tuyệt đối không commit vào Git.
- Nhân viên cần tài khoản riêng; không dùng chung tài khoản.
- Hiện app không có GPS, ảnh xác thực, giới hạn địa chỉ IP hay quy trình duyệt chỉnh sửa công.
- Nếu cần sửa giờ chấm công sai, nên bổ sung tính năng chỉnh sửa có nhật ký/audit log; không nên cho nhân viên tự sửa trực tiếp.
- Quy tắc Chủ nhật 8,0 giờ chỉ áp dụng khi giờ vào/ra đúng 07:30 và 16:10. Cách tính thứ 7 dùng 6,33 giờ làm chuẩn, tăng ca làm tròn xuống mỗi 15 phút.
- Trước khi áp dụng tính lương chính thức, hãy kiểm thử các ca thực tế và xác nhận cách xử lý đi trễ/về sớm, ngày lễ, ca qua đêm và tăng ca vào Chủ nhật với bộ phận nhân sự.
