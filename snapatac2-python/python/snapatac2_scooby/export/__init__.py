from __future__ import annotations

from typing import Literal
from pathlib import Path

import snapatac2_scooby._snapatac2 as internal
from snapatac2_scooby._utils import get_file_format

def export_fragments(
    adata: internal.AnnData | internal.AnnDataSet,
    groupby: str | list[str],
    selections: list[str] | None = None,
    ids: str | list[str] | None = None,
    min_frag_length: int | None = None,
    max_frag_length: int | None = None,
    out_dir: Path = "./",
    prefix: str = "",
    suffix: str = ".bed.zst",
    compression: Literal["gzip", "zstandard"] | None = None,
    compression_level: int | None = None,
) -> dict[str, str]:
    """Export and save fragments in a BED format file.

    Parameters
    ----------
    adata
        The (annotated) data matrix of shape `n_obs` x `n_vars`.
        Rows correspond to cells and columns to regions.
    groupby
        Group the cells. If a `str`, groups are obtained from
        `.obs[groupby]`.
    selections
        Export only the selected groups.
    ids
        Cell ids add to the bed records. If `None`, `.obs_names` is used.
    min_frag_length
        Minimum fragment length to be included in the computation.
    max_frag_length
        Maximum fragment length to be included in the computation.
    out_dir
        Directory for saving the outputs.
    prefix
        Text added to the output file name.
    suffix
        Text added to the output file name.
    compression
        Compression type. If `None`, it is inferred from the suffix.
    compression_level
        Compression level. 1-9 for gzip, 1-22 for zstandard.
        If `None`, it is set to 6 for gzip and 3 for zstandard.

    Returns
    -------
    dict[str, str]
        A dictionary contains `(groupname, filename)` pairs. The file names are
        formatted as `{prefix}{groupname}{suffix}`.

    See Also
    --------
    export_coverage
    """
    if isinstance(groupby, str):
        groupby = adata.obs[groupby]
    if selections is not None:
        selections = set(selections)
    
    if ids is None:
        ids = adata.obs_names
    elif isinstance(ids, str):
        ids = adata.obs[ids]

    if compression is None:
        _, compression = get_file_format(suffix)

    return internal.export_fragments(
        adata, list(ids), list(groupby), out_dir, prefix, suffix, selections, 
        min_frag_length, max_frag_length, compression, compression_level,
    )

def export_coverage(
    adata: internal.AnnData | internal.AnnDataSet,
    groupby: str | list[str],
    selections: list[str] | None = None,
    bin_size: int = 10,
    blacklist: Path | None = None,
    normalization: Literal["RPKM", "CPM", "BPM"] | None = "RPKM",
    include_for_norm: list[str] | Path = None,
    exclude_for_norm: list[str] | Path = None,
    min_frag_length: int | None = None,
    max_frag_length: int | None = 2000,
    counting_strategy: Literal['fragment', 'insertion'] = 'fragment',
    smooth_base: int | None = None,
    out_dir: Path = "./",
    prefix: str = "",
    suffix: str = ".bw",
    output_format: Literal["bedgraph", "bigwig"] | None = None,
    compression: Literal["gzip", "zstandard"] | None = None,
    compression_level: int | None = None,
    tempdir: Path | None = None,
    n_jobs: int = 8,
) -> dict[str, str]:
    """Export and save coverage in a bedgraph or bigwig format file.

    This function first divides cells into groups based on the `groupby` parameter.
    It then independently generates the genome-wide coverage track (bigWig or bedGraph) for each group
    of cells. The coverage is calculated as the number of reads
    per bin, where bins are short consecutive counting windows of a defined size.
    For paired-end data, the reads are extended to the fragment length and the
    coverage is calculated as the number of fragments per bin.
    There are several options for normalization. The default is RPKM, which
    normalizes by the total number of reads and the length of the region.
    The normalization can be disabled by setting `normalization=None`.

    .. image:: /_static/images/func+export_coverage.svg
        :align: center

    Parameters
    ----------
    adata
        The (annotated) data matrix of shape `n_obs` x `n_vars`.
        Rows correspond to cells and columns to regions.
    groupby
        Group the cells. If a `str`, groups are obtained from
        `.obs[groupby]`.
    selections
        Export only the selected groups.
    bin_size
        Size of the bins, in bases, for the output of the bigwig/bedgraph file.
    blacklist
        A BED file containing the blacklisted regions.
    normalization
        Normalization method. If `None`, no normalization is performed. Options:
        - RPKM (per bin) = #reads per bin / (#mapped_reads (in millions) * bin length (kb)).
        - CPM (per bin) = #reads per bin / #mapped_reads (in millions).
        - BPM (per bin) = #reads per bin / sum of all reads per bin (in millions).
    include_for_norm
        A list of string (e.g., ["chr1:1-100", "chr2:2-200"]) or a BED file containing
        the genomic loci to include for normalization.
        If specified, only the reads that overlap with these loci will be used for normalization.
        A typical use case is to include only the promoter regions for the normalization.
    exclude_for_norm
        A list of string (e.g., ["chr1:1-100", "chr2:2-200"]) or a BED file containing
        the genomic loci to exclude for normalization.
        If specified, the reads that overlap with these loci will be excluded from normalization.
        If a read overlaps with both `include_for_norm` and `exclude_for_norm`, it will be excluded.
    min_frag_length
        Minimum fragment length to be included in the computation.
    max_frag_length
        Maximum fragment length to be included in the computation.
    counting_strategy
        The strategy to compute feature counts. It must be one of the following:
        "fragment" or "insertion". "fragment" means the
        feature counts are assigned based on the number of fragments that overlap
        with a region of interest. "insertion" means the feature counts are assigned
        based on the number of insertions that overlap with a region of interest.
    smooth_base
        Length of the smoothing window in bases for the output of the bigwig/bedgraph file.
    out_dir
        Directory for saving the outputs.
    prefix
        Text added to the output file name.
    suffix
        Text added to the output file name.
    output_format
        Output format. If `None`, it is inferred from the suffix.
    compression
        Compression type. If `None`, it is inferred from the suffix.
    compression_level
        Compression level. 1-9 for gzip, 1-22 for zstandard.
        If `None`, it is set to 6 for gzip and 3 for zstandard.
    n_jobs
        Number of threads to use. If `<= 0`, use all available threads.

    Returns
    -------
    dict[str, str]
        A dictionary contains `(groupname, filename)` pairs. The file names are
        formatted as `{prefix}{groupname}{suffix}`.

    See Also
    --------
    export_fragments

    Examples
    --------
    >>> import snapatac2_scooby as snap
    >>> data = snap.read(snap.datasets.pbmc5k(type="annotated_h5ad"), backed='r')
    >>> snap.ex.export_coverage(data, groupby='cell_type', suffix='.bedgraph.zst')
    {'cDC': './cDC.bedgraph.zst',
     'Memory B': './Memory B.bedgraph.zst',
     'CD4 Naive': './CD4 Naive.bedgraph.zst',
     'pDC': './pDC.bedgraph.zst',
     'CD8 Naive': './CD8 Naive.bedgraph.zst',
     'CD8 Memory': './CD8 Memory.bedgraph.zst',
     'CD14 Mono': './CD14 Mono.bedgraph.zst',
     'Naive B': './Naive B.bedgraph.zst',
     'NK': './NK.bedgraph.zst',
     'CD4 Memory': './CD4 Memory.bedgraph.zst',
     'CD16 Mono': './CD16 Mono.bedgraph.zst',
     'MAIT': './MAIT.bedgraph.zst'}
    >>> snap.ex.export_coverage(data, groupby='cell_type', suffix='.bw')
    {'Naive B': './Naive B.bw',
     'CD4 Memory': './CD4 Memory.bw',
     'CD16 Mono': './CD16 Mono.bw',
     'CD8 Naive': './CD8 Naive.bw',
     'pDC': './pDC.bw',
     'CD8 Memory': './CD8 Memory.bw',
     'NK': './NK.bw',
     'Memory B': './Memory B.bw',
     'CD14 Mono': './CD14 Mono.bw',
     'MAIT': './MAIT.bw',
     'CD4 Naive': './CD4 Naive.bw',
     'cDC': './cDC.bw'}
    """
    if isinstance(groupby, str):
        groupby = adata.obs[groupby]
    if selections is not None:
        selections = set(selections)
    
    if output_format is None:
        output_format, inferred_compression = get_file_format(suffix)
        if output_format is None:
            raise ValueError("Output format cannot be inferred from suffix.")
        if compression is None:
            compression = inferred_compression

    n_jobs = None if n_jobs <= 0 else n_jobs
    return internal.export_coverage(
        adata, list(groupby), bin_size, out_dir, prefix, suffix, output_format, counting_strategy,
        selections, blacklist, normalization, include_for_norm, exclude_for_norm, min_frag_length,
        max_frag_length, smooth_base, compression, compression_level, tempdir, n_jobs,
    )