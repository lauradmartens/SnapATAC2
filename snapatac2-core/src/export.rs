use crate::utils::{ChromValues, ChromValuesReader, GenomeIndex, GBaseIndex};

use anndata_rs::{element::ElemTrait, anndata::{AnnData, AnnDataSet}};
use nalgebra_sparse::CsrMatrix;
use anyhow::{Context, Result, ensure};
use flate2::{Compression, write::GzEncoder};
use itertools::Itertools;
use std::{
    fs::File,
    io::{BufReader, BufWriter, BufRead, Write},
    path::{Path, PathBuf},
    collections::{BTreeMap, HashMap, HashSet},
    process::Command,
};
use tempfile::Builder;
use rayon::iter::{ParallelIterator, IntoParallelIterator};
use which::which;
use bed_utils::bed::{BEDLike, BED, BedGraph, OptionalFields};
use bigtools::{bigwig::bigwigwrite::BigWigWrite, bed::bedparser::BedParser};
use futures::executor::ThreadPool;

pub trait Exporter: ChromValuesReader {
    fn export_bed<P: AsRef<Path>>(
        &self,
        barcodes: &Vec<&str>,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>>;

    fn export_bigwig<P: AsRef<Path>>(
        &self,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        resolution: usize,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>>;

    fn call_peaks<P: AsRef<Path> + std::marker::Sync>(
        &self,
        q_value: f64,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>>
    {
        // Check if the command is in the PATH
        ensure!(
            which("macs2").is_ok(),
            "Cannot find macs2; please make sure macs2 has been installed"
        );

        std::fs::create_dir_all(&dir)?;
        let tmp_dir = Builder::new().tempdir_in(&dir)
            .context("failed to create tmperorary directory")?;

        eprintln!("preparing input...");
        let files = self.export_bed(
            group_by, group_by, selections, &tmp_dir, "", ".bed.gz"
        ).with_context(|| format!("cannot save bed file to {}", tmp_dir.path().display()))?;
        let genome_size = self.get_reference_seq_info()?.into_iter().map(|(_, v)| v).sum();
        eprintln!("calling peaks for {} groups...", files.len());
        files.into_par_iter().map(|(key, fl)| {
            let out_file = dir.as_ref().join(
                prefix.to_string() + key.as_str().replace("/", "+").as_str() + suffix
            );
            macs2(fl, q_value, genome_size, &tmp_dir, &out_file)?;
            eprintln!("group {}: done!", key);
            Ok((key, out_file))
        }).collect()
    }
}

impl Exporter for AnnData {
    fn export_bed<P: AsRef<Path>>(
        &self,
        barcodes: &Vec<&str>,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>> {
        export_insertions_as_bed(
            &mut self.read_insertions(500)?,
            barcodes, group_by, selections, dir, prefix, suffix,
        )
    }

    fn export_bigwig<P: AsRef<Path>>(
        &self,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        resolution: usize,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>> {
        let chrom_sizes = self.get_reference_seq_info()?.into_iter()
            .map(|(a, b)| (a, b as u32)).collect();
        let genome_index = GBaseIndex::read_from_anndata(&mut self.get_uns().inner())?;

        let mut groups: HashSet<&str> = group_by.iter().map(|x| *x).unique().collect();
        if let Some(select) = selections { groups.retain(|x| select.contains(x)); }
        std::fs::create_dir_all(&dir)
            .with_context(|| format!("cannot create directory: {}", dir.as_ref().display()))?;
        groups.into_iter().map(|x| {
            let filename = dir.as_ref().join(
                prefix.to_string() + x.replace("/", "+").as_str() + suffix
            );
            let insertion: Box<CsrMatrix<u8>> = self.get_obsm().inner()
                .get("insertion").expect(".obsm does not contain key: insertion")
                .read().unwrap().into_any().downcast().unwrap();
            export_insertions_as_bigwig(
                &insertion,
                &genome_index,
                &chrom_sizes,
                resolution,
                filename.as_path().to_str().unwrap().to_string(),
            );
            Ok((x.to_string(), filename))
        }).collect()
    }
}

impl Exporter for AnnDataSet {
    fn export_bed<P: AsRef<Path>>(
        &self,
        barcodes: &Vec<&str>,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>> {
        export_insertions_as_bed(
            &mut self.read_insertions(500)?,
            barcodes, group_by, selections, dir, prefix, suffix,
        )
    }

    fn export_bigwig<P: AsRef<Path>>(
        &self,
        group_by: &Vec<&str>,
        selections: Option<HashSet<&str>>,
        resolution: usize,
        dir: P,
        prefix: &str,
        suffix:&str,
    ) -> Result<HashMap<String, PathBuf>> {
        let chrom_sizes = self.get_reference_seq_info()?.into_iter()
            .map(|(a, b)| (a, b as u32)).collect();
        let genome_index = GBaseIndex::read_from_anndata(&mut self.get_uns().inner())?;

        let mut groups: HashSet<&str> = group_by.iter().map(|x| *x).unique().collect();
        if let Some(select) = selections { groups.retain(|x| select.contains(x)); }
        std::fs::create_dir_all(&dir)
            .with_context(|| format!("cannot create directory: {}", dir.as_ref().display()))?;
        groups.into_iter().map(|x| {
            let filename = dir.as_ref().join(
                prefix.to_string() + x.replace("/", "+").as_str() + suffix
            );
            let insertion: Box<CsrMatrix<u8>> = self.get_obsm().inner()
                .get("insertion").expect(".obsm does not contain key: insertion")
                .read().unwrap().into_any().downcast().unwrap();
            export_insertions_as_bigwig(
                &insertion,
                &genome_index,
                &chrom_sizes,
                resolution,
                filename.as_path().to_str().unwrap().to_string(),
            );
            Ok((x.to_string(), filename))
        }).collect()
    }
}



/// Export TN5 insertion sites to bed files with following fields:
///     1. chromosome
///     2. start
///     3. end (which is start + 1)
///     4. cell ID
fn export_insertions_as_bed<I, P>(
    insertions: &mut I,
    barcodes: &Vec<&str>,
    group_by: &Vec<&str>,
    selections: Option<HashSet<&str>>,
    dir: P,
    prefix: &str,
    suffix:&str,
) -> Result<HashMap<String, PathBuf>>
where
    I: Iterator<Item = Vec<ChromValues>>,
    P: AsRef<Path>,
{
    let mut groups: HashSet<&str> = group_by.iter().map(|x| *x).unique().collect();
    if let Some(select) = selections { groups.retain(|x| select.contains(x)); }
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("cannot create directory: {}", dir.as_ref().display()))?;
    let mut files = groups.into_iter().map(|x| {
        let filename = dir.as_ref().join(
            prefix.to_string() + x.replace("/", "+").as_str() + suffix
        );
        let f = File::create(&filename)
            .with_context(|| format!("cannot create file: {}", filename.display()))?;
        let e: Box<dyn Write> = if filename.ends_with(".gz") {
            Box::new(GzEncoder::new(BufWriter::new(f), Compression::default()))
        } else {
            Box::new(BufWriter::new(f))
        };
        Ok((x, (filename, e)))
    }).collect::<Result<HashMap<_, _>>>()?;

    insertions.try_fold::<_, _, Result<_>>(0, |accum, x| {
        let n_records = x.len();
        x.into_iter().enumerate().try_for_each::<_, Result<_>>(|(i, ins)| {
            if let Some((_, fl)) = files.get_mut(group_by[accum + i]) {
                let bc = barcodes[accum + i];
                ins.into_iter().map(|x| {
                    let bed: BED<4> = BED::new(
                        x.chrom(), x.start(), x.end(), Some(bc.to_string()),
                        None, None, OptionalFields::default(),
                    );
                    vec![bed; x.value as usize]
                }).flatten().try_for_each(|o| writeln!(fl, "{}", o))?;
            }
            Ok(())
        })?;
        Ok(accum + n_records)
    })?;
    Ok(files.into_iter().map(|(k, (v, _))| (k.to_string(), v)).collect())
}

/// Export TN5 insertions as bigwig files
/// 
/// # Arguments
/// 
/// * `insertions` - TN5 insertion matrix
/// * `genome_index` - 
/// * `chrom_sizes` - 
fn export_insertions_as_bigwig(
    insertions: &CsrMatrix<u8>,
    genome_index: &GBaseIndex,
    chrom_sizes: &HashMap<String, u32>,
    resolution: usize,
    out_file: String,
)
{
    // aggregate insertion counts
    let mut counts: BTreeMap<usize, u32> = BTreeMap::new();
    insertions.col_indices().into_iter().zip(insertions.values()).for_each(|(i, v)| {
        let e = counts.entry(*i / resolution).or_insert(0);
        *e += *v as u32;
    });

    // compute normalization factor
    let total_count: u32 = counts.values().sum();
    let norm_factor = ((total_count as f32) / 1000000.0) *
        ((resolution as f32) / 1000.0);

    // Make BedGraph
    let mut bedgraph: Vec<BedGraph<f32>> = counts.into_iter().map(move |(k, v)| {
        let mut region = genome_index.lookup_region(k * resolution);
        region.set_end(region.start() + resolution as u64);
        BedGraph::from_bed(&region, (v as f32) / norm_factor)
    }).group_by(|x| (x.chrom().to_string(), x.value)).into_iter().map(|(_, mut groups)| {
        let mut first = groups.next().unwrap();
        if let Some(last) = groups.last() {
            first.set_end(last.end());
        }
        first
    }).collect();

    // perform clipping to make sure the end of each region is within the range.
    bedgraph.iter_mut().group_by(|x| x.chrom().to_string()).into_iter().for_each(|(chr, groups)| {
        let size = *chrom_sizes.get(&chr).expect(&format!("chromosome not found: {}", chr)) as u64;
        let bed = groups.last().unwrap();
        if bed.end() > size {
            bed.set_end(size);
        }
    });

    // write to bigwig file
    BigWigWrite::create_file(out_file).write(
        chrom_sizes.clone(),
        bigtools::bed::bedparser::BedParserStreamingIterator::new(
            BedParser::wrap_iter(bedgraph.into_iter().map(|x| {
                let val = bigtools::bigwig::Value {
                    start: x.start() as u32,
                    end: x.end() as u32,
                    value: x.value,
                };
                Ok((x.chrom().to_string(), val))
            })),
            chrom_sizes.clone(),
            false,
        ),
        ThreadPool::new().unwrap(),
    ).unwrap();
}

fn macs2<P1, P2, P3>(
    bed_file: P1,
    q_value: f64,
    genome_size: u64,
    tmp_dir: P2,
    out_file: P3,
) -> Result<()>
where
    P1: AsRef<Path>,
    P2: AsRef<Path>,
    P3: AsRef<Path>,
{
    let dir = Builder::new().tempdir_in(tmp_dir)?;

    Command::new("macs2").args([
        "callpeak",
        "-f", "BED",
        "-t", bed_file.as_ref().to_str().unwrap(),
        "--keep-dup", "all",
        "--outdir", format!("{}", dir.path().display()).as_str(),
        "--qvalue", format!("{}", q_value).as_str(),
        "-g", format!("{}", (genome_size as f64 * 0.9).round()).as_str(),
        "--call-summits",
        "--nomodel", "--shift", "-100", "--extsize", "200",
        "--nolambda",
        "--tempdir", format!("{}", dir.path().display()).as_str(),
    ]).output().context("macs2 command did not exit properly")?;

    let reader = BufReader::new(File::open(
        dir.path().join("NA_peaks.narrowPeak"))
            .context("NA_peaks.narrowPeak: cannot find the peak file")?
    );
    let mut writer: Box<dyn Write> = if out_file.as_ref().extension().unwrap() == "gz" {
        Box::new(BufWriter::new(GzEncoder::new(
            File::create(out_file)?,
            Compression::default(),
        )))
    } else {
        Box::new(BufWriter::new(File::create(out_file)?))
    };
    for x in reader.lines() {
        let x_ = x?;
        let mut strs: Vec<_> = x_.split("\t").collect();
        if strs[4].parse::<u64>().unwrap() > 1000 {
            strs[4] = "1000";
        }
        let line: String = strs.into_iter().intersperse("\t").collect();
        write!(writer, "{}\n", line)?;
    }
    Ok(())
}
 