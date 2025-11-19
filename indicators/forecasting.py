import pandas as pd
from utilsforecast.plotting import plot_series
from utilsforecast.evaluation import evaluate
from utilsforecast.losses import *

import warnings
warnings.filterwarnings('ignore')

from statsforecast import StatsForecast
from statsforecast.models import Naive, HistoricAverage, WindowAverage, SeasonalNaive, AutoARIMA

# --- Forecasting ---
def forecasting(df, interval, h):
    """
    Perform forecasting on the given time series data using various models.

    Parameters:
    df (pd.DataFrame): DataFrame containing 'unique_id', 'ds' (date), and 'y' (value) columns.
    h (int): Forecast horizon.

    Returns:
    pd.DataFrame: DataFrame containing forecasts from different models.
    """

    # Initialize forecasting models
    models = [
        Naive(),
        HistoricAverage(),
        WindowAverage(window_size=7),
        SeasonalNaive(season_length=7)
    ]

    # Create StatsForecast object
    sf = StatsForecast(
        models=models,
        freq=interval  # Assuming daily frequency; adjust as needed
    )

    # Generate forecasts
    forecasts = sf.forecast(df=df, h=h)

    return forecasts
