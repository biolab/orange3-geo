from os.path import join, dirname
from Orange.data.table import dataset_dirs
from Orange.data import Table


dataset_dirs.insert(0, join(dirname(__file__), "datasets"))
del join, dirname, dataset_dirs


# Remove this when we require Orange 3.34
if not hasattr(Table, "get_column"):
    import scipy.sparse as sp
    import numpy as np

    def get_column(self, column):
        col, _ = self.get_column_view(column)
        if sp.issparse(col):
            col = col.toarray().reshape(-1)
        if self.domain[column].is_primitive():
            col = col.astype(np.float64)
        return col

    Table.get_column = get_column
