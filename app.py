# -*- coding: utf-8 -*-
import io
import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client, Client

st.set_page_config(page_title="Chấm công Online", page_icon="🕒", layout="wide")

# -------------------- CẤU HÌNH --------------------
WORK_START = time(7, 30)
WORK_END = time(16, 30)
BREAKS = [(time(10, 0), time(10, 10)), (time(12, 20), time(13, 0))]
STANDARD_MINUTES = 8 * 60
OT_STEP_MINUTES = 15
SATURDAY_STANDARD_HOURS = 6.33
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

st.title("🕒 Chấm công Online")
st.caption("Chấm công vào/ra • Theo dõi công • Báo cáo tháng • Xuất Excel")


def get_secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return default


def connect_supabase():
    url = get_secret("SUPABASE_URL")
    anon_key = get_secret("SUPABASE_ANON_KEY")
    service_key = get_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not anon_key:
        st.error("Chưa cấu hình SUPABASE_URL và SUPABASE_ANON_KEY trong Streamlit Secrets.")
        st.info("Xem file README.md để thiết lập Supabase và triển khai.")
        st.stop()
    public_client = create_client(url, anon_key)
    admin_client = create_client(url, service_key) if service_key else None
    token = st.session_state.get("access_token")
    if token:
        public_client.postgrest.auth(token)
    return public_client, admin_client


def safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(VN_TZ).replace(tzinfo=None)
    return parsed


def combine_day_time(day, value):
    if not value:
        return None
    if isinstance(value, time):
        return datetime.combine(day, value)
    if isinstance(value, datetime):
        return value
    return datetime.combine(day, time.fromisoformat(str(value)))


def overlap_minutes(start_dt, end_dt, break_start, break_end):
    bs = datetime.combine(start_dt.date(), break_start)
    be = datetime.combine(start_dt.date(), break_end)
    left = max(start_dt, bs)
    right = min(end_dt, be)
    return max(0, int((right - left).total_seconds() // 60))


def calculate_attendance(work_date, clock_in, clock_out):
    """Trả về phút làm thực tế, giờ công chuẩn, tăng ca và ghi chú.
    Chủ nhật: khung 07:30-16:10 được quy đổi cố định 8,0 giờ.
    Thứ 7: tăng ca = tổng giờ làm thực tế sau khi trừ nghỉ - 6,33, không âm.
    Ngày thường: tối đa 8 giờ chuẩn; phần vượt tính OT theo từng mốc đủ 15 phút.
    """
    if not clock_in or not clock_out:
        return {"worked_minutes": 0, "regular_hours": 0.0, "overtime_hours": 0.0, "total_hours": 0.0, "note": "Chưa đủ giờ vào/ra"}

    start_dt = combine_day_time(work_date, clock_in)
    end_dt = combine_day_time(work_date, clock_out)
    if end_dt <= start_dt:
        return {"worked_minutes": 0, "regular_hours": 0.0, "overtime_hours": 0.0, "total_hours": 0.0, "note": "Giờ ra phải sau giờ vào"}

    elapsed_minutes = int((end_dt - start_dt).total_seconds() // 60)
    deducted_breaks = sum(overlap_minutes(start_dt, end_dt, bs, be) for bs, be in BREAKS)
    worked_minutes = max(0, elapsed_minutes - deducted_breaks)

    # Chủ nhật: theo quy định công ty, ca 07:30-16:10 được tính 8,0 giờ.
    if work_date.weekday() == 6 and start_dt.time() == time(7, 30) and end_dt.time() == time(16, 10):
        return {"worked_minutes": 480, "regular_hours": 8.0, "overtime_hours": 0.0, "total_hours": 8.0, "note": "Chủ nhật: ca 07:30-16:10 tính 8,0 giờ"}

    worked_hours = worked_minutes / 60.0

    if work_date.weekday() == 5:  # Thứ 7
        overtime = max(0.0, worked_hours - SATURDAY_STANDARD_HOURS)
        # Làm tròn xuống theo mốc 15 phút đủ.
        overtime = int((overtime * 60) // OT_STEP_MINUTES) * 0.25
        regular = min(worked_hours, SATURDAY_STANDARD_HOURS)
        return {
            "worked_minutes": worked_minutes,
            "regular_hours": round(regular, 2),
            "overtime_hours": round(overtime, 2),
            "total_hours": round(regular + overtime, 2),
            "note": "Thứ 7: tăng ca = giờ làm thực tế - 6,33; làm tròn xuống mốc 15 phút"
        }

    overtime_minutes = max(0, worked_minutes - STANDARD_MINUTES)
    overtime_hours = (overtime_minutes // OT_STEP_MINUTES) * 0.25
    regular_hours = min(worked_minutes, STANDARD_MINUTES) / 60.0
    return {
        "worked_minutes": worked_minutes,
        "regular_hours": round(regular_hours, 2),
        "overtime_hours": round(overtime_hours, 2),
        "total_hours": round(regular_hours + overtime_hours, 2),
        "note": "Ngày thường: 8 giờ chuẩn; tăng ca làm tròn xuống mốc 15 phút"
    }


def fmt_hours(value):
    return f"{safe_float(value):.2f}".rstrip("0").rstrip(".")


def fetch_profile(client, user_id):
    result = client.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    return result.data[0] if result.data else None


def logout():
    try:
        st.session_state.supabase.auth.sign_out()
    except Exception:
        pass
    for key in ["access_token", "user", "profile", "supabase"]:
        st.session_state.pop(key, None)
    st.rerun()


public_client, admin_client = connect_supabase()

# -------------------- ĐĂNG NHẬP --------------------
if not st.session_state.get("user"):
    st.subheader("Đăng nhập")
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="ten@congty.com")
        password = st.text_input("Mật khẩu", type="password")
        submitted = st.form_submit_button("Đăng nhập", type="primary", use_container_width=True)
    if submitted:
        try:
            response = public_client.auth.sign_in_with_password({"email": email.strip(), "password": password})
            st.session_state.supabase = public_client
            st.session_state.user = response.user.model_dump() if hasattr(response.user, "model_dump") else response.user
            st.session_state.access_token = response.session.access_token
            public_client.postgrest.auth(response.session.access_token)
            profile = fetch_profile(public_client, response.user.id)
            if not profile:
                st.error("Tài khoản chưa được cấp hồ sơ chấm công. Vui lòng liên hệ quản trị viên.")
                st.session_state.pop("user", None)
                st.session_state.pop("access_token", None)
                st.stop()
            st.session_state.profile = profile
            st.rerun()
        except Exception as exc:
            st.error("Đăng nhập thất bại. Kiểm tra email/mật khẩu hoặc liên hệ quản trị viên.")
            st.caption(str(exc))
    st.info("Tài khoản do quản trị viên tạo. Liên hệ quản trị viên nếu bạn chưa có tài khoản.")
    st.stop()

# Rebuild authenticated client on reruns
public_client, admin_client = connect_supabase()
user = st.session_state["user"]
profile = st.session_state.get("profile") or fetch_profile(public_client, user["id"])
if not profile:
    st.error("Không tìm thấy hồ sơ nhân viên. Vui lòng liên hệ quản trị viên.")
    if st.button("Đăng xuất"):
        logout()
    st.stop()
st.session_state.profile = profile
is_admin = profile.get("role") == "admin"
employee_name = profile.get("full_name") or user.get("email") or "Nhân viên"

with st.sidebar:
    st.success(f"Xin chào, {employee_name}")
    st.caption(f"Vai trò: {'Quản trị viên' if is_admin else 'Nhân viên'}")
    if st.button("Đăng xuất", use_container_width=True):
        logout()
    page_options = ["Chấm công", "Lịch sử của tôi"]
    if is_admin:
        page_options += ["Quản lý nhân viên", "Báo cáo toàn công ty"]
    page = st.radio("Menu", page_options)

# -------------------- TIỆN ÍCH DỮ LIỆU --------------------
def load_attendance(start_date=None, end_date=None, employee_id=None):
    query = public_client.table("attendance").select("*").order("work_date", desc=True)
    if start_date:
        query = query.gte("work_date", str(start_date))
    if end_date:
        query = query.lte("work_date", str(end_date))
    if employee_id:
        query = query.eq("employee_id", employee_id)
    return query.execute().data or []


def upsert_attendance(work_date, clock_in=None, clock_out=None, employee_id=None):
    employee_id = employee_id or user["id"]
    existing = public_client.table("attendance").select("*").eq("employee_id", employee_id).eq("work_date", str(work_date)).limit(1).execute().data
    now = datetime.now(VN_TZ).replace(microsecond=0).isoformat()
    if existing:
        row = existing[0]
        update_data = {"updated_at": now}
        if clock_in is not None:
            update_data["clock_in"] = clock_in
        if clock_out is not None:
            update_data["clock_out"] = clock_out
        public_client.table("attendance").update(update_data).eq("id", row["id"]).execute()
    else:
        payload = {
            "employee_id": employee_id,
            "work_date": str(work_date),
            "clock_in": clock_in,
            "clock_out": clock_out,
            "updated_at": now
        }
        public_client.table("attendance").insert(payload).execute()


def attendance_dataframe(rows, include_email=False):
    if not rows:
        return pd.DataFrame()
    profiles = {}
    if include_email and is_admin:
        try:
            ids = list({r["employee_id"] for r in rows})
            if ids:
                profs = public_client.table("profiles").select("id,full_name,email").in_("id", ids).execute().data or []
                profiles = {p["id"]: p for p in profs}
        except Exception:
            profiles = {}
    result = []
    for row in rows:
        d = date.fromisoformat(row["work_date"])
        cin = parse_dt(row.get("clock_in"))
        cout = parse_dt(row.get("clock_out"))
        if cin and cin.date() != d:
            cin = datetime.combine(d, cin.time())
        if cout and cout.date() != d:
            cout = datetime.combine(d, cout.time())
        calc = calculate_attendance(d, cin, cout)
        prof = profiles.get(row["employee_id"], {})
        result.append({
            "Ngày": d.strftime("%d/%m/%Y"),
            "Thứ": ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"][d.weekday()],
            "Nhân viên": prof.get("full_name", "") if include_email else employee_name,
            "Email": prof.get("email", "") if include_email else "",
            "Giờ vào": cin.strftime("%H:%M:%S") if cin else "",
            "Giờ ra": cout.strftime("%H:%M:%S") if cout else "",
            "Giờ thực tế": round(calc["worked_minutes"] / 60, 2),
            "Công chuẩn (giờ)": calc["regular_hours"],
            "Tăng ca (giờ)": calc["overtime_hours"],
            "Tổng tính công (giờ)": calc["total_hours"],
            "Ghi chú": calc["note"]
        })
    return pd.DataFrame(result)


def excel_bytes(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="ChamCong")
        ws = writer.sheets["ChamCong"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for column_cells in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in column_cells)
            ws.column_dimensions[column_cells[0].column_letter].width = min(max_len + 2, 42)
    return output.getvalue()


# -------------------- CHẤM CÔNG --------------------
if page == "Chấm công":
    today = date.today()
    now = datetime.now(VN_TZ).replace(tzinfo=None)
    st.subheader("Chấm công hôm nay")
    c1, c2, c3 = st.columns(3)
    c1.metric("Ngày", today.strftime("%d/%m/%Y"))
    c2.metric("Giờ hiện tại", now.strftime("%H:%M:%S"))
    c3.metric("Loại ngày", ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"][today.weekday()])

    today_rows = public_client.table("attendance").select("*").eq("employee_id", user["id"]).eq("work_date", str(today)).limit(1).execute().data
    current = today_rows[0] if today_rows else {}
    cin = parse_dt(current.get("clock_in"))
    cout = parse_dt(current.get("clock_out"))

    m1, m2 = st.columns(2)
    m1.metric("Giờ vào", cin.strftime("%H:%M:%S") if cin else "Chưa chấm")
    m2.metric("Giờ ra", cout.strftime("%H:%M:%S") if cout else "Chưa chấm")

    b1, b2 = st.columns(2)
    with b1:
        if not cin:
            if st.button("🟢 CHẤM CÔNG VÀO", type="primary", use_container_width=True):
                try:
                    upsert_attendance(today, clock_in=datetime.now(VN_TZ).replace(microsecond=0).isoformat())
                    st.success("Đã ghi nhận giờ vào.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không thể chấm công vào: {exc}")
        else:
            st.button("🟢 ĐÃ CHẤM CÔNG VÀO", disabled=True, use_container_width=True)
    with b2:
        if cin and not cout:
            if st.button("🔴 CHẤM CÔNG RA", type="primary", use_container_width=True):
                try:
                    if now <= cin:
                        st.error("Giờ ra phải sau giờ vào.")
                    else:
                        upsert_attendance(today, clock_out=datetime.now(VN_TZ).replace(microsecond=0).isoformat())
                        st.success("Đã ghi nhận giờ ra.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Không thể chấm công ra: {exc}")
        elif cout:
            st.button("🔴 ĐÃ CHẤM CÔNG RA", disabled=True, use_container_width=True)
        else:
            st.button("🔴 CHẤM CÔNG RA", disabled=True, use_container_width=True)

    if cin and cout:
        calc = calculate_attendance(today, cin, cout)
        st.divider()
        a, b, c = st.columns(3)
        a.metric("Giờ làm thực tế", f"{calc['worked_minutes'] / 60:.2f}")
        b.metric("Công chuẩn (giờ)", fmt_hours(calc["regular_hours"]))
        c.metric("Tăng ca (giờ)", fmt_hours(calc["overtime_hours"]))
        st.caption(calc["note"])
    st.info("Lưu ý: thời gian lấy từ máy chủ ứng dụng. Hãy chấm công bằng tài khoản cá nhân; nếu chấm sai, liên hệ quản trị viên.")

# -------------------- LỊCH SỬ CỦA TÔI --------------------
elif page == "Lịch sử của tôi":
    st.subheader("Lịch sử chấm công của tôi")
    today = date.today()
    col1, col2 = st.columns(2)
    month = col1.selectbox("Tháng", list(range(1, 13)), index=today.month - 1)
    year = col2.selectbox("Năm", list(range(today.year - 3, today.year + 2)), index=3)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    rows = load_attendance(start, end, user["id"])
    df = attendance_dataframe(rows)
    if df.empty:
        st.info("Tháng này chưa có dữ liệu chấm công.")
    else:
        st.dataframe(df.drop(columns=["Email"]), use_container_width=True, hide_index=True)
        total_regular = df["Công chuẩn (giờ)"].sum()
        total_ot = df["Tăng ca (giờ)"].sum()
        total = df["Tổng tính công (giờ)"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Tổng công chuẩn", f"{total_regular:.2f} giờ")
        c2.metric("Tổng tăng ca", f"{total_ot:.2f} giờ")
        c3.metric("Tổng giờ tính công", f"{total:.2f} giờ")
        st.download_button("📥 Xuất Excel tháng này", data=excel_bytes(df.drop(columns=["Email"])),
                           file_name=f"cham_cong_{year}_{month:02d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -------------------- QUẢN LÝ NHÂN VIÊN --------------------
elif page == "Quản lý nhân viên" and is_admin:
    st.subheader("Quản lý nhân viên")
    if not admin_client:
        st.error("Thiếu SUPABASE_SERVICE_ROLE_KEY. Thêm khóa này trong Streamlit Secrets để quản trị tạo tài khoản.")
    else:
        with st.expander("➕ Tạo tài khoản nhân viên", expanded=True):
            with st.form("create_employee"):
                full_name = st.text_input("Họ và tên")
                new_email = st.text_input("Email đăng nhập")
                new_password = st.text_input("Mật khẩu tạm thời (ít nhất 8 ký tự)", type="password")
                role = st.selectbox("Vai trò", ["employee", "admin"], format_func=lambda x: "Nhân viên" if x == "employee" else "Quản trị viên")
                create = st.form_submit_button("Tạo tài khoản", type="primary")
            if create:
                if not full_name.strip() or not new_email.strip() or len(new_password) < 8:
                    st.error("Vui lòng nhập họ tên, email hợp lệ và mật khẩu ít nhất 8 ký tự.")
                else:
                    try:
                        created = admin_client.auth.admin.create_user({
                            "email": new_email.strip().lower(),
                            "password": new_password,
                            "email_confirm": True,
                            "user_metadata": {"full_name": full_name.strip()}
                        })
                        new_user = created.user
                        admin_client.table("profiles").upsert({
                            "id": new_user.id,
                            "email": new_email.strip().lower(),
                            "full_name": full_name.strip(),
                            "role": role
                        }).execute()
                        st.success("Đã tạo tài khoản. Hãy gửi email đăng nhập và mật khẩu tạm thời cho nhân viên qua kênh riêng.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Không tạo được tài khoản: {exc}")

    st.markdown("#### Danh sách nhân viên")
    try:
        profiles = public_client.table("profiles").select("id,full_name,email,role,created_at").order("full_name").execute().data or []
        if profiles:
            p_df = pd.DataFrame([{
                "Họ tên": p.get("full_name", ""),
                "Email": p.get("email", ""),
                "Vai trò": "Quản trị viên" if p.get("role") == "admin" else "Nhân viên",
                "Ngày tạo": str(p.get("created_at", ""))[:10]
            } for p in profiles])
            st.dataframe(p_df, use_container_width=True, hide_index=True)
        else:
            st.info("Chưa có hồ sơ.")
    except Exception as exc:
        st.error(f"Không tải được danh sách nhân viên: {exc}")

# -------------------- BÁO CÁO TOÀN CÔNG TY --------------------
elif page == "Báo cáo toàn công ty" and is_admin:
    st.subheader("Báo cáo chấm công toàn công ty")
    today = date.today()
    c1, c2, c3 = st.columns(3)
    month = c1.selectbox("Tháng báo cáo", list(range(1, 13)), index=today.month - 1)
    year = c2.selectbox("Năm báo cáo", list(range(today.year - 3, today.year + 2)), index=3)
    profiles = public_client.table("profiles").select("id,full_name,email").order("full_name").execute().data or []
    profile_map = {p["id"]: p for p in profiles}
    choices = ["Tất cả nhân viên"] + [f'{p.get("full_name") or p.get("email")} ({p.get("email")})' for p in profiles]
    selected = c3.selectbox("Nhân viên", choices)
    selected_id = None
    if selected != "Tất cả nhân viên":
        selected_email = selected.split("(")[-1].rstrip(")")
        selected_id = next((p["id"] for p in profiles if p.get("email") == selected_email), None)

    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    rows = load_attendance(start, end, selected_id)
    df = attendance_dataframe(rows, include_email=True)
    if df.empty:
        st.info("Không có dữ liệu trong tháng đã chọn.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        totals = df.groupby("Nhân viên", dropna=False).agg(
            **{"Số ngày có dữ liệu": ("Ngày", "count"),
               "Công chuẩn (giờ)": ("Công chuẩn (giờ)", "sum"),
               "Tăng ca (giờ)": ("Tăng ca (giờ)", "sum"),
               "Tổng tính công (giờ)": ("Tổng tính công (giờ)", "sum")}
        ).reset_index()
        st.markdown("#### Tổng hợp theo nhân viên")
        st.dataframe(totals, use_container_width=True, hide_index=True)
        st.download_button("📥 Xuất Excel báo cáo", data=excel_bytes(df),
                           file_name=f"bao_cao_cham_cong_{year}_{month:02d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.download_button("📥 Xuất Excel tổng hợp", data=excel_bytes(totals),
                           file_name=f"tong_hop_cham_cong_{year}_{month:02d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
