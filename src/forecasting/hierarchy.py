"""Top-down allocation: family forecast x SKU share of the family over trailing history."""
import numpy as np



def allocate_by_share(fam_fc, fam_index, sku_index, sku_family, sku_hist):
    fam_of = np.array([fam_index[sku_family[s]] for s in sku_index])
    out = np.zeros(len(sku_index))

    for j in range(len(sku_index)):
        members = fam_of == fam_of[j]
        family_hist_total = sku_hist[members].sum()

        if family_hist_total > 0:
            share = sku_hist[j] / family_hist_total
        else:
            share = 1.0 / members.sum()

        out[j] = fam_fc[fam_of[j]] * share

    return out
