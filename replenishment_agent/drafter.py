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


def template_message(supplier_name: str, pr_number: str, lines: list[dict], lang: str = "en") -> str:
    """lines: dicts with material, qty, unit, needed_by (ISO date)."""
    if lang == "ar":
        rows = "\n".join(f"- {l['material']}: {_fmt_qty(l).replace('kg','كجم').replace('pcs','قطعة')}"
                         f" - مطلوب بحلول {l['needed_by']}" for l in lines)
        return (f"السادة / {supplier_name}\nتحية طيبة،\n\n"
                f"بخصوص طلب الشراء رقم {pr_number}، نرجو التكرم بإفادتنا بسعر الوحدة وموعد التوريد "
                f"وأقل كمية للطلب للأصناف التالية:\n{rows}\n\n"
                "هذه رسالة مسودة لطلب عرض سعر، ولا تمثل التزامًا بالشراء.\n\nشكرًا لتعاونكم.")
    rows = "\n".join(f"- {l['material']}: {_fmt_qty(l)} - needed by {l['needed_by']}" for l in lines)
    return (f"Dear {supplier_name},\n\n"
            f"Regarding purchase request {pr_number}, please confirm your unit price, delivery date and "
            f"minimum order quantity for the following items:\n{rows}\n\n"
            "This is a draft request for quotation and does not commit us to a purchase.\n\nBest regards,")


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


def draft_message(supplier_name, pr_number, lines, lang="en", llm=None):
    """Returns (text, source). source = 'template' | 'llm'. llm: callable(prompt)->str, or None."""
    base = template_message(supplier_name, pr_number, lines, lang)
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
