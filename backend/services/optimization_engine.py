import numpy as np
import pandas as pd
import scipy.optimize as sco
from typing import Tuple, List, Dict

# Risk-free rate assumption (could be dynamic, but 2% is a reasonable baseline for university-style MPT)
RISK_FREE_RATE = 0.02
TRADING_DAYS = 252

def calculate_portfolio_stats(weights: np.ndarray, returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> Tuple[float, float, float]:
    """
    Calculate annualized return, volatility, and Sharpe ratio for a portfolio.
    """
    port_return = np.sum(returns_mean * weights)
    port_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
    sharpe_ratio = (port_return - RISK_FREE_RATE) / port_volatility if port_volatility > 0 else 0
    return port_return, port_volatility, sharpe_ratio

def neg_sharpe_ratio(weights: np.ndarray, returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> float:
    """Objective function for Max Sharpe optimization (scipy minimizes)."""
    return -calculate_portfolio_stats(weights, returns_mean, cov_matrix)[2]

def portfolio_volatility(weights: np.ndarray, returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> float:
    """Objective function for Min Volatility optimization."""
    return calculate_portfolio_stats(weights, returns_mean, cov_matrix)[1]

def portfolio_return(weights: np.ndarray, returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> float:
    """Objective function for target return constraint."""
    return calculate_portfolio_stats(weights, returns_mean, cov_matrix)[0]

def _get_constraints_and_bounds(num_assets: int) -> Tuple[Tuple, Tuple]:
    """Helper to generate standard long-only, fully invested constraints."""
    constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1}) # sum(weights) = 1
    bounds = tuple((0, 1) for _ in range(num_assets))              # 0 <= weight <= 1
    return constraints, bounds

def solve_max_sharpe(returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> dict:
    """Find the portfolio weights that maximize the Sharpe ratio."""
    num_assets = len(returns_mean)
    args = (returns_mean, cov_matrix)
    constraints, bounds = _get_constraints_and_bounds(num_assets)
    init_guess = num_assets * [1. / num_assets,] # Equal weight start
    
    result = sco.minimize(neg_sharpe_ratio, init_guess, args=args,
                          method='SLSQP', bounds=bounds, constraints=constraints)
    
    port_ret, port_vol, sharpe = calculate_portfolio_stats(result.x, returns_mean, cov_matrix)
    return {
        "weights": pd.Series(np.round(result.x, 4), index=returns_mean.index),
        "return": port_ret,
        "volatility": port_vol,
        "sharpe": sharpe,
        "success": result.success
    }

def solve_min_volatility(returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> dict:
    """Find the portfolio weights that minimize overall volatility."""
    num_assets = len(returns_mean)
    args = (returns_mean, cov_matrix)
    constraints, bounds = _get_constraints_and_bounds(num_assets)
    init_guess = num_assets * [1. / num_assets,]
    
    result = sco.minimize(portfolio_volatility, init_guess, args=args,
                          method='SLSQP', bounds=bounds, constraints=constraints)
    
    port_ret, port_vol, sharpe = calculate_portfolio_stats(result.x, returns_mean, cov_matrix)
    return {
        "weights": pd.Series(np.round(result.x, 4), index=returns_mean.index),
        "return": port_ret,
        "volatility": port_vol,
        "sharpe": sharpe,
        "success": result.success
    }

def solve_target_risk(returns_mean: pd.Series, cov_matrix: pd.DataFrame, target_risk: float) -> dict:
    """Find the portfolio weights that maximize return for a given target volatility (risk)."""
    num_assets = len(returns_mean)
    args = (returns_mean, cov_matrix)
    
    def neg_portfolio_return(w, ret_mean, cov):
        return -portfolio_return(w, ret_mean, cov)
        
    constraints = (
        {'type': 'eq', 'fun': lambda x: np.sum(x) - 1},
        {'type': 'eq', 'fun': lambda x: portfolio_volatility(x, returns_mean, cov_matrix) - target_risk}
    )
    bounds = tuple((0, 1) for _ in range(num_assets))
    init_guess = num_assets * [1. / num_assets,]
    
    result = sco.minimize(neg_portfolio_return, init_guess, args=args,
                          method='SLSQP', bounds=bounds, constraints=constraints)
    
    port_ret, port_vol, sharpe = calculate_portfolio_stats(result.x, returns_mean, cov_matrix)
    return {
        "weights": pd.Series(np.round(result.x, 4), index=returns_mean.index),
        "return": port_ret,
        "volatility": port_vol,
        "sharpe": sharpe,
        "success": result.success
    }

def calculate_efficient_frontier(returns_mean: pd.Series, cov_matrix: pd.DataFrame, num_points: int = 50) -> pd.DataFrame:
    """
    Calculate points along the efficient frontier.
    Finds the min volatility portfolio for a range of target returns.
    """
    min_vol_res = solve_min_volatility(returns_mean, cov_matrix)
    max_ret_asset = returns_mean.max()
    
    if not min_vol_res["success"]:
        return pd.DataFrame()
        
    target_returns = np.linspace(min_vol_res["return"], max_ret_asset, num_points)
    frontier_vols = []
    frontier_returns = []
    
    num_assets = len(returns_mean)
    args = (returns_mean, cov_matrix)
    _, bounds = _get_constraints_and_bounds(num_assets)
    init_guess = num_assets * [1. / num_assets,]
    
    # Continuation guess: start with the solved weights of min volatility
    current_guess = np.array(min_vol_res["weights"].values) if "weights" in min_vol_res else np.array(init_guess)
    
    for tr in target_returns:
        constraints = (
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1},
            {'type': 'eq', 'fun': lambda x: portfolio_return(x, returns_mean, cov_matrix) - tr}
        )
        res = sco.minimize(portfolio_volatility, current_guess, args=args,
                           method='SLSQP', bounds=bounds, constraints=constraints)
        if res.success:
            frontier_vols.append(res.fun)
            frontier_returns.append(tr)
            current_guess = res.x  # Update guess for the next target return point
            
    return pd.DataFrame({"Volatility": frontier_vols, "Return": frontier_returns})

def backtest_portfolio(daily_returns: pd.DataFrame, weights: pd.Series, lookback_days: int = 252) -> pd.Series:
    """
    Calculate the historical cumulative return of a fixed-weight portfolio.
    Uses daily rebalancing assumption for mathematical simplicity in MPT.
    """
    # Ensure weights match columns
    common_assets = list(set(daily_returns.columns) & set(weights.index))
    if not common_assets:
        return pd.Series(dtype=float)
        
    dr_clean = daily_returns[common_assets].tail(lookback_days).dropna()
    w_clean = weights[common_assets]
    # Normalize weights just in case
    w_clean = w_clean / w_clean.sum()
    
    # Portfolio daily returns
    port_daily_ret = dr_clean.dot(w_clean)
    
    # Cumulative return (rebased to 1.0)
    cumulative_ret = (1 + port_daily_ret).cumprod()
    # Subtract 1 to show % return, and prepend 0 for the start date
    # But usually it's better to return the index factor (starting at 1) for plotting
    return cumulative_ret

def forecast_performance(mu: float, sigma: float, initial_value: float = 1.0, horizon_days: int = 252, simulations: int = 1000) -> pd.DataFrame:
    """
    Generate probabilistic forecast bands using Geometric Brownian Motion (GBM).
    Returns a DataFrame with Median, Upper/Lower 1-sigma, and Upper/Lower 2-sigma bands.
    """
    dt = 1 / TRADING_DAYS
    # We use log returns for GBM drift
    drift = (mu - 0.5 * sigma**2) * dt
    vol = sigma * np.sqrt(dt)
    
    # Generate random paths
    np.random.seed(42) # For reproducibility in UI
    Z = np.random.normal(0, 1, (horizon_days, simulations))
    daily_returns = np.exp(drift + vol * Z)
    
    # Calculate price paths
    price_paths = np.zeros_like(daily_returns)
    price_paths[0] = initial_value
    for t in range(1, horizon_days):
        price_paths[t] = price_paths[t-1] * daily_returns[t]
        
    # Calculate percentiles at each time step
    percentiles = np.percentile(price_paths, [2.5, 16, 50, 84, 97.5], axis=1)
    
    # Create future date index
    future_dates = [pd.Timestamp.today() + pd.Timedelta(days=i) for i in range(horizon_days)]
    
    df_forecast = pd.DataFrame({
        "Date": future_dates,
        "Lower_2Sigma": percentiles[0],
        "Lower_1Sigma": percentiles[1],
        "Median": percentiles[2],
        "Upper_1Sigma": percentiles[3],
        "Upper_2Sigma": percentiles[4]
    }).set_index("Date")
    
    return df_forecast

def solve_for_target_volatility(target_vol: float, returns_mean: pd.Series, cov_matrix: pd.DataFrame) -> dict:
    """
    Find the portfolio weights that maximize return for a specific target volatility.
    This effectively finds the point on the Efficient Frontier for a given risk level.
    """
    num_assets = len(returns_mean)
    args = (returns_mean, cov_matrix)
    _, bounds = _get_constraints_and_bounds(num_assets)
    init_guess = num_assets * [1. / num_assets,]
    
    # We minimize negative return (to maximize return)
    # Subject to: 
    # 1. Sum of weights = 1
    # 2. Portfolio volatility = target_vol
    def neg_return(w, mu, cov): return -np.sum(mu * w)
    
    constraints = (
        {'type': 'eq', 'fun': lambda x: np.sum(x) - 1},
        {'type': 'eq', 'fun': lambda x: portfolio_volatility(x, returns_mean, cov_matrix) - target_vol}
    )
    
    result = sco.minimize(neg_return, init_guess, args=args,
                          method='SLSQP', bounds=bounds, constraints=constraints)
    
    port_ret, port_vol, sharpe = calculate_portfolio_stats(result.x, returns_mean, cov_matrix)
    return {
        "weights": pd.Series(np.round(result.x, 4), index=returns_mean.index),
        "return": port_ret,
        "volatility": port_vol,
        "sharpe": sharpe,
        "success": result.success
    }
