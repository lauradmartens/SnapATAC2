import snapatac2_scooby as snap

import numpy as np
import anndata as ad
import pandas as pd
from pathlib import Path
from natsort import natsorted
from collections import defaultdict
import pytest
from hypothesis import given, settings, HealthCheck, strategies as st
from hypothesis.extra.numpy import *
from scipy.sparse import csr_matrix
import gzip

from distutils import dir_util
from pytest import fixture
import os

@fixture
def datadir(tmpdir, request):
    '''
    Fixture responsible for searching a folder with the same name of test
    module and, if available, moving all contents to a temporary directory so
    tests can use them freely.
    '''
    filename = request.module.__file__
    test_dir, _ = os.path.splitext(filename)

    if os.path.isdir(test_dir):
        dir_util.copy_tree(test_dir, str(tmpdir))

    return tmpdir

def h5ad(dir=Path("./")):
    import uuid
    dir.mkdir(exist_ok=True)
    return str(dir / Path(str(uuid.uuid4()) + ".h5ad"))


@given(
    x = arrays(integer_dtypes(endianness='='), (500, 50)),
    groups = st.lists(st.integers(min_value=0, max_value=5), min_size=500, max_size=500),
    var = st.lists(st.integers(min_value=0, max_value=100000), min_size=50, max_size=50),
)
@settings(max_examples=10, deadline=None, suppress_health_check = [HealthCheck.function_scoped_fixture])
def test_aggregation(x, groups, var, tmp_path):
    def assert_equal(a, b):
        assert a.keys() == b.keys()
        np.testing.assert_array_equal(
            np.array(list(a.values())),
            np.array(list(b.values())),
        )

    groups = [str(g) for g in groups]
    obs_names = [str(i) for i in range(len(groups))]
    var_names = [str(i) for i in range(len(var))]
    adata = snap.AnnData(
        X=x,
        obs = dict(ident=obs_names, groups=groups),
        var = dict(ident=var_names, txt=var),
        filename = h5ad(tmp_path),
    )

    expected = defaultdict(list)
    for g, v in zip(groups, list(x)):
        expected[g].append(v)
    for k in expected.keys():
        expected[k] = np.array(expected[k], dtype="float64").sum(axis = 0)
    expected = dict(natsorted(expected.items()))

    np.testing.assert_array_equal(
        x.sum(axis=0),
        snap.tl.aggregate_X(adata),
    )
    np.testing.assert_array_equal(
        np.array(list(expected.values())),
        snap.tl.aggregate_X(adata, file = h5ad(tmp_path), groupby=groups).X[:],
    )


def test_make_fragment(datadir, tmp_path):
    bam = str(datadir.join('test.bam'))
    bed = str(datadir.join('test.bed.gz'))
    output = str(tmp_path) + "/out.bed.gz"
    snap.pp.make_fragment_file(bam, output, True, barcode_regex="(^[ATCG]+):", chunk_size=5000)

    with gzip.open(bed, 'rt') as fl:
        expected = sorted(fl.readlines())

    with gzip.open(output, 'rt') as fl:
        actual = sorted(fl.readlines())
    
    assert expected == actual

@given(
    mat = arrays(
        np.float64, (50, 100),
        elements = {"allow_subnormal": False, "allow_nan": False, "allow_infinity": False, "min_value": 1, "max_value": 100},
    ),
)
@settings(deadline = None, suppress_health_check = [HealthCheck.function_scoped_fixture])
def test_reproducibility(mat):
    adata = ad.AnnData(X=csr_matrix(mat))
    embeddings = []
    for _ in range(3):
        embeddings.append(snap.tl.spectral(adata, features=None, random_state=0, inplace=False)[1])
    for x in embeddings:
        np.testing.assert_array_equal(x, embeddings[0])

    snap.tl.spectral(adata, features=None, random_state=0)
    knn = []
    for _ in range(3):
        knn.append(snap.pp.knn(adata, random_state=0, n_neighbors=25, inplace=False).todense())
    for x in knn:
        np.testing.assert_array_equal(x, knn[0])

    snap.pp.knn(adata, random_state=0, n_neighbors=25)
    leiden = []
    for _ in range(3):
        leiden.append(snap.tl.leiden(adata, random_state=0, resolution=1, n_iterations=10, inplace=False))
    for x in leiden:
        np.testing.assert_array_equal(x, leiden[0])

def read_bed(bed_file):
    with gzip.open(bed_file, 'rt') as f:
        return sorted([line.strip().split('\t')[:4] for line in f if line.startswith('chr')])

def test_import(datadir):
    test_files = [snap.datasets.pbmc500(downsample=True), str(datadir.join('test_clean.tsv.gz'))]

    for fl in test_files:
        data = snap.pp.import_fragments(
            fl,
            chrom_sizes=snap.genome.hg38,
            min_num_fragments=0,
            sorted_by_barcode=False,
        )

        data.obs['group'] = 'test_import'
        outputs = snap.ex.export_fragments(data, groupby="group", out_dir=str(datadir), suffix='.bed.gz')

        assert read_bed(list(outputs.values())[0]) == read_bed(fl)

def test_tile_matrix(datadir):
    def total_count(adata, bin_size):
        return snap.pp.add_tile_matrix(
            adata,
            bin_size=bin_size,
            inplace=False,
            counting_strategy='insertion',
            ).X.sum()

    data = snap.pp.import_fragments(
        snap.datasets.pbmc500(downsample=True),
        chrom_sizes=snap.genome.hg38,
        min_num_fragments=0,
        sorted_by_barcode=False,
    )

    counts = [total_count(data, i) for i in [500, 1000, 5000, 10000]]
    for i in range(1, len(counts)):
        assert counts[i] == counts[i - 1], f"Bin size {i} failed"

def test_rna_xf_filter_fragments(datadir, tmp_path):
    bam = str(datadir.join('test_stranded.bam'))
    bed = str(datadir.join('test_unstranded.bed.gz'))
    output = str(tmp_path) + "/out.bed.gz"

    snap.pp.make_fragment_file(
    bam_file=bam,
    output_file=str(tmp_path) + "/out.bed.gz",
    barcode_tag="CB",
    umi_tag="UB",
    umi_regex=None,
    stranded=False,
    is_paired=False,
    shift_left=0,
    shift_right=0,
    xf_filter=True
)
    with gzip.open(bed, 'rt') as fl:
        expected = sorted(fl.readlines())

    with gzip.open(output, 'rt') as fl:
        actual = sorted(fl.readlines())
    
    assert expected == actual

def test_stranded_fragment_file(datadir, tmp_path):
    bam = str(datadir.join('test_stranded.bam'))
    bed_plus = str(datadir.join('test_stranded.bed.plus.gz'))
    bed_minus = str(datadir.join('test_stranded.bed.minus.gz'))
    output_plus = str(tmp_path) + "/out.bed.plus.gz"
    output_minus = str(tmp_path) + "/out.bed.minus.gz"

    snap.pp.make_fragment_file(
    bam_file=bam,
    output_file=str(tmp_path) + "/out.bed.gz",
    barcode_tag="CB",
    umi_tag="UB",
    umi_regex=None,
    stranded=True,
    is_paired=False,
    shift_left=0,
    shift_right=0,
    xf_filter=True
)

    with gzip.open(bed_plus, 'rt') as fl:
        expected = sorted(fl.readlines())

    with gzip.open(output_plus, 'rt') as fl:
        actual = sorted(fl.readlines())
    
    assert expected == actual

    with gzip.open(bed_minus, 'rt') as fl:
        expected = sorted(fl.readlines())

    with gzip.open(output_minus, 'rt') as fl:
        actual = sorted(fl.readlines())

    assert expected == actual

# def test_export_coverage(datadir, tmp_path):
#     ad_minus = ad.read_h5ad(str(datadir.join('test_minus.h5ad')))
#     ad_plus = ad.read_h5ad(str(datadir.join('test_plus.h5ad')))

#     import pybigtools
#     bw_plus = pybigtools.open(str(datadir.join('test_plus.bw')))
#     bw_minus = pybigtools.open(str(datadir.join('test_minus.bw')))

#     snap.ex.export_coverage(
#     ad_minus,
#     groupby='group',
#     bin_size=1,
#     normalization=None,
#     n_jobs=-1,
#     max_frag_length=None,
#     suffix='.bw',
#     prefix=f"{str(tmp_path)}/minus."
# )
    
#     snap.ex.export_coverage(
#     ad_plus,
#     groupby='group',
#     bin_size=1,
#     normalization=None,
#     n_jobs=-1,
#     max_frag_length=None,
#     suffix='.bw',
#     prefix=f"{str(tmp_path)}/plus."
# )   
    
#     output_plus = pybigtools.open(f"{str(tmp_path)}/plus.test.bw")
#     output_minus = pybigtools.open(f"{str(tmp_path)}/minus.test.bw")

#     assert list(bw_plus.intervals("chr1")) == list(output_plus.intervals("chr1"))
#     assert list(bw_minus.intervals("chr1")) == list(output_minus.intervals("chr1"))