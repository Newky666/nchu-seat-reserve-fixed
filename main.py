#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py - 南昌航空大学图书馆座位自动预约(蓝航 App 通道)

纯标准库实现, 零第三方依赖。

用法:
    py main.py --import 抓包文件.txt     # 从抓包文件导入 auth/uid(只需一次)
    py main.py --setup                  # 交互式配置: 选楼层/阅览室/座位/时间段
    py main.py --search                  # 查看当前可预约的座位
    py main.py --now                     # 即刻预约: 从当前整点约到闭馆(默认22:00)
    py main.py --book                    # 预约次日(多任务依次执行)
    py main.py --mylist                  # 查看我的预约列表
    py main.py --cancel 预约ID            # 取消某个预约
    py main.py                           # 定时模式: 每晚到点自动抢座

认证说明:
    蓝航 App 预约接口只需 Cookie 里的 auth + uid(+ is_remember)。
    用 --import 从抓包文件自动提取这些字段写入 config.json,
    之后直接运行即可。auth/uid 失效后(预约报登录错误)重新抓包再 --import 一次。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://lib-zw.lib.nchu.edu.cn"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reserve.log")
MEMORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookmemory.json")

UA = ("Mozilla/5.0 (Linux; Android 15; 23046RP50C Build/AQ3A.250226.002; wv) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/131.0.6778.260 "
      "Safari/537.36 NchuApp/1.0.14 MicroMessenger/8.0.47.2560")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except OSError:
        pass


def _migrate_legacy(cfg: dict) -> dict:
    """把旧版单账号配置(顶层 account/reserve/tasks)迁移成多账号结构。"""
    if "accounts" in cfg:
        return cfg
    old_account = cfg.get("account") or {}
    sid = old_account.get("student_id") or "default"
    accounts = {
        sid: {
            "student_id": sid,
            "auth": old_account.get("auth", ""),
            "uid": old_account.get("uid", ""),
            "is_remember": old_account.get("is_remember", ""),
            "login_time": old_account.get("login_time", ""),
            "seat_bookers": old_account.get("seat_bookers", []),
            "reserve": cfg.get("reserve", {}),
            "tasks": cfg.get("tasks", []),
        }
    }
    return {
        "accounts": accounts,
        "schedule": cfg.get("schedule", {}),
        "current": sid,
    }


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
        cfg = json.load(fp)
    return _migrate_legacy(cfg)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 座位记忆(bookmemory.json): 按学号记录历史预约座位, 每用户最多 5 条
# ---------------------------------------------------------------------------
def load_memory() -> dict:
    if os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (ValueError, OSError):
            return {}
    return {}


def save_memory(mem: dict) -> None:
    with open(MEMORY_PATH, "w", encoding="utf-8") as fp:
        json.dump(mem, fp, ensure_ascii=False, indent=2)


def add_memory(student_id: str, entry: dict, max_items: int = 5) -> None:
    """记录某用户的预约座位习惯。只存座位号+房间+楼层, 不存时间段。
    每个用户最多 max_items 条, 超出时最新替换最旧。"""
    if not student_id or not entry.get("seat_num"):
        return
    mem = load_memory()
    lst = mem.get(student_id, [])
    # 同座位+同房间去重: 移到最新
    key = (entry.get("seat_num"), entry.get("room"))
    lst = [e for e in lst if (e.get("seat_num"), e.get("room")) != key]
    lst.insert(0, entry)
    mem[student_id] = lst[:max_items]
    save_memory(mem)


def get_memory(student_id: str) -> list:
    """返回某用户的历史座位记忆(最新在前)。"""
    return load_memory().get(student_id, [])


def clear_memory(student_id: str) -> None:
    """删除某用户的全部习惯座位记忆。"""
    mem = load_memory()
    if student_id in mem:
        del mem[student_id]
        save_memory(mem)


def account_list(cfg: dict) -> list:
    """返回所有账号的学号列表(按导入顺序)。"""
    return list((cfg.get("accounts") or {}).keys())


def get_account(cfg: dict, student_id: str = None) -> dict:
    """获取指定学号的账号(默认当前账号), 不存在返回空 dict。"""
    accounts = cfg.get("accounts") or {}
    sid = student_id or cfg.get("current")
    return accounts.get(sid, {}) if sid else {}


def active_account(cfg: dict) -> dict:
    """当前选中账号。"""
    return get_account(cfg, cfg.get("current"))


def current_student_id(cfg: dict) -> str:
    return cfg.get("current", "")


def set_current(cfg: dict, student_id: str) -> None:
    """切换当前账号(必须已存在)。"""
    if student_id in (cfg.get("accounts") or {}):
        cfg["current"] = student_id


def build_headers(cfg: dict) -> dict:
    a = active_account(cfg)
    cookie = "web_language=zh; login_time=%s; uid=%s; auth=%s; is_remember=%s" % (
        a.get("login_time", ""), a.get("uid", ""),
        a.get("auth", ""), a.get("is_remember", ""))
    return {
        "Cookie": cookie,
        "User-Agent": UA,
        "X-Requested-With": "cn.edu.nchu.nahang",
        "Referer": BASE + "/",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    }


def http(url: str, data: str = None, headers: dict = None) -> dict:
    req = urllib.request.Request(url, data=data.encode() if data else None,
                                 headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"CODE": "HTTP%d" % exc.code, "MESSAGE": str(exc)}
    except Exception as exc:
        return {"CODE": "NetworkError", "MESSAGE": str(exc)}


# ---------------------------------------------------------------------------
# 认证导入
# ---------------------------------------------------------------------------
def _parse_cookie_fields(cookie: str) -> dict:
    fields = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip()] = v.strip()
    return fields


def _parse_bookers(body: str) -> list:
    bookers = []
    for part in urllib.parse.unquote(body).split("&"):
        if part.startswith("seatBookers["):
            bookers.append(part.split("=", 1)[1])
    return bookers


def _parse_seats(body: str) -> list:
    """从抓包 body 提取 seats[] 参数(图书馆座位的 id)。"""
    seats = []
    for part in urllib.parse.unquote(body).split("&"):
        if part.startswith("seats["):
            seats.append(part.split("=", 1)[1])
    return seats


def _save_account(student_id: str, fields: dict, bookers: list,
                  seat_ids: list = None) -> int:
    """把认证信息 + 座位 id 存入指定学号对应的账号(多账号各自独立)。"""
    cfg = load_config()
    accounts = cfg.setdefault("accounts", {})
    sid = student_id or "default"
    a = accounts.setdefault(sid, {})
    a["student_id"] = sid
    if fields.get("auth"):
        a["auth"] = fields["auth"]
    if fields.get("uid"):
        a["uid"] = fields["uid"]
    if fields.get("is_remember"):
        a["is_remember"] = fields["is_remember"]
    if fields.get("login_time"):
        a["login_time"] = fields["login_time"]
    if bookers:
        a["seat_bookers"] = bookers
    # 座位 id 记入该账号的 target_seats(便于识别, 也作为选座偏好)
    if seat_ids:
        a.setdefault("reserve", {})["target_seats"] = seat_ids
    cfg["current"] = sid
    save_config(cfg)
    print("[OK] 已导入认证信息:")
    print("  学号       : %s" % sid)
    print("  auth       : %s..." % a.get("auth", "")[:30])
    print("  uid        : %s..." % a.get("uid", "")[:30])
    print("  seatBookers: %s" % ", ".join(a.get("seat_bookers", [])))
    print("  座位 id    : %s" % ", ".join(seat_ids or []))
    return 0


def cmd_import(path: str) -> int:
    """从抓包文件导入认证信息, 自动识别 cURL 和 HAR 两种格式。"""
    raw = open(path, "rb").read()
    txt = raw.decode("utf-8", "replace")

    # 学号(从 nchuLogin 的 uid=xxx@stu 提取, cURL 和 HAR 都能匹配)
    student_id = ""
    m = re.search(r"nchuLogin\?uid=(\d+)@stu", txt)
    if m:
        student_id = m.group(1)

    stripped = txt.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        # HAR / JSON 格式
        try:
            har = json.loads(txt)
        except ValueError:
            print("[!] 无法解析该文件(既不是 cURL 也不是有效 JSON)")
            return 1
        entries = (har.get("log") or {}).get("entries", []) or []
        target = None
        for e in entries:
            req = e.get("request") or {}
            if "bookSeats" in req.get("url", ""):
                target = req
                break
        if not target:
            print("[!] 没找到 bookSeats 请求")
            return 1
        cookie = ""
        for h in target.get("headers", []) or []:
            if (h.get("name") or "").lower() == "cookie":
                cookie = h.get("value") or ""
                break
        fields = _parse_cookie_fields(cookie)
        body = (target.get("postData") or {}).get("text", "")
        bookers = _parse_bookers(body)
        seat_ids = _parse_seats(body)
        return _save_account(student_id, fields, bookers, seat_ids)

    # cURL 格式
    parts = txt.split("curl")
    target = None
    for p in parts:
        if "bookSeats" in p and "Cookie:" in p:
            target = p
            break
    if not target:
        print("[!] 没找到 bookSeats 请求, 请确认抓包文件里包含预约操作")
        return 1

    cookie = re.search(r"-H 'Cookie:\s*([^']*)'", target).group(1)
    fields = _parse_cookie_fields(cookie)
    body = re.search(r"(?:-d|--data-raw)\s+'([^']*)'", target)
    raw_body = body.group(1) if body else ""
    bookers = _parse_bookers(raw_body)
    seat_ids = _parse_seats(raw_body)
    return _save_account(student_id, fields, bookers, seat_ids)


# ---------------------------------------------------------------------------
# 座位查询与选座
# ---------------------------------------------------------------------------
def extract_seats(data) -> list:
    """从 POIs 数组提取所有座位, 按座位 id 去重, 并带上所属阅览室名。"""
    seats = {}

    def walk(d, room: str):
        if isinstance(d, dict):
            cur = room
            if d.get("roomName"):
                cur = d["roomName"]
            info = d.get("info")
            if isinstance(info, dict) and info.get("title"):
                cur = info["title"]
            pois = d.get("POIs")
            if isinstance(pois, list):
                for p in pois:
                    if isinstance(p, dict) and p.get("id") is not None:
                        sid = str(p["id"])
                        if sid not in seats:
                            item = dict(p)
                            item["_room"] = cur
                            seats[sid] = item
            for v in d.values():
                walk(v, cur)
        elif isinstance(d, list):
            for x in d:
                walk(x, room)

    walk(data, "")
    return list(seats.values())


def search_seats(cfg: dict, begin_ts: int, duration: int,
                 content_id: str = None) -> list:
    sc = active_account(cfg).get("reserve", {}).get("space_category", {})
    cid = content_id or sc.get("content_id", "")
    body = ("beginTime=%d&duration=%d&num=1&space_category%%5Bcategory_id%%5D=%s"
            "&space_category%%5Bcontent_id%%5D=%s" % (
                begin_ts, duration, sc.get("category_id", ""), cid))
    resp = http(BASE + "/Seat/Index/searchSeats?LAB_JSON=1", data=body,
                headers=build_headers(cfg))
    return extract_seats(resp)


def get_floors(cfg: dict) -> list:
    """获取楼层/区域列表, 返回 [(名称, content_id), ...]。"""
    resp = http(BASE + "/Space/Category/list?LAB_JSON=1",
                headers=build_headers(cfg))
    floors = []

    def walk(d):
        if isinstance(d, dict):
            if d.get("ui_type") == "ht.space.SpaceReservationListItem":
                url = (d.get("link") or {}).get("url", "")
                m = re.search(r"content_id%5D=(\d+)", url)
                floors.append((d.get("name", ""), m.group(1) if m else ""))
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for x in d:
                walk(x)

    walk(resp)
    # 去重保序, 并过滤暂不支持的区域(上海路校区)
    seen, result = set(), []
    for f in floors:
        if f[1] not in seen and "上海路" not in f[0]:
            seen.add(f[1])
            result.append(f)
    return result


def get_rooms(cfg: dict, content_id: str, begin_ts: int, duration: int) -> list:
    """获取某楼层下的阅览室名称列表。"""
    seats = search_seats(cfg, begin_ts, duration, content_id=content_id)
    rooms = []
    seen = set()
    for s in seats:
        r = s.get("_room") or "未知区域"
        if r not in seen:
            seen.add(r)
            rooms.append(r)
    return rooms


def room_type(name: str) -> str:
    """判断房间类型: 自习区=室外过道, 阅览室/自习室=室内。"""
    if "自习区" in name:
        return "室外·过道"
    if "自习室" in name or "阅览室" in name:
        return "室内·房间"
    return "室内"


# 学校最新配置: 以下区域"每个座位都有插座"(接口的 have_socket 是旧数据, 不可靠)
ALL_SOCKET_ROOMS = ("自习区", "社会科学阅览室一", "学生社区")


def seat_has_socket(seat: dict, room: str = "") -> bool:
    """判断座位是否有插座(结合学校最新插座分布规则)。

    规则: 自习区(过道)、二楼社科阅览室一、学生社区 = 每个座位都有插座;
          其余阅览室按接口 have_socket 字段(可能是部分区域才有)。
    """
    room = room or seat.get("_room", "") or ""
    for kw in ALL_SOCKET_ROOMS:
        if kw in room:
            return True
    return str(seat.get("have_socket")) == "1"


def pick_best_seat(cfg: dict, seats: list) -> dict:
    """按偏好选一个最优座位。"""
    if not seats:
        return {}
    reserve = active_account(cfg).get("reserve", {})
    prefs = reserve.get("preferences", {})
    targets = reserve.get("target_seats", [])

    # 优先选用户指定的座位
    if targets:
        for s in seats:
            if str(s.get("id")) in [str(t) for t in targets]:
                return s

    def score(s):
        sc = 0
        if prefs.get("near_socket") and seat_has_socket(s):
            sc += 10
        return sc

    return max(seats, key=score)


# ---------------------------------------------------------------------------
# 预约 / 取消 / 查询
# ---------------------------------------------------------------------------
def do_book(cfg: dict, begin_ts: int, duration: int, seat_id) -> dict:
    a = active_account(cfg)
    bookers = a.get("seat_bookers") or [a.get("student_id", "")]
    body = "beginTime=%d&duration=%d&seats%%5B0%%5D=%s&seatBookers%%5B0%%5D=%s" % (
        begin_ts, duration, seat_id, bookers[0])
    return http(BASE + "/Seat/Index/bookSeats?LAB_JSON=1", data=body,
                headers=build_headers(cfg))


def is_login_expired(resp: dict) -> bool:
    """判断响应是否表示登录已失效。"""
    if not isinstance(resp, dict):
        return False
    data = resp.get("DATA", {})
    if isinstance(data, dict) and data.get("is_login") is False:
        return True
    text = "%s %s" % (resp.get("CODE", ""), resp.get("MESSAGE", ""))
    for kw in ("login", "登录", "失效", "重新登录", "未登录", "expired", "invalid", "auth"):
        if kw.lower() in text.lower():
            return True
    return False


def warn_if_expired(resp: dict) -> bool:
    """如果登录失效, 打印醒目提示, 返回是否失效。"""
    if not is_login_expired(resp):
        return False
    log("=" * 60)
    log("[!] 登录已失效(auth/uid 过期)")
    log("[!] 请重新抓包, 然后运行: py main.py --import 抓包文件.txt")
    log("=" * 60)
    return True


# 预约失败常见原因 → 中文说明
FAIL_REASONS = (
    ("seattimerangeout", "预约时段无效或未开放(可能还没到放号时间 22:00)"),
    ("seatbebooked", "该座位已被他人预约"),
    ("seatoccupied", "该座位已被占用"),
    ("alreadybooked", "你已有预约, 不能重复预约"),
    ("hasbooking", "你已有预约, 不能重复预约"),
    ("booked", "已有预约"),
    ("noavailableseat", "没有可用座位"),
    ("noseat", "没有可用座位"),
    ("timeout", "请求超时"),
    ("networkerror", "网络错误"),
    ("nologin", "未登录"),
    ("loginexpired", "登录已过期"),
    ("expired", "登录已过期"),
    ("notopen", "预约未开放"),
)


def explain_failure(resp: dict) -> str:
    """从预约响应中提取具体失败原因, 转成中文说明。"""
    if not isinstance(resp, dict):
        return "未知错误"
    data = resp.get("DATA", {})
    # 认证失效优先
    if isinstance(data, dict) and data.get("is_login") is False:
        return "抓包失效(auth/uid 已过期), 请重新抓包导入"
    # 提取原始错误信息(CODE + MESSAGE + DATA.msg)
    parts = [str(resp.get("CODE", "")), str(resp.get("MESSAGE", ""))]
    if isinstance(data, dict):
        parts.append(str(data.get("msg", "")))
        parts.append(str(data.get("result", "")))
    raw = " ".join(parts).lower()
    for key, cn in FAIL_REASONS:
        if key in raw:
            return cn
    # 兜底: 返回 DATA.msg 或 MESSAGE
    if isinstance(data, dict) and data.get("msg"):
        return "预约失败: %s" % data.get("msg")
    if resp.get("MESSAGE"):
        return "预约失败: %s" % resp.get("MESSAGE")
    return "预约失败(未知原因)"


def my_bookings(cfg: dict) -> list:
    resp = http(BASE + "/Seat/Index/myBookingList?LAB_JSON=1",
                headers=build_headers(cfg))
    items = []
    if isinstance(resp, dict):
        content = resp.get("content", {})
        for it in content.get("defaultItems", []) or []:
            items.append({
                "id": it.get("id"),
                "room": it.get("roomName"),
                "seat": it.get("seatNum"),
                "time": it.get("time"),
                "status": it.get("status"),
            })
    return items


def cancel_booking(cfg: dict, booking_id, student_id: str = None) -> dict:
    """取消预约, 可指定学号(默认当前账号)。"""
    orig = current_student_id(cfg)
    if student_id and student_id != orig:
        cfg["current"] = student_id
    result = http(BASE + "/Seat/Index/cancelBooking?bookingId=%s&LAB_JSON=1" % booking_id,
                  data="", headers=build_headers(cfg))
    if student_id and student_id != orig:
        cfg["current"] = orig
    return result


# ---------------------------------------------------------------------------
# 命令: 查询座位 / 立即预约 / 我的列表 / 取消
# ---------------------------------------------------------------------------
def ts_of(days_ahead: int, hour: int) -> int:
    target = datetime.now().date() + timedelta(days=days_ahead)
    return int(datetime.combine(target, datetime.min.time()).timestamp()) + hour * 3600


def _to_min(t: str) -> int:
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(mins: int) -> str:
    return "%02d:%02d" % (mins // 60, mins % 60)


def split_time_range(start: str, end: str, max_hours: int = 6, min_hours: int = 1) -> list:
    """把 'HH:MM' 起止时间拆成多个段, 每段在 [min_hours, max_hours] 之间。"""
    s, e = _to_min(start), _to_min(end)
    if e <= s:
        raise ValueError("结束时间必须晚于开始时间")
    if e - s < min_hours * 60:
        raise ValueError("预约时长最少 %d 小时" % min_hours)

    # 用整数分钟计算各段边界
    boundaries = [s]
    cur = s
    while cur < e:
        nxt = min(cur + max_hours * 60, e)
        # 最后一段不足 min_hours: 从上一段借时间, 让最后一段凑够 min_hours
        if nxt == e and (nxt - cur) < min_hours * 60 and len(boundaries) >= 2:
            need = min_hours * 60 - (nxt - cur)
            boundaries[-1] -= need
            cur = boundaries[-1]
            nxt = e
        boundaries.append(nxt)
        cur = nxt

    segs = []
    for i in range(len(boundaries) - 1):
        segs.append((_to_hhmm(boundaries[i]), _to_hhmm(boundaries[i + 1])))
    return segs


def time_range_to_ts(days_ahead: int, start: str, end: str) -> tuple:
    """把 'HH:MM' 起止时间转成 (begin_ts, duration_sec)。"""
    base = datetime.now().date() + timedelta(days=days_ahead)
    base_ts = int(datetime.combine(base, datetime.min.time()).timestamp())
    return base_ts + _to_min(start) * 60, (_to_min(end) - _to_min(start)) * 60


def cmd_search(cfg: dict) -> int:
    reserve = active_account(cfg).get("reserve", {})
    begin = ts_of(1, int(reserve.get("start_hour", 8)))
    dur = int(reserve.get("duration_hours", 6)) * 3600
    seats = search_seats(cfg, begin, dur)
    print("查询 %s 起 %d 小时, 共 %d 个可选座位" % (
        time.strftime("%m-%d %H:%M", time.localtime(begin)),
        dur // 3600, len(seats)))
    print("=" * 60)

    # 按阅览室分组
    rooms: dict = {}
    for s in seats:
        rooms.setdefault(s.get("_room") or "未知区域", []).append(s)

    for room, slist in sorted(rooms.items()):
        def num(v):
            try:
                return int(v)
            except (ValueError, TypeError):
                return 9999
        slist.sort(key=lambda s: num(s.get("title")))
        socket_seats = [s for s in slist if seat_has_socket(s, room)]
        print("\n【%s】[%s] 空座 %d 个 | 有插座 %d 个" % (
            room, room_type(room), len(slist), len(socket_seats)))
        if socket_seats:
            print("   有插座座号: %s" % " ".join(str(s.get("title")) for s in socket_seats[:40]))
        others = [s for s in slist if not seat_has_socket(s, room)]
        if others:
            print("   普通座号  : %s" % " ".join(str(s.get("title")) for s in others[:40]))
            if len(others) > 40:
                print("              (共 %d 个, 只显示前 40 个)" % len(others))

    print("\n" + "=" * 60)
    best = pick_best_seat(cfg, seats)
    if best:
        print("按当前偏好选中: %s 座 (id=%s, 插座=%s)" % (
            best.get("title"), best.get("id"), "有" if seat_has_socket(best) else "无"))
    return 0


def book_one(cfg: dict, content_id: str, seat_id, seat_num: str,
             start: str, end: str, days_ahead: int = 1) -> dict:
    """预约一个时间段, 返回结果。"""
    begin, dur = time_range_to_ts(days_ahead, start, end)
    log("预约: %s座 %s-%s (%.1f 小时)" % (seat_num, start, end, dur / 3600))
    result = do_book(cfg, begin, dur, seat_id)
    warn_if_expired(result)
    return result


def cmd_book(cfg: dict, days_ahead: int = 1) -> int:
    tasks = active_account(cfg).get("tasks") or []
    if tasks:
        # 多任务模式: 依次预约每个时间段
        ok = 0
        for i, t in enumerate(tasks, 1):
            log("[任务 %d/%d] %s室 %s座 %s-%s" % (
                i, len(tasks), t.get("room", ""), t.get("seat_num", ""),
                t.get("start", ""), t.get("end", "")))
            result = book_one(cfg, t.get("content_id"), t.get("seat_id"),
                              t.get("seat_num", ""), t.get("start", ""), t.get("end", ""),
                              days_ahead=days_ahead)
            msg = json.dumps(result, ensure_ascii=False)
            log("  结果: %s" % msg[:220])
            data = result.get("DATA", {}) if isinstance(result, dict) else {}
            if data.get("result") == "success":
                ok += 1
            else:
                log("  失败原因: %s" % explain_failure(result))
        log("完成: %d/%d 个任务预约成功" % (ok, len(tasks)))
        return 0

    # 无 tasks 时走旧单任务配置
    reserve = active_account(cfg).get("reserve", {})
    begin = ts_of(days_ahead, int(reserve.get("start_hour", 8)))
    dur = int(reserve.get("duration_hours", 6)) * 3600
    seats = search_seats(cfg, begin, dur)
    seat = pick_best_seat(cfg, seats)
    if not seat:
        log("[失败] 没有可用座位")
        return 1
    log("选中座位 id=%s 座号=%s" % (seat.get("id"), seat.get("title")))
    result = do_book(cfg, begin, dur, seat.get("id"))
    msg = json.dumps(result, ensure_ascii=False)
    log("预约结果: %s" % msg[:300])
    return 0


def cmd_now(cfg: dict) -> int:
    """即刻预约: 从当前整点(向下取整)预约到闭馆, 超6小时自动拆分。

    例: 现在 19:30 → 按 19:00 时段算, 预约 19:00-22:00(闭馆)。
    """
    now = datetime.now()
    close_str = cfg.get("schedule", {}).get("close_time", "22:00")
    open_str = cfg.get("schedule", {}).get("open_time", "08:00")
    chh, cmm = (int(x) for x in close_str.split(":"))
    ohh, omm = (int(x) for x in open_str.split(":"))
    close = now.replace(hour=chh, minute=cmm, second=0, microsecond=0)
    open_dt = now.replace(hour=ohh, minute=omm, second=0, microsecond=0)
    start = now.replace(minute=0, second=0, microsecond=0)  # 向下取整到整点
    if start < open_dt:  # 当前整点早于开馆, 从开馆开始
        start = open_dt
    if close <= start:
        log("[失败] 现在已过闭馆时间(%s)" % close_str)
        return 1

    # 拆分时间段(每段 ≤ 6 小时)
    segs = split_time_range(start.strftime("%H:%M"), close.strftime("%H:%M"))

    # 确定座位
    tasks = active_account(cfg).get("tasks") or []
    if tasks:
        t = tasks[0]
        seat_id = t.get("seat_id")
        seat_num = t.get("seat_num", "")
    else:
        seats = search_seats(cfg, int(start.timestamp()), int((close - start).total_seconds()))
        seat = pick_best_seat(cfg, seats)
        if not seat:
            log("[失败] 现在时段没有可用座位")
            return 1
        seat_id = seat.get("id")
        seat_num = seat.get("title", "")

    # 依次预约每一段
    for s, e in segs:
        begin_ts, dur = time_range_to_ts(0, s, e)
        log("即刻预约: %s座 %s-%s" % (seat_num, s, e))
        result = do_book(cfg, begin_ts, dur, seat_id)
        msg = json.dumps(result, ensure_ascii=False)
        log("  结果: %s" % msg[:250])
        warn_if_expired(result)
    return 0


def cmd_setup(cfg: dict) -> int:
    """交互式配置向导: 选楼层 → 选阅览室 → 选座位 → 选时间段(多段)。"""
    print("=" * 60)
    print(" 图书馆座位预约 - 配置向导")
    print("=" * 60)

    # 1. 选楼层
    floors = get_floors(cfg)
    if not floors:
        print("[!] 获取楼层列表失败, 请检查网络或认证")
        return 1
    print("\n请选择楼层/区域:")
    for i, (name, _cid) in enumerate(floors, 1):
        print("  [%d] %s" % (i, name))
    choice = input("输入编号: ").strip()
    try:
        floor_name, content_id = floors[int(choice) - 1]
    except (ValueError, IndexError):
        print("[!] 编号无效")
        return 1
    print("已选楼层: %s" % floor_name)

    # 2. 选阅览室
    begin = ts_of(1, 8)
    rooms = get_rooms(cfg, content_id, begin, 6 * 3600)
    if not rooms:
        print("[!] 该楼层暂无阅览室或查询失败")
        return 1
    print("\n该楼层下的阅览室(室内房间 / 室外过道自习区):")
    for i, r in enumerate(rooms, 1):
        print("  [%d] %-34s [%s]" % (i, r, room_type(r)))
    choice = input("输入编号: ").strip()
    try:
        room = rooms[int(choice) - 1]
    except (ValueError, IndexError):
        print("[!] 编号无效")
        return 1
    print("已选阅览室: %s" % room)

    # 3. 选座位
    seats = [s for s in search_seats(cfg, begin, 6 * 3600, content_id=content_id)
             if s.get("_room") == room]

    def num(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 9999

    seats.sort(key=lambda s: num(s.get("title")))
    if not seats:
        print("[!] 该阅览室暂无座位")
        return 1
    socket_seats = [s for s in seats if seat_has_socket(s, room)]
    print("\n该阅览室共 %d 个座位" % len(seats))
    if socket_seats:
        print("有插座座号: %s" % " ".join(str(s.get("title")) for s in socket_seats[:40]))
    else:
        print("座号范围: %s ~ %s" % (seats[0].get("title"), seats[-1].get("title")))
    seat_num = input("请输入座位号(如 211): ").strip()
    seat = next((s for s in seats if str(s.get("title")) == seat_num), None)
    if not seat:
        print("[!] 找不到座位号 %s, 请重新运行 --setup" % seat_num)
        return 1
    print("已选座位: %s 座 (id=%s, 插座=%s)" % (
        seat.get("title"), seat.get("id"), "有" if seat_has_socket(seat, room) else "无"))

    # 4. 选时间段(多段)
    print("\n请输入时间段, 格式: 开始-结束 (24小时制)")
    print("可多段用逗号分隔, 如: 12:00-18:00, 19:00-21:00")
    print("单段最长 6 小时, 超长会自动拆分")
    time_input = input("时间段: ").strip()
    tasks = []
    for part in time_input.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            print("[!] 格式错误: %s (应为 开始-结束)" % part)
            return 1
        start, end = part.split("-", 1)
        try:
            segs = split_time_range(start, end)
        except ValueError as exc:
            print("[!] %s" % exc)
            return 1
        for s, e in segs:
            tasks.append({
                "content_id": content_id,
                "room": room,
                "seat_id": seat.get("id"),
                "seat_num": seat.get("title"),
                "start": s,
                "end": e,
            })

    # 5. 保存
    active_account(cfg)["tasks"] = tasks
    save_config(cfg)
    print("\n[OK] 已保存 %d 个预约任务:" % len(tasks))
    for t in tasks:
        print("  %s %s座  %s-%s" % (t["room"], t["seat_num"], t["start"], t["end"]))
    print("\n之后: `py main.py` 到点自动预约 / `py main.py --book` 立即预约")
    return 0


def cmd_mylist(cfg: dict) -> int:
    for it in my_bookings(cfg):
        print("预约 %s  %s室 %s座  status=%s" % (
            it["id"], it["room"], it["seat"], it["status"]))
    return 0


def cmd_cancel(cfg: dict, booking_id) -> int:
    result = cancel_booking(cfg, booking_id)
    print("取消结果: %s" % json.dumps(result, ensure_ascii=False)[:200])
    return 0


# ---------------------------------------------------------------------------
# 定时调度
# ---------------------------------------------------------------------------
def run_scheduler(cfg: dict) -> int:
    release = cfg.get("schedule", {}).get("release_time", "22:00:00")
    hh, mm, ss = (int(x) for x in release.split(":"))
    tasks = active_account(cfg).get("tasks") or []
    retry = int(cfg.get("schedule", {}).get("retry_count", 5))
    interval = float(cfg.get("schedule", {}).get("retry_interval_sec", 0.5))

    log("定时模式已启动, 每天 %s 自动抢明天的座位" % release)
    if tasks:
        log("已配置 %d 个预约任务:" % len(tasks))
        for t in tasks:
            log("  %s %s座 %s-%s" % (t.get("room", ""), t.get("seat_num", ""),
                                     t.get("start", ""), t.get("end", "")))
    else:
        log("未配置任务, 请先运行 `py main.py --setup` 配置")

    last_date = None
    while True:
        now = datetime.now()
        today = now.date()
        target = datetime(today.year, today.month, today.day, hh, mm, ss)
        # 如果今天已过放号时间, 等明天
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        log("下次抢座: %s (%.1f 分钟后)" % (target, wait / 60))
        time.sleep(wait + 1.0)

        # 到点执行
        if last_date == today:
            continue
        last_date = today

        if tasks:
            # 多任务模式: 依次预约每个时间段
            expired = False
            for t in tasks:
                if expired:
                    break
                for attempt in range(retry):
                    result = book_one(cfg, t.get("content_id"), t.get("seat_id"),
                                      t.get("seat_num", ""), t.get("start", ""),
                                      t.get("end", ""))
                    msg = json.dumps(result, ensure_ascii=False)
                    log("[%s座 %s-%s 第%d次] %s" % (
                        t.get("seat_num", ""), t.get("start", ""), t.get("end", ""),
                        attempt + 1, msg[:200]))
                    if is_login_expired(result):
                        expired = True
                        break
                    data = result.get("DATA", {}) if isinstance(result, dict) else {}
                    if data.get("result") == "success":
                        break
                    time.sleep(interval)
        else:
            # 旧单任务模式(无 tasks 时)
            reserve = active_account(cfg).get("reserve", {})
            begin = ts_of(1, int(reserve.get("start_hour", 8)))
            dur = int(reserve.get("duration_hours", 6)) * 3600
            for attempt in range(retry):
                seats = search_seats(cfg, begin, dur)
                seat = pick_best_seat(cfg, seats)
                if not seat:
                    log("[第%d次] 暂无可用座位, 稍后重试" % (attempt + 1))
                    time.sleep(interval * 3)
                    continue
                result = do_book(cfg, begin, dur, seat.get("id"))
                msg = json.dumps(result, ensure_ascii=False)
                log("[第%d次] 预约结果: %s" % (attempt + 1, msg[:250]))
                data = result.get("DATA", {}) if isinstance(result, dict) else {}
                if data.get("result") == "success":
                    break
                time.sleep(interval)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> int:
    args = sys.argv[1:]
    if not args:
        cfg = load_config()
        return run_scheduler(cfg)
    cmd = args[0]
    if cmd == "--import":
        return cmd_import(args[1]) if len(args) > 1 else 2
    cfg = load_config()
    if cmd == "--setup":
        return cmd_setup(cfg)
    if cmd == "--search":
        return cmd_search(cfg)
    if cmd == "--book":
        days_ahead = 0 if "--today" in args else 1
        return cmd_book(cfg, days_ahead)
    if cmd == "--now":
        return cmd_now(cfg)
    if cmd == "--mylist":
        return cmd_mylist(cfg)
    if cmd == "--cancel" and len(args) > 1:
        return cmd_cancel(cfg, args[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
