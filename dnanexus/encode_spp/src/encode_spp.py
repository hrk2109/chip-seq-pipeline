#!/usr/bin/env python
# encode_spp 0.0.1
# Generated by dx-app-wizard.
#
# Basic execution pattern: Your app will run on a single machine from
# beginning to end.
#
# See https://wiki.dnanexus.com/Developer-Portal for documentation and
# tutorials on how to modify this file.
#
# DNAnexus Python Bindings (dxpy) documentation:
#   http://autodoc.dnanexus.com/bindings/python/current/

import os, subprocess, shlex, time, re
from multiprocessing import Pool, cpu_count
from subprocess import Popen, PIPE #debug only this should only need to be imported into run_pipe
import dxpy

def run_pipe(steps, outfile=None):
    #break this out into a recursive function
    #TODO:  capture stderr
    from subprocess import Popen, PIPE
    p = None
    p_next = None
    first_step_n = 1
    last_step_n = len(steps)
    for n,step in enumerate(steps, start=first_step_n):
        print "step %d: %s" %(n,step)
        if n == first_step_n:
            if n == last_step_n and outfile: #one-step pipeline with outfile
                with open(outfile, 'w') as fh:
                    print "one step shlex: %s to file: %s" %(shlex.split(step), outfile)
                    p = Popen(shlex.split(step), stdout=fh)
                break
            print "first step shlex to stdout: %s" %(shlex.split(step))
            p = Popen(shlex.split(step), stdout=PIPE)
            #need to close p.stdout here?
        elif n == last_step_n and outfile: #only treat the last step specially if you're sending stdout to a file
            with open(outfile, 'w') as fh:
                print "last step shlex: %s to file: %s" %(shlex.split(step), outfile)
                p_last = Popen(shlex.split(step), stdin=p.stdout, stdout=fh)
                p.stdout.close()
                p = p_last
        else: #handles intermediate steps and, in the case of a pipe to stdout, the last step
            print "intermediate step %d shlex to stdout: %s" %(n,shlex.split(step))
            p_next = Popen(shlex.split(step), stdin=p.stdout, stdout=PIPE)
            p.stdout.close()
            p = p_next
    out,err = p.communicate()
    return out,err

def count_lines(filename):
    if filename.endswith(('.Z','.gz','.bz','.bz2')):
        catcommand = 'gzip -dc'
    else:
        catcommand = 'cat'
    out,err = run_pipe([
        '%s %s' %(catcommand, filename),
        'wc -l'
    ])
    return int(out)

def spp(experiment, control, xcor_scores):
    spp_applet = dxpy.find_one_data_object(
        classname='applet', name='spp', zero_ok=False, more_ok=False, return_handler=True)
    return spp_applet.run(
        {"experiment": experiment,
         "control": control,
         "xcor_scores_input": xcor_scores},
         instance_type="mem2_ssd1_x8")

def xcor_only(tags, paired_end):
    xcor_only_applet = dxpy.find_one_data_object(
        classname='applet', name='xcor_only', zero_ok=False, more_ok=False, return_handler=True)
    return xcor_only_applet.run({"input_tagAlign": tags, "paired_end": paired_end}, instance_type="mem2_ssd1_x8")

 
@dxpy.entry_point('main')
def main(rep1_ta, rep2_ta, ctl1_ta, ctl2_ta, rep1_xcor, rep2_xcor, npeaks, nodups, rep1_paired_end, rep2_paired_end):

    if not rep1_paired_end == rep2_paired_end:
      raise ValueError('Mixed PE/SE not supported (yet)')
    paired_end = rep1_paired_end
    # The following lines initialize the data object inputs on the platform
    # into dxpy.DXDataObject instances that you can start using immediately.

    rep1_ta_file = dxpy.DXFile(rep1_ta)
    rep2_ta_file = dxpy.DXFile(rep2_ta)
    ctl1_ta_file = dxpy.DXFile(ctl1_ta)
    ctl2_ta_file = dxpy.DXFile(ctl2_ta)
    rep1_xcor_file = dxpy.DXFile(rep1_xcor)
    rep2_xcor_file = dxpy.DXFile(rep2_xcor)

    # The following line(s) download your file inputs to the local file system
    # using variable names for the filenames.

    dxpy.download_dxfile(rep1_ta_file.get_id(), rep1_ta_file.name)
    dxpy.download_dxfile(rep2_ta_file.get_id(), rep2_ta_file.name)
    dxpy.download_dxfile(ctl1_ta_file.get_id(), ctl1_ta_file.name)
    dxpy.download_dxfile(ctl2_ta_file.get_id(), ctl2_ta_file.name)
    dxpy.download_dxfile(rep1_xcor_file.get_id(), rep1_xcor_file.name)
    dxpy.download_dxfile(rep2_xcor_file.get_id(), rep2_xcor_file.name)

    rep1_ta_filename = rep1_ta_file.name
    rep2_ta_filename = rep2_ta_file.name
    ctl1_ta_filename = ctl1_ta_file.name
    ctl2_ta_filename = ctl2_ta_file.name
    rep1_xcor_filename = rep1_xcor_file.name
    rep2_xcor_filename = rep2_xcor_file.name

    ntags_rep1 = count_lines(rep1_ta_filename)
    ntags_rep2 = count_lines(rep2_ta_filename)
    ntags_ctl1 = count_lines(ctl1_ta_filename)
    ntags_ctl2 = count_lines(ctl2_ta_filename)

    for n,name,filename in [(ntags_rep1, 'replicate 1', rep1_ta_filename),
                            (ntags_rep2, 'replicate 2', rep2_ta_filename),
                            (ntags_ctl1, 'control 1', ctl1_ta_filename),
                            (ntags_ctl2, 'control 2', ctl2_ta_filename)]:
        print "Found %d tags in %s file %s" %(n,name,filename)

    print subprocess.check_output('ls -l', shell=True, stderr=subprocess.STDOUT)

    pool_applet = dxpy.find_one_data_object(
        classname='applet', name='pool', zero_ok=False, more_ok=False, return_handler=True)
    pool_controls_subjob = pool_applet.run({"inputs": [ctl1_ta, ctl2_ta]})
    pool_replicates_subjob = pool_applet.run({"inputs": [rep1_ta, rep2_ta]})

    pooled_controls = pool_controls_subjob.get_output_ref("pooled")
    pooled_replicates = pool_replicates_subjob.get_output_ref("pooled")

    rep1_control = ctl1_ta #default
    rep2_control = ctl2_ta #default
    ratio_ctl_reads = float(ntags_ctl1)/float(ntags_ctl2)
    if ratio_ctl_reads < 1:
        ratio_ctl_reads = 1/ratio_ctl_reads
    ratio_cutoff = 1.2
    if ratio_ctl_reads > ratio_cutoff:
        print "Number of reads in controls differ by > factor of %f. Using pooled controls." %(ratio_cutoff)
        rep1_control = pooled_controls
        rep2_control = pooled_controls
    else:
        if ntags_ctl1 < ntags_rep1:
            print "Fewer reads in control replicate 1 than experiment replicate 1.  Using pooled controls for replicate 1."
            rep1_control = pooled_controls
        if ntags_ctl2 < ntags_rep2:
            print "Fewer reads in control replicate 2 than experiment replicate 2.  Using pooled controls for replicate 2."
            rep2_control = pooled_controls

    pseudoreplicator_applet = dxpy.find_one_data_object(
        classname='applet', name='pseudoreplicator', zero_ok=False, more_ok=False, return_handler=True)
    rep1_pr_subjob = pseudoreplicator_applet.run({"input_tags": rep1_ta})
    rep2_pr_subjob = pseudoreplicator_applet.run({"input_tags": rep2_ta})

    pool_pr1_subjob = pool_applet.run({"inputs": [rep1_pr_subjob.get_output_ref("pseudoreplicate1"),
                                                  rep2_pr_subjob.get_output_ref("pseudoreplicate1")]})
    pool_pr2_subjob = pool_applet.run({"inputs": [rep1_pr_subjob.get_output_ref("pseudoreplicate2"),
                                                  rep2_pr_subjob.get_output_ref("pseudoreplicate2")]})

    pooled_replicates_xcor_subjob = xcor_only(pooled_replicates, paired_end)
    rep1_pr1_xcor_subjob = xcor_only(rep1_pr_subjob.get_output_ref("pseudoreplicate1"), paired_end)
    rep1_pr2_xcor_subjob = xcor_only(rep1_pr_subjob.get_output_ref("pseudoreplicate2"), paired_end)
    rep2_pr1_xcor_subjob = xcor_only(rep2_pr_subjob.get_output_ref("pseudoreplicate1"), paired_end)
    rep2_pr2_xcor_subjob = xcor_only(rep2_pr_subjob.get_output_ref("pseudoreplicate2"), paired_end)
    pool_pr1_xcor_subjob = xcor_only(pool_pr1_subjob.get_output_ref("pooled"), paired_end)
    pool_pr2_xcor_subjob = xcor_only(pool_pr2_subjob.get_output_ref("pooled"), paired_end)

    rep1_peaks_subjob = spp(rep1_ta,
                            rep1_control,
                            rep1_xcor)

    rep2_peaks_subjob = spp(rep2_ta,
                            rep2_control,
                            rep2_xcor)

    pooled_peaks_subjob = spp(pooled_replicates,
                              pooled_controls,
                              pooled_replicates_xcor_subjob.get_output_ref("CC_scores_file"))

    rep1pr1_peaks_subjob = spp(rep1_pr_subjob.get_output_ref("pseudoreplicate1"),
                                rep1_control,
                                rep1_pr1_xcor_subjob.get_output_ref("CC_scores_file"))

    rep1pr2_peaks_subjob = spp(rep1_pr_subjob.get_output_ref("pseudoreplicate2"),
                                rep1_control,
                                rep1_pr2_xcor_subjob.get_output_ref("CC_scores_file"))

    rep2pr1_peaks_subjob = spp(rep2_pr_subjob.get_output_ref("pseudoreplicate1"),
                                rep2_control,
                                rep2_pr1_xcor_subjob.get_output_ref("CC_scores_file"))

    rep2pr2_peaks_subjob = spp(rep2_pr_subjob.get_output_ref("pseudoreplicate2"),
                                rep2_control,
                                rep2_pr2_xcor_subjob.get_output_ref("CC_scores_file"))

    pooledpr1_peaks_subjob = spp(pool_pr1_subjob.get_output_ref("pooled"),
                                  pooled_controls,
                                  pool_pr1_xcor_subjob.get_output_ref("CC_scores_file"))

    pooledpr2_peaks_subjob = spp(pool_pr2_subjob.get_output_ref("pooled"),
                                  pooled_controls,
                                  pool_pr2_xcor_subjob.get_output_ref("CC_scores_file"))

    output = {
      'rep1_peaks':       rep1_peaks_subjob.get_output_ref("peaks"),
      'rep1_xcor_plot':   rep1_peaks_subjob.get_output_ref("xcor_plot"),
      'rep1_xcor_scores': rep1_peaks_subjob.get_output_ref("xcor_scores"),
      'rep2_peaks':       rep2_peaks_subjob.get_output_ref("peaks"),
      'rep2_xcor_plot':   rep2_peaks_subjob.get_output_ref("xcor_plot"),
      'rep2_xcor_scores': rep2_peaks_subjob.get_output_ref("xcor_scores"),
      'pooled_peaks':       pooled_peaks_subjob.get_output_ref("peaks"),
      'pooled_xcor_plot':   pooled_peaks_subjob.get_output_ref("xcor_plot"),
      'pooled_xcor_scores': pooled_peaks_subjob.get_output_ref("xcor_scores"),
      'rep1pr1_peaks':       rep1pr1_peaks_subjob.get_output_ref("peaks"),
      'rep1pr1_xcor_plot':   rep1pr1_peaks_subjob.get_output_ref("xcor_plot"),
      'rep1pr1_xcor_scores': rep1pr1_peaks_subjob.get_output_ref("xcor_scores"),
      'rep1pr2_peaks':       rep1pr2_peaks_subjob.get_output_ref("peaks"),
      'rep1pr2_xcor_plot':   rep1pr2_peaks_subjob.get_output_ref("xcor_plot"),
      'rep1pr2_xcor_scores': rep1pr2_peaks_subjob.get_output_ref("xcor_scores"),
      'rep2pr1_peaks':       rep2pr1_peaks_subjob.get_output_ref("peaks"),
      'rep2pr1_xcor_plot':   rep2pr1_peaks_subjob.get_output_ref("xcor_plot"),
      'rep2pr1_xcor_scores': rep2pr1_peaks_subjob.get_output_ref("xcor_scores"),
      'rep2pr2_peaks':       rep2pr2_peaks_subjob.get_output_ref("peaks"),
      'rep2pr2_xcor_plot':   rep2pr2_peaks_subjob.get_output_ref("xcor_plot"),
      'rep2pr2_xcor_scores': rep2pr2_peaks_subjob.get_output_ref("xcor_scores"),
      'pooledpr1_peaks':       pooledpr1_peaks_subjob.get_output_ref("peaks"),
      'pooledpr1_xcor_plot':   pooledpr1_peaks_subjob.get_output_ref("xcor_plot"),
      'pooledpr1_xcor_scores': pooledpr1_peaks_subjob.get_output_ref("xcor_scores"),
      'pooledpr2_peaks':       pooledpr2_peaks_subjob.get_output_ref("peaks"),
      'pooledpr2_xcor_plot':   pooledpr2_peaks_subjob.get_output_ref("xcor_plot"),
      'pooledpr2_xcor_scores': pooledpr2_peaks_subjob.get_output_ref("xcor_scores"),
    }

    return output

dxpy.run()
