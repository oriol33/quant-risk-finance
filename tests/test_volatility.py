import pandas as pd
from risk_metrics.market import annualized_volatility

def test_volatility_positive():
    r = pd.Series([0.01, -0.01, 0.02, -0.02])
    assert annualized_volatility(r) > 0