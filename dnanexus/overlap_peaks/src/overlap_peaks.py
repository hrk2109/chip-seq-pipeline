#!/usr/bin/env python
# overlap_peaks 0.0.1

import re
import dxpy
import common
import logging
import subprocess

logger = logging.getLogger(__name__)
logger.addHandler(dxpy.DXLogHandler())
logger.propagate = False
logger.setLevel(logging.INFO)


def xcor_only(tags, paired_end, spp_version=None, name='xcor_only'):
    xcor_only_applet = \
        dxpy.find_one_data_object(
            classname='applet',
            name='xcor_only',
            project=dxpy.PROJECT_CONTEXT_ID,
            zero_ok=False,
            more_ok=False,
            return_handler=True)
    applet_input = {
        "input_tagAlign": tags,
        "paired_end": paired_end
    }
    if spp_version:
        applet_input.update({'spp_version': spp_version})
    return xcor_only_applet.run(applet_input, name=name)


def internal_pseudoreplicate_overlap(rep1_peaks, rep2_peaks, pooled_peaks,
                                     rep1_ta, rep1_xcor,
                                     paired_end, chrom_sizes, as_file,
                                     peak_type, prefix, fragment_length=None):

    rep1_peaks_file      = dxpy.DXFile(rep1_peaks)
    rep2_peaks_file      = dxpy.DXFile(rep2_peaks)
    pooled_peaks_file    = dxpy.DXFile(pooled_peaks)
    rep1_ta_file         = dxpy.DXFile(rep1_ta)
    rep1_xcor_file       = dxpy.DXFile(rep1_xcor)
    chrom_sizes_file     = dxpy.DXFile(chrom_sizes)
    as_file_file         = dxpy.DXFile(as_file)

    # Input filenames - necessary to define each explicitly because input files
    # could have the same name, in which case subsequent
    # file would overwrite previous file
    rep1_peaks_fn      = 'rep1-%s' % (rep1_peaks_file.name)
    rep2_peaks_fn      = 'rep2-%s' % (rep2_peaks_file.name)
    pooled_peaks_fn    = 'pooled-%s' % (pooled_peaks_file.name)
    rep1_ta_fn         = 'r1ta_%s' % (rep1_ta_file.name)
    rep1_xcor_fn       = 'r1xc_%s' % (rep1_xcor_file.name)
    chrom_sizes_fn     = 'chrom.sizes'
    as_file_fn         = '%s.as' % (peak_type)

    # Output filenames
    if prefix:
        basename = prefix
    else:
        # strip off the peak and compression extensions
        m = re.match(
            '(.*)(\.%s)+(\.((gz)|(Z)|(bz)|(bz2)))' % (peak_type),
            pooled_peaks.name)
        if m:
            basename = m.group(1)
        else:
            basename = pooled_peaks.name

    overlapping_peaks_fn    = '%s.replicated.%s' % (basename, peak_type)
    overlapping_peaks_bb_fn = overlapping_peaks_fn + '.bb'
    rejected_peaks_fn       = '%s.rejected.%s' % (basename, peak_type)
    rejected_peaks_bb_fn    = rejected_peaks_fn + '.bb'

    # Intermediate filenames
    overlap_tr_fn = 'replicated_tr.%s' % (peak_type)
    overlap_pr_fn = 'replicated_pr.%s' % (peak_type)

    # Download file inputs to the local file system with local filenames

    dxpy.download_dxfile(rep1_peaks_file.get_id(), rep1_peaks_fn)
    dxpy.download_dxfile(rep2_peaks_file.get_id(), rep2_peaks_fn)
    dxpy.download_dxfile(pooled_peaks_file.get_id(), pooled_peaks_fn)
    dxpy.download_dxfile(rep1_ta_file.get_id(), rep1_ta_fn)
    dxpy.download_dxfile(rep1_xcor_file.get_id(), rep1_xcor_fn)
    dxpy.download_dxfile(chrom_sizes_file.get_id(), chrom_sizes_fn)
    dxpy.download_dxfile(as_file_file.get_id(), as_file_fn)

    logger.info(subprocess.check_output('set -x; ls -l', shell=True))

    # the only difference between the peak_types is how the extra columns are
    # handled
    if peak_type == "narrowPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$13-$12; if (($21/s1 >= 0.5) || ($21/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-10'
        bed_type = 'bed6+4'
    elif peak_type == "gappedPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$18-$17; if (($31/s1 >= 0.5) || ($31/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-15'
        bed_type = 'bed12+3'
    elif peak_type == "broadPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$12-$11; if (($19/s1 >= 0.5) || ($19/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-9'
        bed_type = 'bed6+3'
    else:
        assert peak_type in ['narrowPeak', 'gappedPeak', 'broadPeak'], "%s is unrecognized.  peak_type should be narrowPeak, gappedPeak or broadPeak." % (peak_type)

    # Find pooled peaks that overlap Rep1 and Rep2 where overlap is defined as
    # the fractional overlap wrt any one of the overlapping peak pairs  > 0.5
    out, err = common.run_pipe([
        'intersectBed -wo -a %s -b %s' % (pooled_peaks_fn, rep1_peaks_fn),
        awk_command,
        cut_command,
        'sort -u',
        'intersectBed -wo -a stdin -b %s' % (rep2_peaks_fn),
        awk_command,
        cut_command,
        'sort -u'
        ], overlap_tr_fn)
    print(
        "%d peaks overlap with both true replicates"
        % (common.count_lines(overlap_tr_fn)))

    # this is a simplicate analysis
    # overlapping peaks are just based on pseudoreps of the one pool
    out, err = common.run_pipe([
        'cat %s' % (overlap_tr_fn),
        'sort -u'
        ], overlapping_peaks_fn)
    print(
        "%d peaks overlap"
        % (common.count_lines(overlapping_peaks_fn)))

    # rejected peaks
    out, err = common.run_pipe([
        'intersectBed -wa -v -a %s -b %s' % (pooled_peaks_fn, overlapping_peaks_fn)
        ], rejected_peaks_fn)
    print("%d peaks were rejected" % (common.count_lines(rejected_peaks_fn)))

    # calculate FRiP (Fraction of Reads in Peaks)

    # Extract the fragment length estimate from column 3 of the
    # cross-correlation scores file or use the user-defined
    # fragment_length if given.
    if fragment_length is not None:
        fraglen = fragment_length
        fragment_length_given_by_user = True
    else:
        fraglen = common.xcor_fraglen(rep1_xcor_fn)
        fragment_length_given_by_user = False

    # FRiP
    reads_in_peaks_fn = 'reads_in_%s.ta' % (peak_type)
    n_reads, n_reads_in_peaks, frip_score = common.frip(
        rep1_ta_fn, rep1_xcor_fn, overlapping_peaks_fn,
        chrom_sizes_fn, fraglen,
        reads_in_peaks_fn=reads_in_peaks_fn)

    # count peaks
    npeaks_in = common.count_lines(common.uncompress(pooled_peaks_fn))
    npeaks_out = common.count_lines(overlapping_peaks_fn)
    npeaks_rejected = common.count_lines(rejected_peaks_fn)

    # make bigBed files for visualization
    overlapping_peaks_bb_fn = common.bed2bb(
        overlapping_peaks_fn, chrom_sizes_fn, as_file_fn, bed_type=bed_type)
    rejected_peaks_bb_fn = common.bed2bb(
        rejected_peaks_fn, chrom_sizes_fn, as_file_fn, bed_type=bed_type)

    # Upload file outputs from the local file system.

    overlapping_peaks = dxpy.upload_local_file(common.compress(overlapping_peaks_fn))
    overlapping_peaks_bb = dxpy.upload_local_file(overlapping_peaks_bb_fn)
    rejected_peaks = dxpy.upload_local_file(common.compress(rejected_peaks_fn))
    rejected_peaks_bb = dxpy.upload_local_file(rejected_peaks_bb_fn)

    output = {
        "overlapping_peaks"     : dxpy.dxlink(overlapping_peaks),
        "overlapping_peaks_bb"  : dxpy.dxlink(overlapping_peaks_bb),
        "rejected_peaks"        : dxpy.dxlink(rejected_peaks),
        "rejected_peaks_bb"     : dxpy.dxlink(rejected_peaks_bb),
        "npeaks_in"             : npeaks_in,
        "npeaks_out"            : npeaks_out,
        "npeaks_rejected"       : npeaks_rejected,
        "frip_nreads"           : n_reads,
        "frip_nreads_in_peaks"  : n_reads_in_peaks,
        "frip_score"            : frip_score,
        "fragment_length_used"  : fraglen,
        "fragment_length_given_by_user": fragment_length_given_by_user
    }

    return output


def replicated_overlap(rep1_peaks, rep2_peaks, pooled_peaks,
                       pooledpr1_peaks, pooledpr2_peaks,
                       rep1_ta, rep1_xcor, rep2_ta, rep2_xcor,
                       paired_end, chrom_sizes, as_file, peak_type, prefix,
                       fragment_length=None):

    rep1_peaks_file      = dxpy.DXFile(rep1_peaks)
    rep2_peaks_file      = dxpy.DXFile(rep2_peaks)
    pooled_peaks_file    = dxpy.DXFile(pooled_peaks)
    pooledpr1_peaks_file = dxpy.DXFile(pooledpr1_peaks)
    pooledpr2_peaks_file = dxpy.DXFile(pooledpr2_peaks)
    rep1_ta_file         = dxpy.DXFile(rep1_ta)
    rep2_ta_file         = dxpy.DXFile(rep2_ta)
    rep1_xcor_file       = dxpy.DXFile(rep1_xcor)
    rep2_xcor_file       = dxpy.DXFile(rep2_xcor)
    chrom_sizes_file     = dxpy.DXFile(chrom_sizes)
    as_file_file         = dxpy.DXFile(as_file)

    # Input filenames - necessary to define each explicitly because input files
    # could have the same name, in which case subsequent
    # file would overwrite previous file
    rep1_peaks_fn      = 'rep1-%s' % (rep1_peaks_file.name)
    rep2_peaks_fn      = 'rep2-%s' % (rep2_peaks_file.name)
    pooled_peaks_fn    = 'pooled-%s' % (pooled_peaks_file.name)
    pooledpr1_peaks_fn = 'pooledpr1-%s' % (pooledpr1_peaks_file.name)
    pooledpr2_peaks_fn = 'pooledpr2-%s' % (pooledpr2_peaks_file.name)
    rep1_ta_fn         = 'r1ta_%s' % (rep1_ta_file.name)
    rep2_ta_fn         = 'r2ta_%s' % (rep2_ta_file.name)
    rep1_xcor_fn       = 'r1cc_%s' % (rep1_xcor_file.name)
    rep2_xcor_fn       = 'r2cc_%s' % (rep2_xcor_file.name)
    chrom_sizes_fn     = 'chrom.sizes'
    as_file_fn         = '%s.as' % (peak_type)

    # Output filenames
    if prefix:
        basename = prefix
    else:
        # strip off the peak and compression extensions
        m = re.match(
            '(.*)(\.%s)+(\.((gz)|(Z)|(bz)|(bz2)))' % (peak_type),
            pooled_peaks.name)
        if m:
            basename = m.group(1)
        else:
            basename = pooled_peaks.name

    overlapping_peaks_fn    = '%s.replicated.%s' % (basename, peak_type)
    overlapping_peaks_bb_fn = overlapping_peaks_fn + '.bb'
    rejected_peaks_fn       = '%s.rejected.%s' % (basename, peak_type)
    rejected_peaks_bb_fn    = rejected_peaks_fn + '.bb'

    # Intermediate filenames
    overlap_tr_fn = 'replicated_tr.%s' % (peak_type)
    overlap_pr_fn = 'replicated_pr.%s' % (peak_type)

    # Download file inputs to the local file system with local filenames

    dxpy.download_dxfile(rep1_peaks_file.get_id(), rep1_peaks_fn)
    dxpy.download_dxfile(rep2_peaks_file.get_id(), rep2_peaks_fn)
    dxpy.download_dxfile(pooled_peaks_file.get_id(), pooled_peaks_fn)
    dxpy.download_dxfile(pooledpr1_peaks_file.get_id(), pooledpr1_peaks_fn)
    dxpy.download_dxfile(pooledpr2_peaks_file.get_id(), pooledpr2_peaks_fn)
    dxpy.download_dxfile(rep1_ta_file.get_id(), rep1_ta_fn)
    dxpy.download_dxfile(rep2_ta_file.get_id(), rep2_ta_fn)
    dxpy.download_dxfile(rep1_xcor_file.get_id(), rep1_xcor_fn)
    dxpy.download_dxfile(rep2_xcor_file.get_id(), rep2_xcor_fn)
    dxpy.download_dxfile(chrom_sizes_file.get_id(), chrom_sizes_fn)
    dxpy.download_dxfile(as_file_file.get_id(), as_file_fn)

    pool_applet = dxpy.find_one_data_object(
            classname='applet',
            name='pool',
            project=dxpy.PROJECT_CONTEXT_ID,
            zero_ok=False,
            more_ok=False,
            return_handler=True)
    pool_replicates_subjob = \
        pool_applet.run(
            {"inputs": [rep1_ta, rep2_ta],
             "prefix": 'pooled_reps'},
            name='Pool replicates')
    # If fragment length was given by user we skip pooled_replicates
    # _xcor_subjob, set the pool_xcor_filename to None, and update
    # the flag fragment_length_given_by_user. Otherwise, run the subjob
    # to be able to extract the fragment length fron cross-correlations.
    if fragment_length is not None:
        pool_xcor_filename = None
        fraglen = fragment_length
        fragment_length_given_by_user = True
    else:
        pooled_replicates_xcor_subjob = \
            xcor_only(
                pool_replicates_subjob.get_output_ref("pooled"),
                paired_end,
                spp_version=None,
                name='Pool cross-correlation')
        pooled_replicates_xcor_subjob.wait_on_done()
        pool_xcor_link = pooled_replicates_xcor_subjob.describe()['output'].get("CC_scores_file")
        pool_xcor_file = dxpy.get_handler(pool_xcor_link)
        pool_xcor_filename = 'poolcc_%s' % (pool_xcor_file.name)
        dxpy.download_dxfile(pool_xcor_file.get_id(), pool_xcor_filename)
        fraglen = common.xcor_fraglen(pool_xcor_filename)
        fragment_length_given_by_user = False

    pool_replicates_subjob.wait_on_done()
    pool_ta_link = pool_replicates_subjob.describe()['output'].get("pooled")
    pool_ta_file = dxpy.get_handler(pool_ta_link)
    pool_ta_filename = 'poolta_%s' % (pool_ta_file.name)
    dxpy.download_dxfile(pool_ta_file.get_id(), pool_ta_filename)

    logger.info(subprocess.check_output('set -x; ls -l', shell=True))

    # the only difference between the peak_types is how the extra columns are
    # handled
    if peak_type == "narrowPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$13-$12; if (($21/s1 >= 0.5) || ($21/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-10'
        bed_type = 'bed6+4'
    elif peak_type == "gappedPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$18-$17; if (($31/s1 >= 0.5) || ($31/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-15'
        bed_type = 'bed12+3'
    elif peak_type == "broadPeak":
        awk_command = r"""awk 'BEGIN{FS="\t";OFS="\t"}{s1=$3-$2; s2=$12-$11; if (($19/s1 >= 0.5) || ($19/s2 >= 0.5)) {print $0}}'"""
        cut_command = 'cut -f 1-9'
        bed_type = 'bed6+3'
    else:
        assert peak_type in ['narrowPeak', 'gappedPeak', 'broadPeak'], "%s is unrecognized.  peak_type should be narrowPeak, gappedPeak or broadPeak." % (peak_type)

    # Find pooled peaks that overlap Rep1 and Rep2 where overlap is defined as
    # the fractional overlap wrt any one of the overlapping peak pairs  > 0.5
    out, err = common.run_pipe([
        'intersectBed -wo -a %s -b %s' % (pooled_peaks_fn, rep1_peaks_fn),
        awk_command,
        cut_command,
        'sort -u',
        'intersectBed -wo -a stdin -b %s' % (rep2_peaks_fn),
        awk_command,
        cut_command,
        'sort -u'
        ], overlap_tr_fn)
    print(
        "%d peaks overlap with both true replicates"
        % (common.count_lines(overlap_tr_fn)))

    # Find pooled peaks that overlap PseudoRep1 and PseudoRep2 where
    # overlap is defined as the fractional overlap wrt any one of the
    # overlapping peak pairs  > 0.5
    out, err = common.run_pipe([
        'intersectBed -wo -a %s -b %s' % (pooled_peaks_fn, pooledpr1_peaks_fn),
        awk_command,
        cut_command,
        'sort -u',
        'intersectBed -wo -a stdin -b %s' % (pooledpr2_peaks_fn),
        awk_command,
        cut_command,
        'sort -u'
        ], overlap_pr_fn)
    print(
        "%d peaks overlap with both pooled pseudoreplicates"
        % (common.count_lines(overlap_pr_fn)))

    # Combine peak lists
    out, err = common.run_pipe([
        'cat %s %s' % (overlap_tr_fn, overlap_pr_fn),
        'sort -u'
        ], overlapping_peaks_fn)
    print(
        "%d peaks overlap with true replicates or with pooled pseudoreplicates"
        % (common.count_lines(overlapping_peaks_fn)))

    # rejected peaks
    out, err = common.run_pipe([
        'intersectBed -wa -v -a %s -b %s' % (pooled_peaks_fn, overlapping_peaks_fn)
        ], rejected_peaks_fn)
    print("%d peaks were rejected" % (common.count_lines(rejected_peaks_fn)))

    # calculate FRiP (Fraction of Reads in Peaks)
    reads_in_peaks_fn = 'reads_in_%s.ta' % (peak_type)
    n_reads, n_reads_in_peaks, frip_score = common.frip(
        pool_ta_filename, pool_xcor_filename, overlapping_peaks_fn,
        chrom_sizes_fn, fraglen, reads_in_peaks_fn=reads_in_peaks_fn)

    # count peaks
    npeaks_in        = common.count_lines(common.uncompress(pooled_peaks_fn))
    npeaks_out       = common.count_lines(overlapping_peaks_fn)
    npeaks_rejected  = common.count_lines(rejected_peaks_fn)

    # make bigBed files for visualization
    overlapping_peaks_bb_fn = common.bed2bb(
        overlapping_peaks_fn, chrom_sizes_fn, as_file_fn, bed_type=bed_type)
    rejected_peaks_bb_fn = common.bed2bb(
        rejected_peaks_fn, chrom_sizes_fn, as_file_fn, bed_type=bed_type)

    # Upload file outputs from the local file system.

    overlapping_peaks       = dxpy.upload_local_file(common.compress(overlapping_peaks_fn))
    overlapping_peaks_bb    = dxpy.upload_local_file(overlapping_peaks_bb_fn)
    rejected_peaks          = dxpy.upload_local_file(common.compress(rejected_peaks_fn))
    rejected_peaks_bb       = dxpy.upload_local_file(rejected_peaks_bb_fn)

    output = {
        "overlapping_peaks"     : dxpy.dxlink(overlapping_peaks),
        "overlapping_peaks_bb"  : dxpy.dxlink(overlapping_peaks_bb),
        "rejected_peaks"        : dxpy.dxlink(rejected_peaks),
        "rejected_peaks_bb"     : dxpy.dxlink(rejected_peaks_bb),
        "npeaks_in"             : npeaks_in,
        "npeaks_out"            : npeaks_out,
        "npeaks_rejected"       : npeaks_rejected,
        "frip_nreads"           : n_reads,
        "frip_nreads_in_peaks"  : n_reads_in_peaks,
        "frip_score"            : frip_score,
        "fragment_length_used"  : fraglen,
        "fragment_length_given_by_user": fragment_length_given_by_user
    }

    return output


@dxpy.entry_point('main')
def main(rep1_peaks, rep2_peaks, pooled_peaks,
         rep1_ta, rep1_xcor,
         paired_end, chrom_sizes, as_file, peak_type,
         pooledpr1_peaks=None, pooledpr2_peaks=None,
         rep2_ta=None, rep2_xcor=None,
         prefix=None,
         rep1_signal=None, rep2_signal=None, pooled_signal=None,
         fragment_length=None):

    replicate_inputs = [pooledpr1_peaks, pooledpr2_peaks]
    simplicate_experiment = \
        all([replicate_input is None for replicate_input in replicate_inputs])
    # that means pooledpr1_peaks is None and pooledpr2_peaks is None

    if simplicate_experiment:
        output = internal_pseudoreplicate_overlap(
            rep1_peaks, rep2_peaks, pooled_peaks,
            rep1_ta, rep1_xcor,
            paired_end, chrom_sizes, as_file, peak_type, prefix,
            fragment_length)
    else:
        output = replicated_overlap(
            rep1_peaks, rep2_peaks, pooled_peaks,
            pooledpr1_peaks, pooledpr2_peaks,
            rep1_ta, rep1_xcor, rep2_ta, rep2_xcor,
            paired_end, chrom_sizes, as_file, peak_type, prefix,
            fragment_length)

    # These are just passed through for convenience so that signals and tracks
    # are available in one place.  Both input and output are optional.
    if rep1_signal:
        output.update({"rep1_signal": rep1_signal})
    if rep2_signal:
        output.update({"rep2_signal": rep2_signal})
    if pooled_signal:
        output.update({"pooled_signal": pooled_signal})

    logging.info("Exiting with output: %s", output)
    return output


dxpy.run()
