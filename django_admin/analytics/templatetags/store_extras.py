from django import template

register = template.Library()


def _indian_group(whole: str) -> str:
    """1234567 -> 12,34,567"""
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


@register.filter
def inr(value, decimals=2):
    """₹1,23,456.78"""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return value
    whole, _, frac = f"{abs(amount):.{int(decimals)}f}".partition(".")
    sign = "-" if amount < 0 else ""
    return f"{sign}₹{_indian_group(whole)}{'.' + frac if frac else ''}"


@register.filter
def inr_compact(value):
    """₹7.7L / ₹1.2Cr / ₹9.8K — for axis ticks and bar tips."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return value
    for size, suffix in ((1e7, "Cr"), (1e5, "L"), (1e3, "K")):
        if abs(amount) >= size:
            return f"₹{amount / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"₹{amount:.0f}"
