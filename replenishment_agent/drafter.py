"""Supplier message drafting.

The deterministic template is the source of truth. An LLM may only REPHRASE it, and its text is
rejected if it contains any number that is not in the template (no invented quantities, prices or dates).
Nothing is sent: the output is a draft for the buyer.
"""
from __future__ import annotations
import os, re

NUM = re.compile(r"\d[\d,]*\.?\d*")


def _fmt_qty(line: dict) -> str:
    if line["unit"] == "g":                       # chemicals are stored in grams, shown in kg
        return f"{line['qty'] / 1000:,.0f} kg"
    return f"{line['qty']:,.0f} pcs"


def template_message(supplier_name: str, pr_number: str, lines: list[dict], lang: str = "en", rfq: bool = False) -> str:
    """lines: dicts with material, qty, unit, needed_by (ISO date)."""
    if lang == "ar":
        rows = "\n".join(f"- {_label(l, 'ar')}: {_fmt_qty(l).replace('kg','كجم').replace('pcs','قطعة')}"
                         f" - مطلوب بحلول {l['needed_by']}" for l in lines)
        return (f"السادة / {supplier_name}\nتحية طيبة،\n\n"
                f"بخصوص {'طلب عرض السعر' if rfq else 'طلب الشراء'} رقم {pr_number}، نرجو التكرم بإفادتنا بسعر الوحدة وموعد التوريد "
                f"وأقل كمية للطلب للأصناف التالية:\n{rows}\n\n"
                "هذه رسالة مسودة لطلب عرض سعر، ولا تمثل التزامًا بالشراء.\n\nشكرًا لتعاونكم.")
    rows = "\n".join(f"- {_label(l, 'en')}: {_fmt_qty(l)} - needed by {l['needed_by']}" for l in lines)
    return (f"Dear {supplier_name},\n\n"
            f"Regarding {'our request for quotation' if rfq else 'purchase request'} {pr_number}, please confirm your unit price, delivery date and "
            f"minimum order quantity for the following items:\n{rows}\n\n"
            "This is a draft request for quotation and does not commit us to a purchase.\n\nBest regards,")


def _label(l: dict, lang: str = "en") -> str:
    """Item name as the SUPPLIER knows it (from a confirmed website match), with our reference so both sides agree.
    Without a confirmed match: our material name only."""
    name, code = l.get("supplier_name"), l.get("supplier_code")
    if not name and not code:
        return l["material"]
    if lang == "ar":
        return f"{name or code}" + (f" (كود {code}، مرجعنا {l['material']})" if code and name
                                    else f" (مرجعنا {l['material']})")
    return f"{name or code}" + (f" (your code {code}, our ref {l['material']})" if code and name
                                else f" (our ref {l['material']})")


def _numbers(text: str) -> set[str]:
    out = set()
    for tok in NUM.findall(text):
        out.add(tok.replace(",", "").rstrip("."))
    return out


def numbers_are_safe(candidate: str, reference: str) -> bool:
    """True if every number in candidate also appears in the reference template."""
    return _numbers(candidate) <= _numbers(reference)


def _call_claude(prompt: str) -> str:          # pragma: no cover  (needs network and an API key)
    import anthropic
    client = anthropic.Anthropic()
    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
    msg = client.messages.create(model=model, max_tokens=700,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "text", None))


def draft_message(supplier_name, pr_number, lines, lang="en", llm=None, rfq=False):
    """Returns (text, source). source = 'template' | 'llm'. llm: callable(prompt)->str, or None."""
    base = template_message(supplier_name, pr_number, lines, lang, rfq)
    if llm is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return base, "template"
    llm = llm or _call_claude
    prompt = ("Rewrite this supplier request politely and concisely in "
              f"{'Arabic' if lang == 'ar' else 'English'}. Keep every item, quantity and date exactly as given. "
              "Do not add prices, numbers, discounts or commitments. Return only the message.\n\n" + base)
    try:
        out = llm(prompt).strip()
    except Exception:
        return base, "template"
    if out and numbers_are_safe(out, base):
        return out, "llm"
    return base, "template"        # guardrail: invented numbers -> fall back to the template


# ---------------------------------------------------------------- RFQ and purchase order messages
def _unit_word(unit, lang):
    if lang == "ar":
        return "كجم" if unit == "g" else "قطعة"
    return "kg" if unit == "g" else "piece"


def rfq_message(supplier_name, rfq_number, lines, lang="en", llm=None):
    """Request for quotation. The free text may be rephrased by an LLM (guarded); the reply-format block is
    always the fixed template so the reply can be read back automatically. Returns (subject, body, source)."""
    text, source = draft_message(supplier_name, rfq_number, lines, lang, llm, rfq=True)
    if lang == "ar":
        subject = f"[{rfq_number}] طلب عرض سعر"
        rows = "\n".join(f"{_label(l, 'ar')} | سعر الوحدة: ____ جنيه لكل {_unit_word(l['unit'], 'ar')} | "
                         f"أقل كمية: ____ | مدة التوريد: ____ يوم | العرض سارٍ حتى: ____" for l in lines)
        block = (f"\n\nالرقم المرجعي: {rfq_number} (يرجى الإبقاء عليه في عنوان الرد)\n"
                 f"يرجى الرد بسطر لكل صنف بهذا الشكل:\n{rows}")
    else:
        subject = f"[{rfq_number}] Request for quotation"
        rows = "\n".join(f"{_label(l, 'en')} | unit price: EGP ____ per {_unit_word(l['unit'], 'en')} | "
                         f"MOQ: ____ | lead time: ____ days | valid until: ____" for l in lines)
        block = (f"\n\nReference: {rfq_number} (please keep it in the subject of your reply)\n"
                 f"Please reply with one line per item in this format:\n{rows}")
    return subject, text + block, source


def po_message(supplier_name, po_number, lines, lang="en"):
    """lines: material, qty, unit, price_egp, basis_word, delivery_date. Returns (subject, body)."""
    if lang == "ar":
        rows = "\n".join(f"- {_label(l, 'ar')}: {_fmt_qty(l).replace('kg','كجم').replace('pcs','قطعة')} "
                         f"بسعر {l['price_egp']:,.2f} جنيه لكل {_unit_word(l['unit'], 'ar')} - التسليم {l['delivery_date']}"
                         for l in lines)
        return (f"[{po_number}] أمر شراء",
                f"السادة / {supplier_name}\nتحية طيبة،\n\nنرفق أمر الشراء رقم {po_number} للأصناف التالية:\n{rows}\n\n"
                f"يرجى تأكيد الاستلام، وإرسال إشعار الشحن مع رقم التتبع عند الشحن، مع الإبقاء على {po_number} في عنوان الرسالة."
                "\n\nشكرًا لتعاونكم.")
    rows = "\n".join(f"- {_label(l, 'en')}: {_fmt_qty(l)} at EGP {l['price_egp']:,.2f} per {_unit_word(l['unit'], 'en')}"
                     f" - delivery {l['delivery_date']}" for l in lines)
    return (f"[{po_number}] Purchase order",
            f"Dear {supplier_name},\n\nPlease find our purchase order {po_number} for:\n{rows}\n\n"
            f"Please confirm receipt, and when the goods ship send the shipping notice with the quantities shipped, "
            f"the carrier and the tracking number. Keep {po_number} in the subject.\n\nBest regards,")
