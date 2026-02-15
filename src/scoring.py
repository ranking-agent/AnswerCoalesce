import numpy as np


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def modified_sigmoid(x, scale=1, shift=0):
    return sigmoid(scale * (x - shift))


def pvalue_to_sigmoid(p_values, scale=0.5, shift=5):
    p_values = np.atleast_1d(p_values)
    log_value = -np.log10(p_values)
    result = np.round(modified_sigmoid(log_value, scale=scale, shift=shift), 5)
    return result[0] if result.size == 1 else result


def harmonic_mean(weights):
    hmp = np.sum(weights) / np.sum(weights / weights)
    return float(hmp)


def geometric_mean(weights):
    return np.prod(weights) ** (1 / len(weights))


def elrond(weights):
    """"
        # Graph: 2 nodes (source=Gene A, target=Disease X)
        n_nodes = 2

        # Step 1 & 2: Build adjacency matrix by summing conductances
        # Each p-value is a parallel edge between source and target
        A = np.zeros((n_nodes, n_nodes))

        for p in weights:
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
    """
    weights = np.minimum(weights, 0.99999)
    conductances = -1 / np.log(weights)
    total_conductance = np.sum(conductances)
    kirchhoff = 1 / total_conductance
    combined_pvalue = np.exp(-kirchhoff)

    return float(combined_pvalue)


def score_inference(pvalues, method='elrond'):
    """
    Combine p-values into a score.
    """
    weights = np.atleast_1d(pvalue_to_sigmoid(pvalues))

    if method == "elrond":
        return elrond(weights)
    elif method == 'harmonic':
        return harmonic_mean(weights)
    else:
        return geometric_mean(weights)