"""
电车票务数据平台 - 主应用
提供 Oracle 数据表浏览与 Excel 下载功能

架构：
- 运行时 Schema Discovery：不需要预先知道表结构
- 表过滤：白名单/黑名单模式，只暴露需要的表
- 下载预检：自动估算文件大小，大数据集引导分片下载
- 流式传输：边读边写，不将整表加载到内存
"""
import os
import re
from datetime import datetime
from urllib.parse import quote

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, Response, abort, jsonify,
)
from flask_login import login_required, login_user, logout_user, current_user

from config import Config, get_hardware_info
from auth import (
    login_manager, User, init_db,
    _get_user_by_username, get_all_users,
    create_user, delete_user, reset_user_password,
    change_password, toggle_user_active, record_login,
    admin_required,
)
from werkzeug.security import check_password_hash
import export

# 演示模式：用模拟数据替代 Oracle
if Config.DEMO_MODE:
    import db_demo as db_oracle
else:
    import db_oracle


def _parse_date_filter(req):
    """
    从请求参数中提取日期筛选条件。
    返回 (date_column, date_start, date_end) 三元组，
    任一缺失则全部为 None。
    """
    col = req.args.get("date_col", "").strip()
    start = req.args.get("date_start", "").strip()
    end = req.args.get("date_end", "").strip()
    if not col or not start or not end:
        return None, None, None
    try:
        ds = datetime.strptime(start, "%Y-%m-%d").date()
        de = datetime.strptime(end, "%Y-%m-%d").date()
        return col, ds, de
    except ValueError:
        return None, None, None


def _make_date_params(date_column, date_start, date_end):
    """构建传递给 db 模块的日期筛选关键字参数"""
    if date_column and date_start and date_end:
        return {"date_column": date_column, "date_start": date_start, "date_end": date_end}
    return {}


def _parse_format(req):
    """从请求参数解析导出格式：xlsx 或 csv，默认 xlsx"""
    fmt = req.args.get("format", "xlsx").lower()
    return fmt if fmt in ("xlsx", "csv") else "xlsx"


# ===== 应用工厂 =====

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 确保 instance 目录存在
    os.makedirs(app.instance_path, exist_ok=True)

    # 初始化
    login_manager.init_app(app)
    init_db()

    # 启动时探明硬件（缓存结果供后续 /diagnostics 页面使用）
    get_hardware_info()

    # 上下文处理器
    @app.context_processor
    def inject_globals():
        return {
            "current_year": datetime.now().year,
            "config": Config,
        }

    # ===== 错误处理 =====

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="权限不足，请联系管理员。"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="页面未找到。"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500, message="服务器内部错误，请稍后重试。"), 500

    # ===== 登录相关路由 =====

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if not username or not password:
                flash("请输入用户名和密码。", "warning")
                return render_template("login.html")

            row = _get_user_by_username(username)
            if row is None:
                flash("用户名或密码错误。", "danger")
                return render_template("login.html")

            user = User(row)

            if not user.is_active:
                flash("该账号已被禁用，请联系管理员。", "danger")
                return render_template("login.html")

            if not check_password_hash(user.password_hash, password):
                flash("用户名或密码错误。", "danger")
                return render_template("login.html")

            login_user(user, remember=True)
            record_login(user.id)
            flash(f"欢迎回来，{user.display_name}！", "success")

            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)
            return redirect(url_for("index"))

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("您已安全退出。", "info")
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password_route():
        if request.method == "POST":
            old_pw = request.form.get("old_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")

            if not old_pw or not new_pw:
                flash("请填写所有字段。", "warning")
                return render_template("change_password.html")

            if new_pw != confirm_pw:
                flash("两次输入的新密码不一致。", "warning")
                return render_template("change_password.html")

            if len(new_pw) < 6:
                flash("新密码长度不能少于6位。", "warning")
                return render_template("change_password.html")

            success, msg = change_password(current_user.id, old_pw, new_pw)
            category = "success" if success else "danger"
            flash(msg, category)
            if success:
                return redirect(url_for("index"))

        return render_template("change_password.html")

    # ===== 主页与表浏览 =====

    @app.route("/")
    @login_required
    def index():
        """表列表主页"""
        try:
            search = request.args.get("search", "").strip()
            tables = db_oracle.list_tables(search=search if search else None)

            # 按 owner 分组，同时附加下载方案信息
            grouped = {}
            for t in tables:
                owner = t["owner"]
                grouped.setdefault(owner, []).append(t)

            # 计算过滤模式说明
            filter_info = _get_filter_info()

            return render_template(
                "index.html",
                grouped=grouped,
                search=search,
                table_count=len(tables),
                filter_info=filter_info,
            )
        except Exception as e:
            flash(f"连接 Oracle 数据库失败: {e}", "danger")
            return render_template(
                "index.html",
                grouped={},
                search="",
                table_count=0,
                error=str(e),
                filter_info="",
            )

    @app.route("/table/<table_name>")
    @login_required
    def table_preview(table_name):
        """表数据预览页 + 日期筛选 + 下载方案建议"""
        owner = request.args.get("owner", Config.ORACLE_USER.upper())

        if not re.match(r"^[A-Za-z0-9_$#]+$", table_name):
            abort(400)

        # 日期筛选参数
        date_col, date_start, date_end = _parse_date_filter(request)
        date_kw = _make_date_params(date_col, date_start, date_end)

        try:
            columns_info = db_oracle.get_table_columns(owner, table_name)
            date_columns = db_oracle.get_date_columns(owner, table_name)
            columns, rows = db_oracle.get_table_data(
                owner, table_name, limit=Config.MAX_PREVIEW_ROWS, **date_kw
            )

            try:
                plan = db_oracle.get_download_plan(owner, table_name, **date_kw)
            except Exception:
                plan = {"row_count": 0, "est_size_mb": 0, "needs_split": False,
                        "chunks": 0, "chunk_rows": 0,
                        "warning_level": "safe", "warning_message": ""}

            return render_template(
                "table.html",
                table_name=table_name, owner=owner,
                columns_info=columns_info, columns=columns, rows=rows, plan=plan,
                date_columns=date_columns,
                date_col=date_col, date_start=date_start, date_end=date_end,
                preview_limit=Config.MAX_PREVIEW_ROWS,
            )
        except Exception as e:
            flash(f"读取表数据失败: {e}", "danger")
            return redirect(url_for("index"))

    # ===== 下载路由 =====

    def _build_chunk_file(owner, table_name, offset, max_rows, date_kw, fmt="xlsx"):
        """将单个分片生成为 BytesIO（Excel 或 CSV），供单文件下载和 ZIP 打包复用。"""
        from io import BytesIO
        from openpyxl import Workbook

        row_gen = db_oracle.stream_table_data(
            owner, table_name,
            offset=offset, max_rows=max_rows,
            **(date_kw or {}),
        )
        columns_list = next(row_gen)

        buf = BytesIO()
        if fmt == "csv":
            for chunk in export.generate_csv(columns_list, row_gen):
                buf.write(chunk)
        else:
            wb = Workbook(write_only=True)
            ws = wb.create_sheet(title="数据")
            ws.append(columns_list)
            for batch in row_gen:
                for row in batch:
                    ws.append([export._serialize_value(v) for v in row])
            wb.save(buf)

        buf.seek(0)
        return buf


    @app.route("/download/<table_name>")
    @login_required
    def download(table_name):
        """
        流式下载整表。支持日期筛选、分片、格式选择。

        参数:
            owner       - Schema 名称
            date_col    - 日期列名
            date_start  - 开始日期 (YYYY-MM-DD)
            date_end    - 结束日期 (YYYY-MM-DD)
            chunk       - 分片索引（0 开始）
            confirm     - huge 表确认标志
            format      - xlsx（默认）或 csv

        安全分层：safe → large → huge(需确认) → blocked(仅分片)
        """
        owner = request.args.get("owner", Config.ORACLE_USER.upper())
        if not re.match(r"^[A-Za-z0-9_$#]+$", table_name):
            abort(400)

        date_col, date_start, date_end = _parse_date_filter(request)
        date_kw = _make_date_params(date_col, date_start, date_end)
        fmt = _parse_format(request)

        # 构建带日期筛选的查询参数后缀
        filter_qs = ""
        if date_col:
            filter_qs = f"&date_col={date_col}&date_start={date_start}&date_end={date_end}"

        try:
            plan = db_oracle.get_download_plan(owner, table_name, **date_kw)
        except Exception as e:
            flash(f"无法获取表信息: {e}", "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner) + filter_qs)

        # ---- 分片下载：优先处理（自带行数限制，绕过 blocked/huge 检查） ----
        chunk_index = request.args.get("chunk")
        if chunk_index is not None:
            return _download_chunk(owner, table_name, int(chunk_index), plan, date_kw, fmt)

        # ---- blocked: 拒绝直接下载 ----
        if plan["warning_level"] == "blocked":
            flash(plan["warning_message"], "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner) + filter_qs)

        # ---- huge: 需要用户确认 ----
        if plan["warning_level"] == "huge":
            if request.args.get("confirm") != "1":
                confirm_url = f"?owner={owner}&confirm=1&format={fmt}{filter_qs}"
                flash(
                    f"{plan['warning_message']} "
                    f"<a href='{confirm_url}' class='alert-link'>点击确认下载</a> "
                    f"或使用下方的分片下载。",
                    "warning",
                )
                return redirect(url_for("table_preview", table_name=table_name, owner=owner) + filter_qs)

        # ---- 正常流式下载 ----
        return _stream_download(owner, table_name, plan, date_kw, fmt)


    def _stream_download(owner, table_name, plan, date_kw=None, fmt="xlsx"):
        """流式下载整表（Excel 或 CSV）"""
        if date_kw is None:
            date_kw = {}
        try:
            row_gen = db_oracle.stream_table_data(owner, table_name, **date_kw)
            columns = next(row_gen)

            if fmt == "csv":
                def generate():
                    yield from export.generate_csv(columns, row_gen)
                mimetype = "text/csv; charset=utf-8"
                ext = "csv"
            else:
                def generate():
                    yield from export.generate_excel(columns, row_gen)
                mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ext = "xlsx"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{table_name}_{timestamp}.{ext}"

            return Response(
                generate(),
                mimetype=mimetype,
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                    "X-Estimated-Size-MB": str(plan.get("est_size_mb", 0)),
                    "X-Row-Count": str(plan.get("row_count", 0)),
                },
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner))
        except Exception as e:
            flash(f"下载失败: {e}", "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner))


    def _download_chunk(owner, table_name, chunk_index, plan, date_kw=None, fmt="xlsx"):
        """分片下载：只下载第 chunk_index 片（Excel 或 CSV）"""
        if date_kw is None:
            date_kw = {}
        chunk_rows = plan.get("chunk_rows", Config.DOWNLOAD_SPLIT_CHUNK_ROWS)
        offset = chunk_index * chunk_rows
        total_chunks = plan.get("chunks", 1)

        try:
            row_gen = db_oracle.stream_table_data(
                owner, table_name,
                offset=offset, max_rows=chunk_rows, **date_kw,
            )
            columns = next(row_gen)

            if fmt == "csv":
                def generate():
                    yield from export.generate_csv(columns, row_gen)
                mimetype = "text/csv; charset=utf-8"
                ext = "csv"
            else:
                def generate():
                    yield from export.generate_excel(columns, row_gen)
                mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ext = "xlsx"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{table_name}_part{chunk_index + 1}of{total_chunks}_{timestamp}.{ext}"

            return Response(
                generate(),
                mimetype=mimetype,
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                    "X-Chunk-Index": str(chunk_index),
                    "X-Chunk-Total": str(total_chunks),
                },
            )
        except Exception as e:
            flash(f"分片下载失败: {e}", "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner))


    @app.route("/download/<table_name>/all")
    @login_required
    def download_all_chunks(table_name):
        """将所有分片打包为一个 ZIP 文件下载（支持 ?format=csv）。"""
        import tempfile
        import zipfile

        owner = request.args.get("owner", Config.ORACLE_USER.upper())
        if not re.match(r"^[A-Za-z0-9_$#]+$", table_name):
            abort(400)

        date_col, date_start, date_end = _parse_date_filter(request)
        date_kw = _make_date_params(date_col, date_start, date_end)
        fmt = _parse_format(request)

        filter_qs = ""
        if date_col:
            filter_qs = f"&date_col={date_col}&date_start={date_start}&date_end={date_end}"

        try:
            plan = db_oracle.get_download_plan(owner, table_name, **date_kw)
        except Exception as e:
            flash(f"无法获取表信息: {e}", "danger")
            return redirect(url_for("table_preview", table_name=table_name, owner=owner) + filter_qs)

        chunks = plan.get("chunks", 0)
        chunk_rows = plan.get("chunk_rows", Config.DOWNLOAD_SPLIT_CHUNK_ROWS)

        # 不需要分片 -> 走普通流式下载
        if chunks <= 1:
            return _stream_download(owner, table_name, plan, date_kw, fmt)

        # --- 打包 ZIP ---
        ext = "csv" if fmt == "csv" else "xlsx"
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for i in range(chunks):
                    offset = i * chunk_rows
                    buf = _build_chunk_file(owner, table_name, offset, chunk_rows, date_kw, fmt)
                    file_name = f"{table_name}_part{i + 1}of{chunks}.{ext}"
                    zf.writestr(file_name, buf.read())

            # 关闭文件句柄（Windows 下写入完成后方可被 generate 读取）
            tmp.close()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{table_name}_all_{chunks}parts_{timestamp}.zip"

            def generate():
                with open(tmp.name, "rb") as f:
                    while True:
                        piece = f.read(65536)
                        if not piece:
                            break
                        yield piece
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

            return Response(
                generate(),
                mimetype="application/zip",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{quote(zip_filename)}"
                    ),
                    "X-Chunk-Total": str(chunks),
                },
            )
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise


    # ===== API: 下载方案信息 =====

    @app.route("/api/table/<table_name>/plan")
    @login_required
    def api_download_plan(table_name):
        """JSON API: 返回表的下载方案（支持日期筛选）"""
        owner = request.args.get("owner", Config.ORACLE_USER.upper())
        if not re.match(r"^[A-Za-z0-9_$#]+$", table_name):
            return jsonify({"error": "无效的表名"}), 400
        try:
            date_col, date_start, date_end = _parse_date_filter(request)
            date_kw = _make_date_params(date_col, date_start, date_end)
            plan = db_oracle.get_download_plan(owner, table_name, **date_kw)
            return jsonify(plan)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # ===== 系统诊断页面 =====

    @app.route("/diagnostics")
    @login_required
    @admin_required
    def diagnostics():
        """
        系统诊断页面：探明硬件能力 + Oracle 连接测试。

        探明的内容：
        - 服务器可用内存 → 自动计算安全下载上限
        - CPU 核心数 → 决定并发能力
        - Oracle 连接测试 → 验证数据库可达性
        - 表过滤配置 → 确认哪些表被暴露
        """
        hw = get_hardware_info()

        # Oracle 连接测试
        oracle_status = {"ok": False, "error": "", "latency_ms": 0}
        try:
            import time
            t0 = time.perf_counter()
            db_oracle.list_tables(search="___NONEXISTENT___")
            t1 = time.perf_counter()
            oracle_status["ok"] = True
            oracle_status["latency_ms"] = round((t1 - t0) * 1000, 1)
        except Exception as e:
            oracle_status["error"] = str(e)

        # 统计信息
        try:
            all_tables = db_oracle.list_tables()
            stats = {
                "total_tables": len(all_tables),
                "schemas": len(set(t["owner"] for t in all_tables)),
                "large_tables": sum(1 for t in all_tables if (t.get("num_rows") or 0) > Config.DOWNLOAD_WARN_ROWS),
                "huge_tables": sum(1 for t in all_tables if (t.get("num_rows") or 0) > Config.DOWNLOAD_CONFIRM_ROWS),
                "blocked_tables": sum(1 for t in all_tables if (t.get("num_rows") or 0) > Config.MAX_DOWNLOAD_ROWS),
            }
        except Exception:
            stats = {"total_tables": -1, "schemas": -1, "large_tables": -1, "huge_tables": -1, "blocked_tables": -1}

        return render_template(
            "diagnostics.html",
            hardware=hw,
            oracle_status=oracle_status,
            stats=stats,
        )

    # ===== 用户管理（管理员） =====

    @app.route("/admin")
    @login_required
    @admin_required
    def admin():
        """用户管理页面"""
        users = get_all_users()
        return render_template("admin.html", users=users)

    @app.route("/admin/create", methods=["POST"])
    @login_required
    @admin_required
    def admin_create_user():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        display_name = request.form.get("display_name", "").strip()
        is_admin = request.form.get("is_admin") == "1"

        if not username or not password:
            flash("用户名和密码不能为空。", "warning")
            return redirect(url_for("admin"))

        if len(password) < 6:
            flash("密码长度不能少于6位。", "warning")
            return redirect(url_for("admin"))

        success, msg = create_user(username, password, display_name, is_admin)
        category = "success" if success else "danger"
        flash(msg, category)
        return redirect(url_for("admin"))

    @app.route("/admin/delete/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_user(user_id):
        if user_id == current_user.id:
            flash("不能删除自己的账号。", "danger")
            return redirect(url_for("admin"))

        if delete_user(user_id):
            flash("用户已删除。", "success")
        else:
            flash("删除失败：用户不存在。", "danger")
        return redirect(url_for("admin"))

    @app.route("/admin/reset-password/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_reset_password(user_id):
        import secrets
        new_password = secrets.token_urlsafe(8)
        if reset_user_password(user_id, new_password):
            flash(
                f"密码已重置，新密码为: <strong>{new_password}</strong>（请告知用户并提醒登录后修改）",
                "success",
            )
        else:
            flash("重置失败：用户不存在。", "danger")
        return redirect(url_for("admin"))

    @app.route("/admin/toggle-active/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_toggle_active(user_id):
        if user_id == current_user.id:
            flash("不能禁用自己的账号。", "danger")
            return redirect(url_for("admin"))

        success, msg = toggle_user_active(user_id)
        category = "success" if success else "danger"
        flash(msg, category)
        return redirect(url_for("admin"))

    return app


def _get_filter_info():
    """返回当前表过滤配置的人类可读描述"""
    mode = Config.TABLE_FILTER_MODE
    patterns = Config.TABLE_FILTER_PATTERNS
    if mode == "all" or not patterns:
        return "（显示所有数据表）"
    elif mode == "whitelist":
        return f"（仅显示匹配的表: {', '.join(patterns)}）"
    elif mode == "blacklist":
        return f"（已排除: {', '.join(patterns)}）"
    return ""


# ===== 启动入口 =====

if __name__ == "__main__":
    app = create_app()
    hw = get_hardware_info()
    print("=" * 55)
    print("  电车票务数据平台")
    print("  Tram Data Export Platform")
    print("=" * 55)
    print(f"  访问地址:    http://localhost:5000")
    print(f"  默认管理员:  {Config.DEFAULT_ADMIN_USERNAME}")
    print(f"  默认密码:    {Config.DEFAULT_ADMIN_PASSWORD}")
    print("-" * 55)
    if hw["total_memory_mb"] > 0:
        print(f"  服务器内存:  {hw['total_memory_mb']} MB (可用 {hw['available_memory_mb']} MB)")
        print(f"  安全下载上限: ~{hw['safe_download_size_mb']} MB / {hw['safe_download_rows']:,} 行")
    else:
        print("  未检测到 psutil，使用保守默认值")
    print(f"  表过滤模式:  {Config.TABLE_FILTER_MODE}")
    if Config.TABLE_FILTER_PATTERNS:
        print(f"  过滤规则:    {Config.TABLE_FILTER_PATTERNS}")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)