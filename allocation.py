"""Allocation input conversions; currency uses cents, weights retain precision."""
from decimal import Decimal, ROUND_HALF_UP
import math

from models import ValidationError, weight_guidance

MAX_CAPITAL = 1_000_000_000_000.0


def money(value):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValidationError('Allocation amounts must be finite numbers.')
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def amount_total(amounts):
    """Preview the supplied total even while some inputs are empty."""
    return float(sum((Decimal(str(v)) for v in amounts if v is not None), Decimal(0)))


def resolve_allocation(mode, values, capital=None):
    if any(v is None for v in values):
        field = 'amount' if mode == 'amount' else 'weight'
        raise ValidationError(f'Enter every stock {field}, or enter 0 for no allocation.')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
        raise ValidationError('Allocation values must be finite, non-negative numbers.')
    if mode == 'amount':
        capital = amount_total(values)
        if not 0 < capital <= MAX_CAPITAL:
            raise ValidationError('Total amount must be above USD 0 and at most USD 1 trillion.')
        weights = tuple(float(Decimal(str(v)) / Decimal(str(capital)) * 100) for v in values)
    else:
        weights = tuple(values)
        if any(w > 100 for w in weights) or not math.isclose(sum(weights), 100, abs_tol=0.001):
            raise ValidationError(weight_guidance(weights))
        if capital is None or not math.isfinite(capital) or not 0 < capital <= MAX_CAPITAL:
            raise ValidationError('Starting capital must be above USD 0 and at most USD 1 trillion.')
    return float(capital), weights


def amounts_from_weights(capital, weights):
    """Allocate whole cents by largest remainder, preserving the total budget."""
    cents = int(Decimal(str(capital)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)
    decimal_weights = [Decimal(str(w)) for w in weights]
    total = sum(decimal_weights)
    exact = [Decimal(cents) * w / total for w in decimal_weights]
    allocated = [int(v) for v in exact]
    order = sorted(range(len(weights)), key=lambda i: exact[i] - allocated[i], reverse=True)
    for i in order[:cents - sum(allocated)]:
        allocated[i] += 1
    return tuple(v / 100 for v in allocated)
