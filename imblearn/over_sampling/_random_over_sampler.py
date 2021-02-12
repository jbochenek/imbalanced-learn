﻿"""Class to perform random over-sampling."""

# Authors: Guillaume Lemaitre <g.lemaitre58@gmail.com>
#          Christos Aridas
# License: MIT

from numbers import Real

import numpy as np
from scipy import sparse
from sklearn.utils import check_array, check_random_state
from sklearn.utils import _safe_indexing
from sklearn.utils.sparsefuncs import mean_variance_axis

from .base import BaseOverSampler
from ..utils import check_target_type
from ..utils import Substitution
from ..utils._docstring import _random_state_docstring
from ..utils._validation import _deprecate_positional_args


@Substitution(
    sampling_strategy=BaseOverSampler._sampling_strategy_docstring,
    random_state=_random_state_docstring,
)
class RandomOverSampler(BaseOverSampler):
    """Class to perform random over-sampling.

    Object to over-sample the minority class(es) by picking samples at random
    with replacement. The bootstrap can be generated in a smoothed manner.

    Read more in the :ref:`User Guide <random_over_sampler>`.

    Parameters
    ----------
    {sampling_strategy}

    {random_state}

    smoothed_bootstrap : bool, default=False
        Whether or not to generate smoothed bootstrap samples. When this option
        is triggered, be aware that the data to be resampled needs to be
        numerical data since a Gaussian perturbation will be generated and
        added to the bootstrap.

        .. versionadded:: 0.7

    shrinkage : float or dict, default=1.0
        Factor to shrink the covariance matrix used to generate the
        smoothed bootstrap. A factor could be shared by all classes by
        providing a floating number or different for each class over-sampled
        by providing a dictionary where the key are the class targeted and the
        value is the shrinkage factor.

        .. versionadded:: 0.7

    Attributes
    ----------
    sample_indices_ : ndarray of shape (n_new_samples,)
        Indices of the samples selected.

        .. versionadded:: 0.4

    shrinkage_ : dict or None
        The per-class shrinkage factor used to generate the smoothed bootstrap
        sample. `None` when `smoothed_bootstrap=False`.

        .. versionadded:: 0.7

    See Also
    --------
    BorderlineSMOTE : Over-sample using the borderline-SMOTE variant.

    SMOTE : Over-sample using SMOTE.

    SMOTENC : Over-sample using SMOTE for continuous and categorical features.

    SVMSMOTE : Over-sample using SVM-SMOTE variant.

    ADASYN : Over-sample using ADASYN.

    KMeansSMOTE : Over-sample applying a clustering before to oversample using
        SMOTE.

    Notes
    -----
    Supports multi-class resampling by sampling each class independently.
    Supports heterogeneous data as object array containing string and numeric
    data.

    When generating a smoothed bootstrap, this method is also known as Random
    Over-Sampling Examples (ROSE) [1]_.

    .. warning::
       Since smoothed bootstrap are generated by adding a small perturbation
       to the drawn samples, this method is not adequate when working with
       sparse matrices.

    References
    ----------
    .. [1] G Menardi, N. Torelli, "Training and assessing classification
       rules with imbalanced data," Data Mining and Knowledge
       Discovery, 28(1), pp.92-122, 2014.

    Examples
    --------
    >>> from collections import Counter
    >>> from sklearn.datasets import make_classification
    >>> from imblearn.over_sampling import \
RandomOverSampler # doctest: +NORMALIZE_WHITESPACE
    >>> X, y = make_classification(n_classes=2, class_sep=2,
    ... weights=[0.1, 0.9], n_informative=3, n_redundant=1, flip_y=0,
    ... n_features=20, n_clusters_per_class=1, n_samples=1000, random_state=10)
    >>> print('Original dataset shape %s' % Counter(y))
    Original dataset shape Counter({{1: 900, 0: 100}})
    >>> ros = RandomOverSampler(random_state=42)
    >>> X_res, y_res = ros.fit_resample(X, y)
    >>> print('Resampled dataset shape %s' % Counter(y_res))
    Resampled dataset shape Counter({{0: 900, 1: 900}})
    """

    @_deprecate_positional_args
    def __init__(
        self,
        *,
        sampling_strategy="auto",
        random_state=None,
        smoothed_bootstrap=False,
        shrinkage=1.0,
    ):
        super().__init__(sampling_strategy=sampling_strategy)
        self.random_state = random_state
        self.smoothed_bootstrap = smoothed_bootstrap
        self.shrinkage = shrinkage

    def _check_X_y(self, X, y):
        y, binarize_y = check_target_type(y, indicate_one_vs_all=True)
        X, y = self._validate_data(
            X,
            y,
            reset=True,
            accept_sparse=["csr", "csc"],
            dtype=None,
            force_all_finite=False,
        )
        return X, y, binarize_y

    def _fit_resample(self, X, y):
        random_state = check_random_state(self.random_state)

        if self.smoothed_bootstrap:
            if isinstance(self.shrinkage, Real):
                self.shrinkage_ = {
                    klass: self.shrinkage for klass in self.sampling_strategy_
                }
            else:
                missing_shrinkage_keys = (
                    self.sampling_strategy_.keys() - self.shrinkage.keys()
                )
                if missing_shrinkage_keys:
                    raise ValueError(
                        f"`shrinkage` should contain a shrinkage factor for "
                        f"each class that will be resampled. The missing "
                        f"classes are: {repr(missing_shrinkage_keys)}"
                    )
                self.shrinkage_ = self.shrinkage
            # smoothed bootstrap imposes to make numerical operation; we need
            # to be sure to have only numerical data in X
            try:
                X = check_array(X, accept_sparse=["csr", "csc"], dtype="numeric")
            except ValueError as exc:
                raise ValueError(
                    "When smoothed_bootstrap=True, X needs to contain only "
                    "numerical data to later generate a smoothed bootstrap "
                    "sample."
                ) from exc
        else:
            self.shrinkage_ = None

        X_resampled = [X.copy()]
        y_resampled = [y.copy()]

        sample_indices = range(X.shape[0])
        for class_sample, num_samples in self.sampling_strategy_.items():
            target_class_indices = np.flatnonzero(y == class_sample)
            bootstrap_indices = random_state.choice(
                target_class_indices,
                size=num_samples,
                replace=True,
            )
            sample_indices = np.append(sample_indices, bootstrap_indices)
            if self.smoothed_bootstrap:
                # generate a smoothed bootstrap with a perturbation
                n_samples, n_features = X.shape
                smoothing_constant = (4 / ((n_features + 2) * n_samples)) ** (
                    1 / (n_features + 4)
                )
                if sparse.issparse(X):
                    _, X_class_variance = mean_variance_axis(
                        X[target_class_indices, :],
                        axis=0,
                    )
                    X_class_scale = np.sqrt(X_class_variance, out=X_class_variance)
                else:
                    X_class_scale = np.std(X[target_class_indices, :], axis=0)
                smoothing_matrix = np.diagflat(
                    self.shrinkage_[class_sample] * smoothing_constant * X_class_scale
                )
                X_new = random_state.randn(num_samples, n_features)
                X_new = X_new.dot(smoothing_matrix) + X[bootstrap_indices, :]
                if sparse.issparse(X):
                    X_new = sparse.csr_matrix(X_new, dtype=X.dtype)
                X_resampled.append(X_new)
            else:
                # generate a bootstrap
                X_resampled.append(_safe_indexing(X, bootstrap_indices))

            y_resampled.append(_safe_indexing(y, bootstrap_indices))

        self.sample_indices_ = np.array(sample_indices)

        if sparse.issparse(X):
            X_resampled = sparse.vstack(X_resampled, format=X.format)
        else:
            X_resampled = np.vstack(X_resampled)
        y_resampled = np.hstack(y_resampled)

        return X_resampled, y_resampled

    def _more_tags(self):
        return {
            "X_types": ["2darray", "string"],
            "sample_indices": True,
            "allow_nan": True,
        }
