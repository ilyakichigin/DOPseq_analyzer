#!/usr/bin/env python

import subprocess
import argparse
import os.path

import sys
exec_path = os.path.abspath(os.path.join(os.path.dirname(__file__),"..","exec"))
sys.path.append(exec_path)

import fastq_to_bam
import contam_filter
import bam_to_beds
import control_stats

def parse_command_line_arguments():

    parser = argparse.ArgumentParser(description=    
                    """
                    Pipeline for processing of sequencing data of DOP-PCR libraries from isolated chromosomes.
                    See config for process description, inputs and outputs. 
                    """
                    )
    parser.add_argument("config_file", help="input configuration file")
    #parser.add_argument("-d", "--dry-run", action="store_true",
    #                    help="Check all dependencies and print out all commands")
    
    return parser.parse_args()

def parse_config(config_file):
    
    conf = dict()
    
    with open(config_file) as infile:
        for line in infile:
            line = line[:line.find('#')] # removes comments
            line_list = line.split('=')
            if len(line_list) == 2:            
                conf[line_list[0]]=line_list[1].strip(' ')
            #elif len(line_list) == 1:
            #    raise Exception(line+"\n This line in config has no parameter setting and is not comment")
            elif len(line_list) > 2:
                raise Exception(line+"\n This line in config has too many '=' symbols")

    return conf

def run_script(command, run=False):

    # Err: Does not stop on errors from within
    sys.stderr.write(' '.join(command)+'\n') 
    process = subprocess.Popen(command) 
    process.wait()
    
if __name__ == '__main__':
    args = parse_command_line_arguments()
    conf = parse_config(args.config_file)
    #dry_run = args.dry_run
    # !need to add executables check!
    target_name = conf["target_genome"].split('/')[-1]
    contam_name = conf["contam_genome"].split('/')[-1]
    # Steps 1&2. fastq_to_bam and contam_filter if filetered bam does not exist.    
    base_name = '.'.join([conf['sample'],target_name,'filter'])
    filtered_bam_file = base_name+'.bam'
    if not os.path.isfile(filtered_bam_file):    
        # Step 1. Perform fastq_to_bam if resulting sam files do not exist.
        target_sam_file = '.'.join([conf['sample'],target_name,'sam'])
        contam_sam_file = '.'.join([conf['sample'],contam_name,'sam'])
        if ((not os.path.isfile(target_sam_file) and not os.path.isfile(contam_sam_file)) 
            or (os.path.getsize(target_sam_file) == 0)):
            fb_args = argparse.Namespace(fastq_F_file=conf['fastq_F_file'],fastq_R_file=conf['fastq_R_file'],
                                         sample_name=conf['sample'],target_genome=conf["target_genome"],
                                         contam_genome=conf["contam_genome"],proc_bowtie2=conf["proc_bowtie2"],
                                         path_to_cutadapt='cutadapt',path_to_bowtie2='bowtie2')
            assert os.path.isfile(conf['fastq_F_file'])
            assert os.path.isfile(conf['fastq_R_file'])
            sys.stderr.write('----fastq_to_bam.py----\n')
            fastq_to_bam.main(fb_args)
            sys.stderr.write('----Complete!----\n')
        cf_args = argparse.Namespace(target_file=target_sam_file,contam_file=contam_sam_file,
                                     min_quality=20,pre_sort_by_name=True)
        sys.stderr.write('----contam_filter.py----\n')        
        contam_filter.main(cf_args)
        sys.stderr.write('----Complete!----\n')
    # Step 3. Convert bam_to_beds with reads and positions if these files do not exist.
    reads_bed_file = base_name+'.reads.bed'
    pos_bed_file = base_name+'.pos.bed'
    if (not os.path.isfile(reads_bed_file) and not os.path.isfile(pos_bed_file)):
        btb_args = argparse.Namespace(bam_file=filtered_bam_file,path_to_bedtools='bedtools')
        sys.stderr.write('----bam_to_beds.py----\n')
        bam_to_beds.main(btb_args)
        sys.stderr.write('----Complete!----\n')
    # Step 3a. Calculate control_stats if these do not exist.
    stat_file = base_name+'.chrom.tsv'
    if not os.path.isfile(stat_file):
        cs_args = argparse.Namespace(bed_basename='.'.join([conf['sample'],target_name,'filter']),
                                     sizes_file=conf['sizes_file'])
        # redirect stdout to file and then return it back
        sys.stderr.write('----control_stats.py----\n')        
        saveout = sys.stdout        
        with open(stat_file,'w') as f:
            sys.stdout = f
            control_stats.main(cs_args)    
            sys.stdout = saveout
        sys.stderr.write('----Complete!----\n')
    # Step 3b. Draw control_plots.R if these do not exist.
    control_plot_file = base_name+'.chrom.pdf'
    if not os.path.isfile(control_plot_file):
        cp_command = [exec_path+'/control_plots.R',pos_bed_file,conf['sizes_file']]
        sys.stderr.write('----control_plots.R----\n')
        run_script(cp_command)
        sys.stderr.write('----Complete!----\n')
    # Step 4. Perform region_dnacopy.R if regions do not exist.
    regions_table = base_name+'.reg.tsv'
    regions_plot = base_name+'.reg.pdf'
    if not os.path.isfile(regions_table) or not os.path.isfile(regions_plot):
        # pdf height and width increased to get readable plot for all chromosomes 
        rd_command = [exec_path+'/region_dnacopy.R',pos_bed_file,conf['sizes_file'],'20','20']
        sys.stderr.write('----region_dnacopy.R----\n')
        run_script(rd_command)
        sys.stderr.write('----Complete!----\n')