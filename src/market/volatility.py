import pandas as pd
import numpy as np

def annualized_volatility(
    returns: pd.Series,
    periods_per_year: int = 252
) -> float:
    """
    Compute annualized volatility from periodic returns.
    """
    return returns.std(ddof=1) * np.sqrt(periods_per_year)