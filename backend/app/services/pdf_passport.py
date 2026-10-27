"""Real, printable home and equipment PDFs using observed database facts only."""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from app.db.models import Property, Room
from app.db.models.ecosystem import HomeEquipment, HomeHistoryEvent, WorkOrder


def _font_name() -> str:
    """Register a Cyrillic-capable font installed on the server/host."""
    name = "OmaSansCyrillic"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    specified = os.getenv("OMA_PDF_FONT_PATH", "").strip()
    candidates = [
        specified,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pdfmetrics.registerFont(TTFont(name, candidate))
            return name
    raise RuntimeError(
        "Cyrillic PDF font unavailable: install DejaVu Sans/Arial or "
        "set OMA_PDF_FONT_PATH to an installed .ttf file."
    )


def _date(value) -> str:
    if value is None:
        return "Не указана"
    if isinstance(value, str):
        return value[:10]
    return value.strftime("%d.%m.%Y")


def _read_json(value: str | None) -> dict:
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _clean(value) -> str:
    if value is None or value == "":
        return "Нет данных"
    return escape(str(value))


def _style(font: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("OmaTitle", fontName=font, fontSize=19,
                                leading=27, textColor=colors.HexColor("#14364B")),
        "section": ParagraphStyle("OmaSection", fontName=font, fontSize=12,
                                  leading=18, spaceBefore=13, spaceAfter=6,
                                  textColor=colors.HexColor("#155B79")),
        "body": ParagraphStyle("OmaBody", fontName=font, fontSize=9,
                               leading=14, spaceAfter=4),
        "small": ParagraphStyle("OmaSmall", fontName=font, fontSize=8,
                                leading=12, textColor=colors.HexColor("#526576")),
        "footer": ParagraphStyle("OmaFooter", fontName=font, fontSize=8,
                                 leading=11, alignment=TA_CENTER),
    }


def _pdf(title: str, sections: list[tuple[str, list[str]]], *, demo: bool) -> bytes:
    font = _font_name()
    styles = _style(font)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=45, rightMargin=45,
                            topMargin=42, bottomMargin=50, title=title,
                            author="ОМА. Дом")
    items = [
        Paragraph(escape(title), styles["title"]),
        Spacer(1, 6),
        Paragraph("Сформировано: " + _date(datetime.now(timezone.utc)), styles["small"]),
    ]
    if demo:
        items.append(Paragraph(
            "ДЕМОНСТРАЦИОННЫЙ АККАУНТ. Сведения не являются официальным "
            "документом ОМА или подтверждением реальной покупки.",
            styles["small"],
        ))
    items.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#BED4DF"), spaceBefore=9))
    for heading, rows in sections:
        block = [Paragraph(escape(heading), styles["section"])]
        block.extend(Paragraph(escape(row).replace("\n", "<br/>"), styles["body"])
                     for row in rows)
        if len(block) == 1:
            block.append(Paragraph("Сведения отсутствуют", styles["small"]))
        items.extend(block)

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#526576"))
        canvas.drawCentredString(A4[0] / 2, 28,
                                "ОМА. Дом · стр. " + str(_doc.page))
        canvas.restoreState()

    doc.build(items, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def home_passport_pdf(
    prop: Property, rooms: list[Room], equipment: list[HomeEquipment],
    history: list[HomeHistoryEvent], work_orders: list[WorkOrder],
    *, demo: bool
) -> bytes:
    general = [
        "Название: " + _clean(prop.name),
        "Тип жилья: " + _clean(prop.property_type),
        "Адрес/обозначение: " + _clean(prop.address),
        "Владение: " + _clean({"owned":"Собственное","rented":"Арендованное"}.get(
            prop.tenure, prop.tenure)),
        "Создано: " + _date(prop.created_at),
        "Обновлено: " + _date(prop.updated_at),
    ]
    rooms_rows = []
    for room in rooms:
        dimensions = " × ".join(
            str(float(v)) if v is not None else "?"
            for v in (room.width_m, room.length_m, room.height_m)
        )
        rooms_rows.append(
            room.name + " (" + str(room.room_type or "тип не указан") +
            ") — размеры, м (ширина × длина × высота): " + dimensions
        )
    equipment_rows = [
        item.name + " — количество: " + str(item.quantity) + "; состояние: " +
        str(item.status) + "; товар ОМА: " +
        (item.product_id or "не привязан") + "; комната: " +
        str(item.room_id or "не указана")
        for item in equipment
    ]
    work_rows = [
        "Заявка #" + str(order.id) + ": " + order.title +
        " — статус " + order.status + "; мастер #" + str(order.contractor_id)
        for order in work_orders
    ]
    history_rows = [
        _date(event.occurred_at) + ": " + event.title +
        (" — " + event.description if event.description else "")
        for event in history
    ]
    return _pdf("Технический паспорт жилья", [
        ("Объект", general), ("Помещения", rooms_rows),
        ("Зарегистрированное оборудование", equipment_rows),
        ("Связанные заявки", work_rows),
        ("История обслуживания и работ", history_rows),
    ], demo=demo)


def equipment_passport_pdf(item: HomeEquipment, events: list[HomeHistoryEvent], *,
                           demo: bool) -> bytes:
    snapshot = _read_json(item.product_snapshot_json)
    specs = _read_json(item.specifications_json)
    common = [
        "Название: " + _clean(item.name),
        "Модель: " + _clean(snapshot.get("model")),
        "Бренд: " + _clean(snapshot.get("brand")),
        "Артикул/ID товара: " + _clean(item.product_id),
        "Количество: " + str(item.quantity),
        "Состояние: " + _clean(item.status),
        "Дата установки/регистрации: " + _date(item.installed_at),
        "Гарантия: " + _clean(snapshot.get("warranty")),
        "Инструкция производителя: " + _clean(snapshot.get("manual_url")),
        "Интервал обслуживания не установлен"
            if not snapshot.get("service_interval")
            else "Регламент обслуживания: " + str(snapshot["service_interval"]),
        "Примечания: " + _clean(item.notes),
    ]
    specifications = [str(key) + ": " + str(value) for key,value in specs.items()]
    history = [
        _date(ev.occurred_at) + ": " + ev.title +
        (" — " + ev.description if ev.description else "")
        for ev in events
    ]
    return _pdf("Технический паспорт оборудования", [
        ("Оборудование", common),
        ("Подтверждённые сведения и характеристики", specifications),
        ("Связанная история работ", history),
    ], demo=demo)
