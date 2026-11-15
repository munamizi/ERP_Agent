"""人民币金额转换；数据库以整数分保存金额。"""

from decimal import Decimal


def to_fen(value: str | Decimal | int) -> int:
    """
    将人民币元转换为整数分，拒绝非有限金额及多余小数位。

    Args:
        value - 以元表示的金额
    Returns:
        整数分金额；格式错误时抛出 ValueError。
    """
    amount = Decimal(str(value))
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("金额必须是有限数，且最多包含两位小数")
    return int(amount * 100)


def yuan(fen: int) -> str:
    """
    将整数分格式化为两位小数的人民币元字符串。

    Args:
        fen - 整数分金额
    Returns:
        可用于接口和页面的人民币元字符串。
    """
    return f"{Decimal(fen) / 100:.2f}"


def allocate(total: int, weights: list[int]) -> list[int]:
    """
    按权重分摊整数金额，将剩余整分依次分给余数较大的项目。

    Args:
        total - 待分摊的非负整数分金额
        weights - 各项的非负权重，合计必须大于零
    Returns:
        与权重逐项对应且总和等于 total 的整数分金额列表。
    """
    if total < 0 or not weights or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("分摊权重必须非负且合计大于零")
    quotients = [divmod(total * weight, sum(weights)) for weight in weights]
    result = [value for value, _ in quotients]
    ranked = sorted(range(len(weights)), key=lambda index: (-quotients[index][1], index))
    for index in ranked[:total - sum(result)]:
        result[index] += 1
    return result
