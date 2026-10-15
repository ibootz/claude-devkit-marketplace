"""运行是否完整：run 出错的归类，以及闸门对不完整记录的排除。

spec「2.2 离线对照」末段：撞上订阅用量限制而失败的 run 判为无效、不计分；整次运行标「不完整」，
可从断点续跑；不完整的结果不计入发版闸门。
判无效本身不看错误种类（scoring.score_case：error 非空即无效），这里的归类只用于报告与续跑记录。
"""
import re

# 2.1.300 二进制与 API 错误里表示「订阅用量 / 限流」的字样。只作归类，判无效与续跑都不依赖它。
# 「Context limit reached」是上下文超长，不属此类，所以不收裸的「limit reached」。
USAGE_LIMIT_RE = re.compile(
    r'usage limit|hit your limit|rate[ _]limit|\b429\b|too many requests|usage credit',
    re.IGNORECASE)


def classify_run_error(text):
    """'usage_limit'（撞订阅用量限制或限流）或 'other'。"""
    return 'usage_limit' if text and USAGE_LIMIT_RE.search(str(text)) else 'other'


def usage_limit_count(arm_record):
    """该臂判无效的 run 里，撞用量限制的有几个（按 scoring.score_case 写下的 invalid_runs）。"""
    return sum(1 for c in (arm_record.get('cases') or {}).values()
               for r in c.get('invalid_runs', []) if classify_run_error(r.get('error')) == 'usage_limit')


def gate_exclusion_reason(rec):
    """闸门判据里「完整性」这一条：返回排除理由，None 表示不因完整性被排除。

    只认 run.json 里 `complete` 严格为 true；缺字段、非布尔、对照进行中留下的检查点都排除。
    同版本、指纹一致、非 dirty、已审 / 规则子集通过这几条由闸门（票 14）在此之上再判。
    """
    if not isinstance(rec, dict):
        return 'run.json 不是对象'
    if rec.get('complete') is True:
        return None
    reasons = rec.get('incomplete_reasons') or []
    if 'complete' not in rec:
        return 'run.json 没有 complete 字段，视为不完整'
    return '运行不完整' + ('：' + '；'.join(reasons) if reasons else '')
