"""Money conversion checks independent of the Streamlit widget implementation."""
from decimal import Decimal

import pytest

from allocation import amounts_from_weights, money, resolve_allocation
from models import ValidationError


@pytest.mark.parametrize('capital,count',[(100000.,3),(.01,3),(999.99,7),(1e12,20)])
def test_equal_split_preserves_every_cent(capital,count):
    amounts=amounts_from_weights(capital,[1]*count)
    assert sum(Decimal(str(v)) for v in amounts)==Decimal(str(capital))
    assert max(amounts)-min(amounts)<=.010001
    assert all(Decimal(str(v))*100==int(Decimal(str(v))*100) for v in amounts)


def test_amount_ratio_uses_unrounded_weights_and_zero_allocation():
    capital,weights=resolve_allocation('amount',[.01,.02,0.])
    assert capital==.03
    assert weights==pytest.approx((100/3,200/3,0.))
    assert weights[0]!=33.33
    assert amounts_from_weights(capital,weights)==(.01,.02,0.)
    assert money(1.005)==1.01


@pytest.mark.parametrize('amounts',[[None,1.,1.],[0.,0.,0.],[-1.,2.,3.],[float('nan'),1.,1.],[1e12,1e12,0.]])
def test_invalid_amounts_do_not_become_an_analysis(amounts):
    with pytest.raises(ValidationError):
        resolve_allocation('amount',amounts)
