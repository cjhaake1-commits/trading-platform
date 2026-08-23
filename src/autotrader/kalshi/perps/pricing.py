from decimal import Decimal

from ..foundation import PriceBand


def validate_price_band(band: PriceBand, *, side: str, price: Decimal) -> bool:
    return band.admissible(side, price)

