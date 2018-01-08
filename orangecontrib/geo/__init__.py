from os.path import join, dirname
from Orange.data.table import dataset_dirs
dataset_dirs.insert(0, join(dirname(__file__), "datasets"))
del join, dirname, dataset_dirs
