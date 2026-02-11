import numpy as np
from scipy import stats
from scipy.stats import norm, chi2
from scipy.special import gammaincc


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def modified_sigmoid(x, scale=1, shift=0):
    return sigmoid(scale * (x - shift))


def pvalue_to_sigmoid(p_values, scale=0.5, shift=5):
    p_values = np.atleast_1d(p_values)
    p_values = np.clip(p_values, 1e-300, 1.0)
    log_value = -np.log10(p_values)
    result = np.round(modified_sigmoid(log_value, scale=scale, shift=shift), 6)
    return result[0] if result.size == 1 else result


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
    return sigmoid(combined_z/len(p_values))


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
    return pvalue_to_sigmoid(combined_pvalue)


def fisher_method_multiple(p_list):
    X2 = -2 * np.sum(np.log(p_list))
    df = 2 * len(p_list)
    return gammaincc(df / 2, X2 / 2)


def harmonic_mean(pvalues, weights=None):
    pvalues = np.array(pvalues, dtype=float)
    pvalues = np.clip(pvalues, 1e-300, 1.0)

    if weights is None:
        # Unweighted
        n = len(pvalues)
        hmp = n / np.sum(1.0 / pvalues)
    else:
        # Weighted
        weights = np.array(weights, dtype=float)
        hmp = np.sum(weights) / np.sum(weights / pvalues)

    return float(hmp)


def geometric_mean(pvalues):
    return np.prod(pvalues) ** (1 / len(pvalues))


def elrond_pvalue_combination(pvalues, paper=False, paper_equivalence=False):
    pvalues = np.array(pvalues, dtype=float)
    pvalues = np.clip(pvalues, 1e-300, 1e-5)

    if len(pvalues) == 1:
        return float(pvalues[0])

    if paper:
        # Graph: 2 nodes (source=Gene A, target=Disease X)
        n_nodes = 2

        # Step 1 & 2: Build adjacency matrix by summing conductances
        # Each p-value is a parallel edge between source and target
        A = np.zeros((n_nodes, n_nodes))

        for p in pvalues:
            # Resistance from p-value (weight)
            R = -np.log(p)

            # Conductance (inverse of resistance)
            conductance = 1 / R

            # Sum conductances for parallel edges
            A[0, 1] += conductance
            A[1, 0] += conductance  # Symmetric

        # Step 3: Build Laplacian L = D - A
        D = np.diag(np.sum(A, axis=1))
        L = D - A

        # Step 4: Calculate Kirchhoff index with pseudoinverse method
        L_pseudo = pinv(L)

        # Difference vector for nodes 0 and 1
        e_diff = np.array([1, -1])

        # Kirchhoff index: Ω = e_diff^T L^+ e_diff
        kirchhoff = e_diff.T @ L_pseudo @ e_diff

        # Step 5: Inverse mapping f^(-1)(Ω) = e^(-Ω)
        combined_pvalue = np.exp(-kirchhoff)

    elif paper_equivalence:
        conductances = -1 / np.log(pvalues)
        total_conductance = np.sum(conductances)
        kirchhoff = 1 / total_conductance
        combined_pvalue = np.exp(-kirchhoff)

    else:
        conductances = - np.log(pvalues)
        total_conductance = np.sum(conductances)
        kirchhoff = total_conductance ** 1 / len(pvalues)
        combined_pvalue = np.exp(-kirchhoff)

    return float(combined_pvalue)


def stouffers_method( pvalues, weights=None ):
    pvalues = np.array(pvalues, dtype=float)
    pvalues = np.clip(pvalues, 1e-300, 1 - 1e-10)

    z_scores = norm.ppf(1 - pvalues)
    z_scores = np.clip(z_scores, -10, 10)

    if weights is None:
        # Unweighted - standard Stouffer
        combined_z = np.sum(z_scores) / np.sqrt(len(z_scores))
    else:
        # Weighted - simple weighted average (no sqrt penalty!)
        weights = np.array(weights, dtype=float)
        combined_z = np.average(z_scores, weights=weights)

    combined_pvalue = 1 - norm.cdf(combined_z)
    return max(float(combined_pvalue), 1e-300)


def fishers_method( pvalues ):
    pvalues = np.array(pvalues, dtype=float)
    pvalues = np.clip(pvalues, 1e-300, 1.0)
    chi2_stat = -2 * np.sum(np.log(pvalues))
    combined_pvalue = chi2.sf(chi2_stat, 2 * len(pvalues))
    return max(float(combined_pvalue), 1e-300)


def combine_rule_pvalues_to_score( pvalues_list, weights=None, method='geometric' ):
    """
    Combine p-values into a score.

    Args:
        pvalues_list: List of p-values
        weights: Optional list of weights (e.g., support sizes). Only used for 'harmonic' and 'stouffer'.
        method: 'harmonic', 'stouffer', or 'fisher'
    """
    SIGMOID_SCALE = 0.5
    SIGMOID_SHIFT = 5
    pvalues = np.array(pvalues_list, dtype=float)

    if len(pvalues) == 1:
        combined_pvalue = float(pvalues[0])
        combined_score = float(pvalue_to_sigmoid(combined_pvalue, scale=SIGMOID_SCALE, shift=SIGMOID_SHIFT))
        return {
            'combined_pvalue': combined_pvalue,
            'combined_score': combined_score,
            'method': 'single_rule',
            'individual_scores': [combined_score],
            'weights': weights if weights is not None else None
        }

    # Combine p-values
    if method == 'harmonic':
        combined_pvalue = harmonic_mean(pvalues, weights)
    elif method == "elrond":
        combined_pvalue = elrond_pvalue_combination(pvalues, weights)
    elif method == 'stouffer':
        combined_pvalue = stouffers_method(pvalues, weights)
    elif method == 'fisher':
        combined_pvalue = fishers_method(pvalues)
    else:
        combined_pvalue = geometric_mean(pvalues)

    combined_score = float(pvalue_to_sigmoid(combined_pvalue, scale=SIGMOID_SCALE, shift=SIGMOID_SHIFT))
    individual_scores = [float(s) for s in pvalue_to_sigmoid(pvalues, scale=SIGMOID_SCALE, shift=SIGMOID_SHIFT)]

    # Combined score should never be worse than the best individual rule
    # best_individual_score = max(individual_scores)
    # if combined_score < best_individual_score:
    #     combined_score = best_individual_score
    #     combined_pvalue = float(min(pvalues))
    #     method = f"{method}_capped_at_best"

    return {
        'combined_pvalue': combined_pvalue,
        'combined_score': combined_score,
        'method': method,
        'individual_scores': individual_scores,
        'weights': list(weights) if weights is not None else None
    }