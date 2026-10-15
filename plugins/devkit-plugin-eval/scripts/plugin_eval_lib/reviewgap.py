"""距上次复盘的天数（票 15）：gate 与 compare 开跑时据此提醒「先复盘」，check_review 据此判会话保留期。

spec「2.5 会话复盘（review）」：跑离线对照或闸门检查时，若距上次复盘超过 7 天，提示先复盘。
「上次复盘」不另存，从 `<仓>/plugin-evals/<插件>/reviews/` 现算：文件名以 YYYY-MM-DD 开头的最大日期。
复盘结果按本机本地日期命名（A 批集成定稿第 7 条），所以「今天」也取本机本地日期，两个日期相减得天数；
不按 UTC 零点解析，否则东八区上午跑的复盘会被算早一天。
"""
import re
from datetime import date, datetime, timezone
from pathlib import Path

REMIND_AFTER_DAYS = 7          # 超过（>）这么多天提醒先复盘
_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')


def last_review_date(dirs):
    """若干 reviews/ 目录里文件名以 YYYY-MM-DD 开头的最大日期（本机本地日期）；没有则 None。"""
    best = None
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in d.iterdir():
            m = _DATE_RE.match(f.name)
            if not m:
                continue
            try:
                day = datetime.strptime(m.group(1), '%Y-%m-%d').date()
            except ValueError:
                continue
            best = day if best is None or day > best else best
    return best


def today_local(now=None, tz=None):
    """本机本地日期。now 缺省取当前时刻；tz 只给单测固定时区用。"""
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(tz) if tz else now.astimezone()).date()


def days_since(last, now=None, tz=None):
    return (today_local(now, tz) - last).days if isinstance(last, date) else None


def reminder(reviews_dir, *, now=None, tz=None, plugin=None):
    """超过 7 天（或从没复盘过）时返回一句提醒，否则 None。reviews_dir 是该插件的 reviews/ 目录。"""
    last = last_review_date([reviews_dir])
    who = '%s ' % plugin if plugin else ''
    if last is None:
        return ('%s还没有会话复盘记录（plugin-evals/<插件>/reviews/ 下没有结果）：建议先跑会话复盘（review）；'
                '复盘只扫登记清单里的插件，未登记需先登记（register）' % who)
    gap = days_since(last, now, tz)
    if gap > REMIND_AFTER_DAYS:
        return ('%s距上次会话复盘（%s）已 %d 天，超过 %d 天：建议先跑会话复盘（review）'
                % (who, last.isoformat(), gap, REMIND_AFTER_DAYS))
    return None
