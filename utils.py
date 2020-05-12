#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import torch
import numpy as np

def nanmean(v, *args, **kwargs):
    """
    A Pytorch version on Numpy's nanmean
    """
    v = v.clone()
    is_nan = torch.isnan(v)
    v[is_nan] = 0
    return v.sum(*args, **kwargs) / (~is_nan).float().sum(*args, **kwargs)


#### Quantile ######
def quantile(X, q, dim=None):
    """
    Returns the q-th quantile.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Input data.

    q : float
        Quantile level (starting from lower values).

    dim : int or None, default = None
        Dimension allong which to compute quantiles. If None, the tensor is flattened and one value is returned.


    Returns
    -------
        quantiles : torch.DoubleTensor

    """
    return X.kthvalue(int(q * len(X)), dim=dim)[0]


#### Automatic selection of the regularization parameter ####
def pick_epsilon(X, quant=0.5, mult=0.05, max_points=2000):
    """
        Returns a quantile (times a multiplier) of the halved pairwise squared distances in X.
        Used to select a regularization parameter for Sinkhorn distances.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Input data on which distances will be computed.

    quant : float, default = 0.5
        Quantile to return (default is median).

    mult : float, default = 0.05
        Mutiplier to apply to the quantiles.

    max_points : int, default = 2000
        If the length of X is larger than max_points, estimate the quantile on a random subset of size max_points to
        avoid memory overloads.

    Returns
    -------
        epsilon: float

    """
    means = nanmean(X, 0)
    X_ = X.clone()
    mask = torch.isnan(X_)
    X_[mask] = (mask * means)[mask]

    idx = np.random.choice(len(X_), min(max_points, len(X_)), replace=False)
    X = X_[idx]
    dists = ((X[:, None] - X) ** 2).sum(2).flatten() / 2.
    dists = dists[dists > 0]

    return quantile(dists, quant, 0).item() * mult


#### Accuracy Metrics ####
def MAE(X, X_true, mask):
    """
    Mean Absolute Error (MAE) between imputed variables and ground truth. Pytorch/Numpy agnostic
    
    Parameters
    ----------
    X : torch.DoubleTensor or np.ndarray, shape (n, d)
        Data with imputed variables.

    X_true : torch.DoubleTensor or np.ndarray, shape (n, d)
        Ground truth.

    mask : torch.BoolTensor or np.ndarray of booleans, shape (n, d)
        Missing value mask (missing if True)

    Returns
    -------
        MAE : float

    """
    if torch.is_tensor(mask):
        mask_ = mask.bool()
        return torch.abs(X[mask_] - X_true[mask_]).sum() / mask_.sum()
    else: # should be an ndarray
        mask_ = mask.astype(bool)
        return np.absolute(X[mask_] - X_true[mask_]).sum() / mask_.sum()



def RMSE(X, X_true, mask):
    """
    Root Mean Squared Error (MAE) between imputed variables and ground truth. Pytorch/Numpy agnostic

    Parameters
    ----------
    X : torch.DoubleTensor or np.ndarray, shape (n, d)
        Data with imputed variables.

    X_true : torch.DoubleTensor or np.ndarray, shape (n, d)
        Ground truth.

    mask : torch.BoolTensor or np.ndarray of booleans, shape (n, d)
        Missing value mask (missing if True)

    Returns
    -------
        RMSE : float

    """
    if torch.is_tensor(mask):
        mask_ = mask.bool()
        return (((X[mask_] - X_true[mask_]) ** 2).sum() / mask_.sum()).sqrt()
    else: # should be an ndarray
        mask_ = mask.astype(bool)
        return np.sqrt(((X[mask_] - X_true[mask_])**2).sum() / mask_.sum())

##################### MISSING DATA MECHANISMS #############################

##### Missing At Random ######

def MAR_mask(X, p, p_obs):
    """
    Missing at random mechanism with a logistic masking model. First, a subset of variables with *no* missing values is
    randomly selected. The remaining variables have missing values according to a logistic model with random weights,
    re-scaled so as to attain the desired proportion of missing values on those variables.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Data for which missing values will be simulated.

    p : float
        Proportion of missing values to generate for variables which will have missing values.

    p_obs : float
        Proportion of variables with *no* missing values that will be used for the logistic masking model.

    Returns
    -------
    mask : torch.BoolTensor or torch.cuda.BoolTensor, shape (n, d)
        Mask of generated missing values (True if the value is missing).

    """

    n, d = X.shape
    mask = torch.zeros(n, d).bool()

    d_obs = max(int(p_obs * d), 1) ## number of variables that will have no missing values (at least one variable)
    d_na = d - d_obs ## number of variables that will have missing values

    ### Sample variables that will all be observed, and those with missing values:
    idxs_obs = np.random.choice(d, d_obs, replace=False)
    idxs_nas = np.array([i for i in range(d) if i not in idxs_obs])

    ### Other variables will have NA proportions that depend on those observed variables, through a logistic model
    ### The parameters of this logistic model are random.

    coeffs = torch.randn((d_obs, d_na))
    intercepts = torch.randn(d_na)

    ps = torch.sigmoid(X[:, idxs_obs].mm(coeffs) + intercepts)
    ### Rescale to have a desired amount of missing values
    ps /= (ps.mean(0) / p)

    ber = torch.rand(n, d_na)
    mask[:, idxs_nas] = ber < ps

    return mask

##### Missing not at random ######

def MNAR_mask_logistic(X, p, p_params):
    """
    Missing not at random mechanism with a logistic masking model. First, a subset of variables is randomly selected to
    be used as inputs in a logistic masking mechanism. The remaining variables have missing values according to a
    logistic model with random weights, re-scaled so as to attain the desired proportion of missing values on those
    variables, as in the MAR mechanism. The difference is that the input variables are then masked with a MCAR
    mechanism, which makes part of the missingness effectively dependent on unobserved variables.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Data for which missing values will be simulated.

    p : float
        Proportion of missing values to generate for variables which will have missing values.

    p_params : float
        Proportion of variables that will be used for the logistic masking model.

    Returns
    -------
    mask : torch.BoolTensor or torch.cuda.BoolTensor, shape (n, d)
        Mask of generated missing values (True if the value is missing).

    """

    n, d = X.shape
    mask = torch.zeros(n, d).bool()

    d_params = max(int(p_params * d), 1) ## number of variables used as inputs
    d_na = d - d_params ## number of variables masked with the logistic model

    ### Sample variables that will be parameters for the logistic regression:
    idxs_params = np.random.choice(d, d_params, replace=False) ### select at least one variable
    idxs_nas = np.array([i for i in range(d) if i not in idxs_params])

    ### Other variables will have NA proportions that depend on those observed variables, through a logistic model
    ### The parameters of this logistic model are random.
    coeffs = torch.randn((d_params, d_na))
    intercepts = torch.randn(d_na)

    ps = torch.sigmoid(X[:, idxs_params].mm(coeffs) + intercepts)
    ### Rescale to have a desired amount of missing values
    ps /= (ps.mean(0) / p)

    ber = torch.rand(n, d_na)
    mask[:, idxs_nas] = ber < ps

    ## Now, mask some values used in the logistic model at random
    ## This makes the missingness of other variables potentially dependent on masked values
    mask[:, idxs_params] = torch.rand(n, d_params) < p

    return mask

def MNAR_self_mask_logistic(X, p):
    """
    Missing not at random mechanism with a logistic self-masking model. All variables have missing values according to a
    logistic model on *all* variables with random weights, re-scaled so as to attain the desired proportion of missing
    values. Since missingness depends on all variables, it will depend on unobserved values as well.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Data for which missing values will be simulated.

    p : float
        Proportion of missing values to generate for variables which will have missing values.

    Returns
    -------
    mask : torch.BoolTensor or torch.cuda.BoolTensor, shape (n, d)
        Mask of generated missing values (True if the value is missing).

    """

    n, d = X.shape
    mask = torch.zeros(n, d).bool()

    ### Other variables will have NA proportions that depend on those observed variables, through a logistic model
    ### The parameters of this logistic model are random.
    coeffs = torch.randn((d, d))
    intercepts = torch.randn(d)

    ps = torch.sigmoid(X.mm(coeffs) + intercepts)
    ### Rescale to have a desired amount of missing values
    ps /= (ps.mean(0) / p)

    ber = torch.rand(n, d)
    mask = ber < ps

    return mask


def MNAR_mask_quantiles(X, p, q, p_params, cut='both', MCAR=False):
    """
    Missing not at random mechanism with quantile censorship. First, a subset of variables which will have missing
    variables is randomly selected. Then, missing values are generated on the q-quantiles at random. Since
    missingness depends on quantile information, it depends on masked values, hence this is a MNAR mechanism.

    Parameters
    ----------
    X : torch.DoubleTensor or torch.cuda.DoubleTensor, shape (n, d)
        Data for which missing values will be simulated.

    p : float
        Proportion of missing values to generate for variables which will have missing values.

    q : float
        Quantile level at which the cuts should occur

    p_params : float
        Proportion of variables that will have missing values

    cut : 'both', 'upper' or 'lower', default = 'both'
        Where the cut should be applied. For instance, if q=0.25 and cut='upper', then missing values will be generated
        in the upper quartiles of selected variables.
        
    MCAR : bool, default = True
        If true, masks variables that were not selected for quantile censorship with a MCAR mechanism.
        
    Returns
    -------
    mask : torch.BoolTensor or torch.cuda.BoolTensor, shape (n, d)
        Mask of generated missing values (True if the value is missing).

    """
    n, d = X.shape

    mask = torch.zeros(n, d).bool()

    d_na = max(int(p_params * d), 1) ## number of variables that will have NMAR values

    ### Sample variables that will have imps at the extremes
    idxs_na = np.random.choice(d, d_na, replace=False) ### select at least one variable with missing values

    ### check if values are greater/smaller that corresponding quantiles
    if cut == 'upper':
        quants = quantile(X[:, idxs_na], q, dim=0)
        m = X[:, idxs_na] >= quants
    elif cut == 'lower':
        quants = quantile(X[:, idxs_na], 1-q, dim=0)
        m = X[:, idxs_na] <= quants
    elif cut == 'both':
        l_quants = quantile(X[:, idxs_na], 1-q, dim=0)
        u_quants = quantile(X[:, idxs_na], q, dim=0)
        m = (X[:, idxs_na] <= l_quants) | (X[:, idxs_na] >= u_quants)

    ### Hide some values exceeding quantiles
    ber = torch.rand(n, d_na)
    mask[:, idxs_na] = (ber < p) & m

    if MCAR:
    ## Add a mcar mecanism on top
        mask = mask | (torch.rand(n, d) < p)

    return mask
