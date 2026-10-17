"""Server-side PDF rendering for a saved run report.

The input is the same RunDetailResponse the browser already reads. This module
does not query plans, environments or the API under test. ReportLab uses its
built-in STSong-Light CID font, so no font file is bundled.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from backend.schemas.run import RunDetailResponse

FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

REDACTED = "[redacted]"
_REPORT_TITLE = "测试运行报告"
_REPORT_NAME = "ApiPilot 测试运行报告"

_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_API_KEY = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b")
_HEADER_VALUE = re.compile(
    r"((?:authorization|cookie|set-cookie|x-api-key|api-key|token|password|secret)\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
_QUERY_VALUE = re.compile(
    r"([?&](?:token|access_token|refresh_token|id_token|api[_-]?key|apikey|key|secret|password|passwd|pwd|authorization|cookie|session|jwt)=)[^&#\s]+",
    re.IGNORECASE,
)
_RELATIVE_QUERY = re.compile(r"(/[^\s?#]*\?)[^\s#]*")

_REPORT_TEXT: dict[str, str] = {
    "console.aiTest.plan.lifecycleName": "{resource} 生命周期验证",
    "console.aiTest.plan.lifecycleGoal": "验证 {resource} 的完整生命周期。",
    "console.aiTest.scenario.authenticationName": "用户认证",
    "console.aiTest.scenario.authenticationDescription": "先调用 token 来源接口，再用该 token 访问受保护接口。",
    "console.aiTest.scenario.authenticationExpected": "认证成功，且 token 可以访问身份接口。",
    "console.aiTest.scenario.lifecycleName": "{resource} 的创建与读取",
    "console.aiTest.scenario.lifecycleDescription": "创建资源，再用返回的 id 把它读回来。",
    "console.aiTest.scenario.lifecycleExpected": "{resource} 创建成功，并可通过返回的 id 读取。",
    "console.aiTest.scenario.paymentName": "依赖型操作",
    "console.aiTest.scenario.paymentDescription": "{endpoint} 作用于先前创建的资源。",
    "console.aiTest.scenario.paymentExpected": "对已存在的资源执行该操作成功。",
    "console.aiTest.scenario.negativeName": "反例",
    "console.aiTest.scenario.negativeDescription": "发送 API 应当拒绝的请求。",
    "console.aiTest.scenario.negativeExpected": "每个非法请求都被拒绝，并返回错误状态码。",
    "console.aiTest.scenario.smokeName": "接口按文档正常响应",
    "console.aiTest.scenario.smokeDescription": "调用 {endpoint}，确认返回符合文档约定。",
    "console.aiTest.scenario.smokeExpected": "{endpoint} 返回文档声明的成功状态码。",
    "console.aiTest.step.request": "请求",
    "console.aiTest.step.extract": "提取",
    "console.aiTest.step.assert": "断言",
    "console.aiTest.step.login": "登录并获取 token",
    "console.aiTest.step.fetchIdentity": "读取当前认证身份",
    "console.aiTest.step.createResource": "创建 {resource}",
    "console.aiTest.step.readResource": "按 id 读取 {resource}",
    "console.aiTest.step.subResourceAction": "对资源执行 {action} 操作",
    "console.aiTest.step.extractVariable": "从响应中提取 {variable}",
    "console.aiTest.step.extractVariableFrom": "从 {method} {path} 响应提取 {variable}",
    "console.aiTest.step.callEndpoint": "调用 {endpoint}",
    "console.aiTest.step.assertResponse": "断言响应符合预期",
    "console.aiTest.step.assertRequestResponse": "断言 {method} {path} 响应",
    "console.aiTest.step.invalidBody": "不带必填字段调用 {endpoint}",
    "console.aiTest.step.boundaryValue": "用超出允许范围的值调用 {endpoint}",
    "console.aiTest.step.unauthenticated": "不带凭证调用 {endpoint}",
    "console.aiTest.assertion.statusIs": "响应状态码为 {status}",
    "console.aiTest.assertion.fieldPresent": "响应体包含 {field}",
    "console.aiTest.assertion.fieldIs": "响应体字段 {field} 为 {value}",
    "console.aiTest.assertion.headerIs": "响应头 {header} 为 {value}",
    "console.aiTest.assertion.resourceCreated": "创建出的资源可通过其 id 读取",
    "console.runs.failure.notExecutable": "该步骤未指定接口，没有可发起的请求。",
    "console.runs.evidence.endpoint": "实际请求",
    "console.runs.evidence.extracted": "提取变量",
    "console.runs.evidence.checked": "校验项",
}

_RUN_STATUS = {
    "queued": "排队中",
    "running": "运行中",
    "passed": "通过",
    "failed": "失败",
    "cancelled": "已取消",
}
_STEP_STATUS = {
    "pending": "待执行",
    "running": "运行中",
    "passed": "通过",
    "failed": "失败",
    "skipped": "跳过",
}
_STEP_KIND = {"request": "请求", "extract": "提取", "assert": "断言", "condition": "条件"}

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle(
    "ReportTitle",
    parent=_STYLES["Title"],
    fontName=FONT,
    fontSize=20,
    leading=26,
    textColor=colors.HexColor("#111827"),
    alignment=TA_LEFT,
)
_H2 = ParagraphStyle(
    "ReportH2",
    parent=_STYLES["Heading2"],
    fontName=FONT,
    fontSize=12,
    leading=17,
    textColor=colors.HexColor("#111827"),
    spaceBefore=10,
    spaceAfter=5,
)
_BODY = ParagraphStyle(
    "ReportBody",
    parent=_STYLES["BodyText"],
    fontName=FONT,
    fontSize=9,
    leading=13,
    wordWrap="CJK",
    textColor=colors.HexColor("#1f2937"),
)
_SMALL = ParagraphStyle(
    "ReportSmall",
    parent=_BODY,
    fontSize=7.5,
    leading=10.5,
)
_LABEL = ParagraphStyle(
    "ReportLabel",
    parent=_SMALL,
    textColor=colors.HexColor("#6b7280"),
)


def _redact_url(value: str) -> str:
    clean = value.split("#", 1)[0]
    query = clean.find("?")
    base = clean[:query] if query >= 0 else clean
    base = re.sub(r"//[^/@]+@", "//", base)
    return base + "?[redacted]" if query >= 0 else base


def redact_text(value: str | None) -> str:
    if value is None:
        return ""
    safe = _URL_IN_TEXT.sub(lambda match: _redact_url(match.group(0)), value)
    safe = _BEARER.sub(lambda match: match.group(1) + " " + REDACTED, safe)
    safe = _JWT.sub(REDACTED, safe)
    safe = _API_KEY.sub(REDACTED, safe)
    safe = _HEADER_VALUE.sub(lambda match: match.group(1) + REDACTED, safe)
    safe = _QUERY_VALUE.sub(lambda match: match.group(1) + REDACTED, safe)
    safe = _RELATIVE_QUERY.sub(lambda match: match.group(1) + "[redacted]", safe)
    return safe


def _redact_path(value: str | None) -> str:
    if not value:
        return ""
    clean = value.split("#", 1)[0]
    query = clean.find("?")
    return clean[:query] + "?[redacted]" if query >= 0 else clean


def _localized(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "text") and not hasattr(value, "key"):
        return redact_text(str(value.text))
    key = str(getattr(value, "key", ""))
    params = dict(getattr(value, "params", {}) or {})
    template = _REPORT_TEXT.get(key, key)
    for name, item in params.items():
        template = template.replace("{" + name + "}", redact_text(str(item)))
    return redact_text(template)


def _date(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return redact_text(str(value))


def _duration(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value} ms" if value < 1000 else f"{value / 1000:.1f} s"


def _paragraph(value: Any, style: ParagraphStyle = _SMALL) -> Paragraph:
    text = escape(redact_text(str(value))).replace("\n", "<br/>")
    return Paragraph(text, style)


def _localized_paragraph(value: Any, style: ParagraphStyle = _SMALL) -> Paragraph:
    return Paragraph(escape(_localized(value)).replace("\n", "<br/>"), style)


def _table(data: list[list[Any]], widths: list[float], *, header: bool = True) -> LongTable:
    rows: list[list[Any]] = []
    for row in data:
        rows.append([cell if isinstance(cell, Paragraph) else _paragraph(cell) for cell in row])
    table = LongTable(
        rows,
        colWidths=widths,
        repeatRows=1 if header else 0,
        splitByRow=1,
        splitInRow=1,
    )
    commands: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")))
        commands.append(("FONTNAME", (0, 0), (-1, 0), FONT))
    table.setStyle(TableStyle(commands))
    return table


class _NumberedCanvas(canvas.Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.setFont(FONT, 8)
            self.setFillColor(colors.HexColor("#6b7280"))
            self.drawRightString(A4[0] - 15 * mm, 8 * mm, f"第 {self._pageNumber} / {total} 页")
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)


def _header(canvas_obj: canvas.Canvas, doc: Any, run_id: str) -> None:
    canvas_obj.saveState()
    canvas_obj.setFont(FONT, 8)
    canvas_obj.setFillColor(colors.HexColor("#6b7280"))
    canvas_obj.drawString(15 * mm, A4[1] - 10 * mm, "ApiPilot · 测试运行报告")
    canvas_obj.drawRightString(A4[0] - 15 * mm, A4[1] - 10 * mm, "Run " + run_id)
    canvas_obj.setStrokeColor(colors.HexColor("#e5e7eb"))
    canvas_obj.line(15 * mm, A4[1] - 12 * mm, A4[0] - 15 * mm, A4[1] - 12 * mm)
    canvas_obj.restoreState()


def _counts(detail: RunDetailResponse) -> dict[str, int]:
    steps = [step for scenario in detail.scenarios for step in scenario.steps]
    assertions = [item for scenario in detail.scenarios for item in scenario.assertions]
    return {
        "scenarios": len(detail.scenarios),
        "steps": len(steps),
        "assertions": len(assertions),
        "passed_steps": sum(1 for step in steps if step.status == "passed"),
        "failed_steps": sum(1 for step in steps if step.status == "failed"),
        "skipped_steps": sum(1 for step in steps if step.status == "skipped"),
        "passed_assertions": sum(1 for item in assertions if item.status == "passed"),
        "failed_assertions": sum(1 for item in assertions if item.status == "failed"),
        "skipped_assertions": sum(1 for item in assertions if item.status == "skipped"),
    }


def build_report_pdf(detail: RunDetailResponse) -> tuple[bytes, datetime]:
    run = detail.run
    generated_at = datetime.now(timezone.utc)
    counts = _counts(detail)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=19 * mm,
        bottomMargin=18 * mm,
        title=_REPORT_NAME,
        author="ApiPilot",
    )
    story: list[Any] = [
        Paragraph("ApiPilot", _LABEL),
        Paragraph(_REPORT_TITLE, _TITLE),
        Paragraph("生成时间：" + _date(generated_at) + " · Run ID：" + run.id, _SMALL),
        Spacer(1, 8),
    ]
    meta = [
        ["项目 ID", run.project_id, "状态", _RUN_STATUS.get(run.status, run.status)],
        ["计划", _localized(run.plan_name), "计划 ID", run.plan_id],
        ["环境 ID", run.environment_id, "Base URL", _redact_url(run.base_url)],
        ["创建时间", _date(run.created_at), "开始时间", _date(run.started_at)],
        ["结束时间", _date(run.finished_at), "耗时", _duration(run.duration_ms)],
        ["变量数量", str(len(run.variable_keys)), "环境/变量值", "不写入报告"],
    ]
    story.append(_table(meta, [30 * mm, 60 * mm, 30 * mm, 60 * mm], header=False))
    story.append(Paragraph("运行摘要", _H2))
    summary_rows = [
        ["指标", "数量"],
        ["场景", str(counts["scenarios"])],
        ["步骤", str(counts["steps"])],
        ["断言", str(counts["assertions"])],
        ["通过步骤", str(counts["passed_steps"])],
        ["失败步骤", str(counts["failed_steps"])],
        ["跳过步骤", str(counts["skipped_steps"])],
        ["通过断言", str(counts["passed_assertions"])],
        ["失败断言", str(counts["failed_assertions"])],
        ["跳过断言", str(counts["skipped_assertions"])],
    ]
    story.append(_table(summary_rows, [90 * mm, 90 * mm]))
    story.append(Paragraph("结论", _H2))
    conclusion = {
        "passed": "服务端将本次运行记录为通过。",
        "failed": "服务端将本次运行记录为失败；下方列出已持久化的失败信息。",
        "cancelled": "服务端将本次运行记录为已取消；已完成的结果仍然保留。",
    }.get(run.status, "服务端记录了本次运行。")
    story.append(Paragraph(escape(conclusion), _BODY))
    if run.failure is not None:
        story.append(
            Paragraph(
                "错误：" + escape(_localized(run.failure.message))
                + ("" if run.failure.detail is None else " - " + escape(redact_text(run.failure.detail))),
                _BODY,
            )
        )
    story.append(Paragraph("执行详情", _H2))
    if not detail.scenarios:
        story.append(Paragraph("本次运行没有记录场景。", _BODY))
    for scenario in detail.scenarios:
        story.append(
            Paragraph(
                f"{scenario.index + 1}. {escape(_localized(scenario.name))} · "
                + _STEP_STATUS.get(scenario.status, scenario.status),
                _H2,
            )
        )
        if not scenario.steps:
            story.append(Paragraph("该场景没有记录步骤。", _SMALL))
        else:
            step_rows: list[list[Any]] = [["#", "类型", "描述", "HTTP", "状态", "耗时"]]
            for step in scenario.steps:
                evidence = "; ".join(
                    _localized(item.label) + ": " + redact_text(item.value)
                    for item in step.evidence
                )
                description = _localized(step.description)
                if evidence:
                    description += "\n证据: " + evidence
                if step.failure is not None:
                    description += "\n错误: " + _localized(step.failure.message)
                    if step.failure.detail is not None:
                        description += " - " + redact_text(step.failure.detail)
                http = " ".join(
                    part for part in (step.method or "", _redact_path(step.path)) if part
                ) or "-"
                step_rows.append(
                    [
                        str(step.index + 1),
                        _STEP_KIND.get(step.kind, step.kind),
                        _paragraph(description),
                        _paragraph(http),
                        _STEP_STATUS.get(step.status, step.status),
                        _duration(step.duration_ms),
                    ]
                )
            story.append(_table(step_rows, [8 * mm, 16 * mm, 78 * mm, 42 * mm, 18 * mm, 18 * mm]))
        if not scenario.assertions:
            story.append(Paragraph("该场景没有记录断言。", _SMALL))
        else:
            assertion_rows: list[list[Any]] = [["断言", "目标", "期望", "实际", "状态"]]
            for assertion in scenario.assertions:
                actual = (
                    redact_text(assertion.actual)
                    if assertion.kind == "status" and assertion.actual is not None
                    else "未记录或出于隐私不显示"
                )
                assertion_rows.append(
                    [
                        _paragraph(_localized(assertion.description)),
                        _paragraph(redact_text(assertion.target)),
                        _paragraph(redact_text(assertion.expected)),
                        _paragraph(actual),
                        _STEP_STATUS.get(assertion.status, assertion.status),
                    ]
                )
            story.append(_table(assertion_rows, [62 * mm, 38 * mm, 30 * mm, 30 * mm, 20 * mm]))
    story.append(Paragraph("范围与限制", _H2))
    story.append(
        Paragraph(
            "本报告只使用 ApiPilot 已保存的运行数据。运行记录没有保存请求/响应正文、"
            "headers、环境变量值或运行时变量值，因此报告不包含这些内容；URL 查询参数值已移除。",
            _BODY,
        )
    )
    story.append(Paragraph("基于本次运行已保存的结果生成，不会重新发起任何请求。", _SMALL))
    doc.build(
        story,
        onFirstPage=lambda canvas_obj, doc_obj: _header(canvas_obj, doc_obj, run.id),
        onLaterPages=lambda canvas_obj, doc_obj: _header(canvas_obj, doc_obj, run.id),
        canvasmaker=_NumberedCanvas,
    )
    content = buffer.getvalue()
    if not content.startswith(b"%PDF") or len(content) < 100:
        raise ValueError("the PDF renderer did not produce a valid PDF")
    return content, generated_at


def report_name() -> str:
    return _REPORT_NAME


def report_filename(run_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", run_id.strip())
    return "ApiPilot-Run-" + (safe or "unknown") + ".pdf"


def report_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
