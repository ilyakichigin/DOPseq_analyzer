#!/usr/bin/env python

import os
import sys
import yaml
import argparse

from yaml import safe_load
from pysam import faidx

from dopseq.tools import \
    fastq_clean, \
    fastq_aln, \
    contam_filter, \
    bam_to_bed, \
    sample_stat, \
    fastq_repexpl, \
    utils


def parse_command_line_arguments():

    parser = argparse.ArgumentParser(description=
                    '''Infer chromosomal regions from isolated chromosome
                    sequencing data.

                    See config for process description, inputs and outputs.
                    '''
                    )
    parser.add_argument('config_file', help='input configuration file')
    parser.add_argument('-c', '--create_makefile',
                        action='store_true', default=False,
                        help='create example makefile')
    parser.add_argument('-d', '--dry_run', action='store_true', default=False,
                        help='check dependencies and print out commands')
    parser.add_argument('-s', '--sizes',
                        action='store_true', default=False,
                        help='print out chromosome sizes for target_genome '
                             'fasta specified in configuration file')

    return parser.parse_args()


def generate_filenames(sample, target_path, contam_path):
    """Given sample name, paths to target and contamination genomes
    return dictionary of output names for files generated by pipeline"""

    target_name = target_path.split('/')[-1].split('.')[0]
    contam_name = contam_path.split('/')[-1].split('.')[0]
    #sample = '%s/%s' % (sample, sample)

    names = {
        'f_trim_reads': '0_fastq/%s.ca.R1.fastq.gz' % sample,
        'r_trim_reads': '0_fastq/%s.ca.R2.fastq.gz' % sample,
        'ca_log': '0_fastq/log/%s.ca.log' % sample,
        'target_path': target_path,
        'contam_path': contam_path,
        'target_name': target_name,
        'contam_name': contam_name,
        'target_bam': '1_aln/%s.%s.bam' % (sample, target_name),
        'contam_bam': '1_aln/%s.%s.bam' % (sample, contam_name),
        'filter_bam': '2_filter/%s.%s.filter.bam' % (sample, target_name),
        'filter_log': '2_filter/%s.%s.filter.log' % (sample, target_name),
        'pos_bed': '3_bed/%s.%s.pos.bed' % (sample, target_name),
        'reg_tsv': '4_reg/%s.%s.reg.tsv' % (sample, target_name),
        'reg_pdf': '4_reg/%s.%s.reg.pdf' % (sample, target_name),
        'stat_file': '5_stats/%s.stats.txt' % sample,
        'repexpl_fasta': '6_fasta/%s.ca.re.fasta' % sample
        }

    return names


def main():

    args = parse_command_line_arguments()

    if args.create_makefile:
        examples_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                     'examples'))
        utils.copy_to_cwd(examples_dir,
                          'dopseq_makefile.yaml', args.config_file)
        sys.stderr.write('Copied example makefile for dopseq pipeline from %s to %s.\n'
                         'You can now fill it with your data and parameters, '
                         'then test ("-d" option) and run the pipeline.'
                         '\n' % (examples_dir, args.config_file))
        sys.exit(0)

    with open(args.config_file) as conf_file:
        conf = safe_load(conf_file)

    # if args.sizes:
    #     fai = conf['target_genome'] + '.fai'

    #     if not os.path.isfile(fai):
    #         faidx(conf['target_genome'])
    #     with open(fai) as f:
    #         for l in f:
    #             print '\t'.join(l.split()[:2])
    #     sys.exit(0)

    if args.dry_run:
        sys.stderr.write('This is a dry run. Only command listing '
                         'will be produced.\n')

    # assign default values for missing parameters
    if 'contam_genome' not in conf.keys():
        conf['contam_genome'] = conf['target_genome']
    if 'bowtie2_path' not in conf.keys():
        conf['bowtie2_path'] = 'bowtie2'
    if 'bwa_path' not in conf.keys():
        conf['bwa_path'] = 'bwa'
    if 'plot_height' not in conf.keys():
        conf['plot_height'] = 20
    if 'plot_width' not in conf.keys():
        conf['plot_width'] = 20
    # keep copy of default parameters
    default_conf = conf.copy()

    for sample in conf['samples']:
        sys.stderr.write('----Processing sample %s with dopseq pipeline----'
                         '\n' % sample)
        
        if not os.path.isdir(sample) and not args.dry_run:
            os.mkdir(sample)

        fnames = generate_filenames(sample,
                                    conf['target_genome'],
                                    conf['contam_genome'])
        # single-end input reads
        if 'fastq_R_file' not in conf['samples'][sample].keys():
            conf['samples'][sample]['fastq_R_file'] = None
            fnames['r_trim_reads'] = None
        for f in (conf['samples'][sample]['fastq_F_file'],
                  conf['samples'][sample]['fastq_R_file']):
            if f:
                utils.check_file(f)

        # reset parameters and override defaults
        conf = default_conf.copy()
        for param in conf['samples'][sample].keys():
            if not param.startswith('fastq_') and param in conf.keys():
                conf[param] = conf['samples'][sample][param]

        # check input files
        for f in (conf['contam_genome'], conf['target_genome'],
                  conf['sizes_file']):
            utils.check_file(f)

        # check executables
        if 'cutadapt_path' not in conf:
            conf['cutadapt_path'] = 'cutadapt'
        if 'bedtools_path' not in conf:
            conf['bedtools_path'] = 'bedtools'
        if conf['aln'] == 'bt2':
            aligner_path = conf['bowtie2_path']
            aligner_args = conf['bowtie2_args']
        elif conf['aln'] == 'bwa':
            aligner_path = conf['bwa_path']
            aligner_args = conf['bwa_args']
        else:
            raise ValueError('Invalid aligner %s!' % conf['aln'])
        for e in (conf['cutadapt_path'], aligner_path, conf['bedtools_path']):
            utils.check_exec(e)

        if not os.path.isfile(fnames['filter_bam']):

            sys.stderr.write('----fastq_clean.py----\n')
            if not os.path.isfile(fnames['f_trim_reads']):
                fc_args = argparse.Namespace(
                    sample=sample,
                    fastq_F_file=conf['samples'][sample]['fastq_F_file'],
                    fastq_R_file=conf['samples'][sample]['fastq_R_file'],
                    o=fnames['f_trim_reads'],
                    p=fnames['r_trim_reads'],
                    l=fnames['ca_log'],
                    dry_run=args.dry_run,
                    cutadapt_path=conf['cutadapt_path'],
                    trim_illumina=conf['trim_illumina'],
                    ampl=conf['ampl'],
                    params=conf['cutadapt_args'])
                fastq_clean.main(fc_args)
            else:
                sys.stderr.write('%s file with trimmed reads exists. '
                                 'OK!\n' % fnames['f_trim_reads'])
            sys.stderr.write('----Complete!----\n')

            sys.stderr.write('----fastq_aln.py----\n')

            for g in ('target', 'contam'):
                if os.path.isfile(fnames[g + '_bam']):
                    sys.stderr.write('%s alignment to %s genome exists. '
                                     'OK!\n' % (fnames[g + '_bam'], g))
                    continue
                fa_args = argparse.Namespace(
                    fastq_F_file=fnames['f_trim_reads'],
                    fastq_R_file=fnames['r_trim_reads'],
                    reference_genome=fnames[g + '_path'],
                    out_bam=fnames[g + '_bam'],
                    aligner=conf['aln'],
                    aligner_path=aligner_path,
                    aligner_args=aligner_args,
                    dry_run = args.dry_run)
                fastq_aln.main(fa_args)
            sys.stderr.write('----Complete!----\n')

            sys.stderr.write('----contam_filter.py----\n')
            cf_args = argparse.Namespace(
                target_bam=fnames['target_bam'],
                contam_bam=fnames['contam_bam'],
                out_bam=fnames['filter_bam'],
                stat_file=fnames['filter_log'],
                min_quality=conf['min_mapq'],
                min_length=conf['min_len'],
                keep_unmapped=False,
                dry_run = args.dry_run)
            contam_filter.main(cf_args)
            sys.stderr.write('----Complete!----\n')

        else:
            sys.stderr.write('%s filtered alignment to target genome exists. '
                             'Skipping read trimming, alignment, and '
                             'filtering.\n' % fnames['filter_bam'])

        sys.stderr.write('----bam_to_bed.py----\n')
        if not os.path.isfile(fnames['pos_bed']):
            btb_args = argparse.Namespace(
                in_bam=fnames['filter_bam'],
                out_bed=fnames['pos_bed'],
                bedtools_path=conf['bedtools_path'],
                dry_run = args.dry_run)
            bam_to_bed.main(btb_args)
        else:
            sys.stderr.write('%s BED file with merged read positions exists. '
                             'OK!\n' % fnames['pos_bed'])
        sys.stderr.write('----Complete!----\n')

        if not args.dry_run and os.stat(fnames['pos_bed']).st_size == 0:
            sys.stderr.write('No reads were retained in the alignment. '
                             'Skipping target region classification.\n')
        else:
            sys.stderr.write('----region_dnacopy.R----\n')
            if not os.path.isfile(fnames['reg_tsv']):
                exec_path = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                         "tools"))
                region_dnacopy_path = exec_path + '/region_dnacopy.R'
                rd_command = '%s %s %s %d %d %s %s' % (region_dnacopy_path,
                        fnames['pos_bed'],
                        conf['sizes_file'],
                        conf['plot_width'],
                        conf['plot_height'],
                        fnames['reg_tsv'],
                        fnames['reg_pdf'])
                utils.run_command(rd_command,
                   verbose=True, dry_run=args.dry_run,
                   outfile=None, errfile=None,
                   return_out=False)
            else:
                sys.stderr.write('%s chromosome region prediction file exists. '
                                 'OK!\n' % fnames['reg_tsv'])
            sys.stderr.write('----Complete!----\n')

        sys.stderr.write('----sample_stat.py----\n')
        if not os.path.isfile(fnames['stat_file']):
            ss_args = argparse.Namespace(
                ca_log=fnames['ca_log'],
                filter_log=fnames['filter_log'],
                pos_bed=fnames['pos_bed'],
                output=fnames['stat_file'],
                dry_run = args.dry_run)
            sample_stat.main(ss_args)
        else:
            sys.stderr.write('%s statistics file exist. '
                             'OK!\n' % fnames['stat_file'])
        sys.stderr.write('----Complete!----\n')

        if conf['fastq_repexpl']:
            if fnames['r_trim_reads'] == None:
                sys.stderr.write('Skipping RepeatExplorer fasta generation as '
                                 'single-end input reads were used.\n')
            else:
                sys.stderr.write('----fastq_repexpl.py----\n')
                if not os.path.isfile(fnames['repexpl_fasta']):
                    fr_args = argparse.Namespace(
                        f_fastq=fnames['f_trim_reads'],
                        r_fastq=fnames['r_trim_reads'],
                        out_fasta=fnames['repexpl_fasta'],
                        rename=True,
                        dry_run = args.dry_run)
                    fastq_repexpl.main(fr_args)
                else:
                    sys.stderr.write('%s file for RepeatExplorer exists. '
                                     'OK!\n' % fnames['repexpl_fasta'])
                sys.stderr.write('----Complete!----\n')

        sys.stderr.write('----Done processing sample %s with dopseq pipeline'
                         '----\n\n' % sample)

    if args.dry_run:
        sys.stderr.write('This was a dry run. Only command listing was '
                         'produced.\n')


if __name__ == '__main__':
    main()