import numpy as np
# import seaborn as sns
from scipy import stats
from scipy.stats import norm, chi2
from scipy.special import betainc


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def pvalue_to_sigmoid(p_values):
    if not (0 < p_values <= 1):
        raise ValueError("p must be in the range (0, 1]")

    log_value = -np.log10(p_values)
    return sigmoid(log_value)

def sum_log_p_values(p_values):
    """Sum the negative logarithms of the p-values."""
    p_values = np.asarray(p_values)
    return -np.sum(np.log(p_values))



def stouffer_s_z_score(p_values, threshold=1e-5, raw_weights = None, prob_score = False):
    """
     Applies Stouffer's Z_Score to a list of p-values.
        0. Calculate raw weights based on proximity to p_value threshold Inverse of the ratio (p-value / threshold), higher for p-values close to the threshold
        1. Convert p-values to z-scores
        2. Calculate the weighted
        3. Convert combined Z-score back to a p-value

    Parameters:
    -----------
    p_values : list or numpy array
        List of p-values from the different enrichment tests.
    weights : list or numpy array ie individual importance assigned to each rule
        eg. how close each of them is to the significance threshold (e.g., 1e-5).

    Returns:
    --------
    float
        Combined p-value according to Stouffer's Z_Score.
    """
    p_values = np.array(p_values)
    p_values = np.clip(p_values, 1e-15, None)

    if not raw_weights:
        raw_weights = threshold / p_values

    # Then normalize the weights to sum to 1
    weights = raw_weights / np.sum(raw_weights)

    z_scores = norm.ppf(1 - np.array(p_values))
    combined_z = np.sum(weights * z_scores) / np.sqrt(np.sum(weights ** 2))
    if prob_score:
    #     # To return score as probability
        combined_p = norm.sf(combined_z)
        return combined_p
    return combined_z


def simes_method(p_values, alpha):
    """
    Applies Simes' method to a list of p-values.
      Sort p-values in ascending order
      Get the number of p-values (n)
      Apply Simes' condition: p(i) <= (i / n) * alpha
      Find the largest index where p(i) <= (i/n) * alpha
      Return the corresponding p-value
            If no p-value satisfies the condition,
                return the smallest p-value
                    else
                return the p-value for the smallest satisfying condition

    Params:
    -----------
    p_values : list or numpy array
        List of p-values from the different enrichment tests.
    alpha : float
        Significance threshold (e.g., 0.05).

    Returns:
    --------
    float
        Combined p-value according to Simes' method.
    """
    p_values = np.array(p_values)
    p_values_sorted = np.sort(p_values)
    n = len(p_values_sorted)
    thresholds = (np.arange(1, n + 1) / n) * alpha

    for i in range(n):
        if p_values_sorted[i] > thresholds[i]:
            break

    if i == 0:
        return p_values_sorted[0]
    else:
        return p_values_sorted[:i].mean()


def wfisher( pvalues, sample_sizes ):
    n = len(pvalues)
    total_sample_size = sum(sample_sizes)
    weights = [n * s / total_sample_size for s in sample_sizes]

    transformed = [stats.gamma.ppf(1 - p, a=w, scale=2) for p, w in zip(pvalues, weights)]
    test_statistic = sum(transformed)

    combined_pvalue = 1 - stats.gamma.cdf(test_statistic, a=n, scale=2)
    return combined_pvalue

def fisher_method_multiple(p_list):
    X2 = -2 * sum(np.log(p) for p in p_list)
    df = 2 * len(p_list)
    return 1 - chi2.cdf(X2, df=df)


def ordmeta(pvalues ):
    n = len(pvalues)
    sorted_pvalues = sorted(pvalues)

    marginal_pvalues = [1 - betainc(i, n - i + 1, p) for i, p in enumerate(sorted_pvalues, 1)]
    min_marginal = min(marginal_pvalues)

    combined_pvalue = 1 - (1 - min_marginal) ** n
    return combined_pvalue


def convert_ndarray_to_list(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_ndarray_to_list(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_ndarray_to_list(element) for element in obj]
    else:
        return obj