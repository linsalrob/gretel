import argparse
import numpy as np

from hansel import Hansel
import gretel
import util

def main():
    parser = argparse.ArgumentParser(description="Gretel: A metagenomic haplotyper.")
    parser.add_argument("bam")
    parser.add_argument("vcf")
    parser.add_argument("contig")
    #parser.add_argument("-s", "--start", type=int, default=1, help="1-indexed start base position [default: 1]")
    parser.add_argument("-e", "--end", type=int, default=-1, help="1-indexed end base position [default: contig end]")

    parser.add_argument("-l", "--lorder", type=int, default=1, help="Order of markov chain to predict next nucleotide [default:1]")
    parser.add_argument("-p", "--paths", type=int, default=100, help="Maximum number of paths to generate [default:100]")

    parser.add_argument("--genes", default=None, help="Input genes for verification")
    parser.add_argument("--hit", default=None, help="Hit table for verification")
    parser.add_argument("--master", default=None, help="Master sequence if available")

    parser.add_argument("--quiet", default=False, action='store_true', help="Don't output anything other than a single summary line.")

    ARGS = parser.parse_args()

    # Process hit table and FASTA reference (if provided)
    HITS = []
    REFS = None
    REF_NAMES = []
    if ARGS.hit and ARGS.genes:
        HITS = gretel.process_hits(ARGS.hit)
        REFS = gretel.process_refs(ARGS.genes)
        REF_NAMES = list(REFS.references)


    VCF_h = gretel.process_vcf(ARGS.vcf, ARGS.contig, 1, ARGS.end)
    BAM_h = gretel.process_bam(VCF_h, ARGS.bam, ARGS.contig, ARGS.lorder)

    #print "[META] #CONTIG", ARGS.contig
    #print "[META] #SNPS", VCF_h["N"]
    #print "[META] #READS", BAM_h["N"]

    PATHS = []
    PATH_PROBS = []
    PATH_PROBS_UW = []

    # Spew out exciting information about the SNPs
    all_marginals = {
        "A": [],
        "C": [],
        "G": [],
        "T": [],
        "N": [],
        "_": [],
        "total": [],
    }
    if not ARGS.quiet:
        print "i\tpos\tgap\tA\tC\tG\tT\tN\t_\ttot"
        last_rev = 0
        for i in range(0, VCF_h["N"]+1):
            marginal = BAM_h["read_support"].get_counts_at(i)
            snp_rev = 0
            if i > 0:
                snp_rev = VCF_h["snp_rev"][i-1]
            print "%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%d" % (
                i,
                snp_rev,
                snp_rev - last_rev,
                marginal.get("A", 0),
                marginal.get("C", 0),
                marginal.get("G", 0),
                marginal.get("T", 0),
                marginal.get("N", 0),
                marginal.get("_", 0),
                marginal.get("total", 0),
            )
            all_marginals["A"].append(marginal.get("A", 0))
            all_marginals["C"].append(marginal.get("C", 0))
            all_marginals["G"].append(marginal.get("G", 0))
            all_marginals["T"].append(marginal.get("T", 0))
            all_marginals["N"].append(marginal.get("N", 0))
            all_marginals["_"].append(marginal.get("_", 0))
            all_marginals["total"].append(
                marginal.get("total", 0)
            )
            last_rev = snp_rev


    # Make some genes
    SPINS = ARGS.paths
    for i in range(0, SPINS):
        init_path, init_prob, init_min = gretel.establish_path(VCF_h["N"], BAM_h["read_support"], BAM_h["read_support_o"])
        if init_path == None:
            break
        current_path = init_path
        gretel.add_ignore_support3(BAM_h["read_support"], VCF_h["N"], init_path, init_min)
        PATHS.append(current_path)
        PATH_PROBS.append(init_prob["weighted"])
        PATH_PROBS_UW.append(init_prob["unweighted"])


    # Make some pretty pictures
    if ARGS.master:
        master_fa = util.load_fasta(ARGS.master)
        master_seq = master_fa.fetch(master_fa.references[0])
        fasta_out_fh = open("out.fasta", "w")

        for i, path in enumerate(PATHS):
            seq = list(master_seq)
            for j, mallele in enumerate(path[1:]):
                snp_pos_on_master = VCF_h["snp_rev"][j]
                try:
                    seq[snp_pos_on_master-1] = mallele
                except IndexError:
                    print path, len(seq), snp_pos_on_master-1
                    import sys; sys.exit(1)
            fasta_out_fh.write(">%d__%.2f\n" % (i, PATH_PROBS[i]))
            fasta_out_fh.write("%s\n" % "".join(seq))
        fasta_out_fh.close()

    #TODO None for ARGS
    if HITS and REFS:
        con_mat, snp_mat, seen_mat, master_mat, full_confusion = gretel.confusion_matrix(PATHS, VCF_h, HITS, REFS, REF_NAMES, VCF_h["N"], ARGS.master)

        if not ARGS.quiet:
            print "#\tname\tsites\trate\tbestit0\trefd\tlogl\tmap"
        RECOVERIES = []
        RECOV_PCTS = []

        for i in range(0, len(con_mat)):
            recovered = 0.0
            at = None
            for j in range(0, len(con_mat[i])):
                if con_mat[i][j] > recovered:
                    recovered = con_mat[i][j]
                    at = j
            if at != None:
                RECOVERIES.append((at, recovered))
                if not ARGS.quiet:
                    print "%d\t%s\t%d\t%.2f\t%d\t%d\t%.2f\t%s" % (
                            i,
                            REF_NAMES[i][1:31],
                            np.mean(seen_mat[i]),
                            recovered,
                            at,
                            np.sum(master_mat[i][at]),
                            PATH_PROBS_UW[at],
                            "".join([str(int(n)) for n in full_confusion[i][at]]),
                    )
            RECOV_PCTS.append(recovered)
        if ARGS.quiet:
            print "%.2f %.2f %.2f" % (min(RECOV_PCTS), max(RECOV_PCTS), np.mean(RECOV_PCTS))

        if not ARGS.quiet:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(2,1,sharex=True)
            x_ax = range(0, len(PATHS))
            ax[0].set_title("Gene Identity Recovery by Iteration")
            for i in range(0, len(REFS)):
                ax[0].plot(x_ax, con_mat[i], linewidth=2.0, alpha=0.75)
            ax[0].set_ylabel("Identity (%)")
            ax[0].set_ylim(0, 100)

            PATH_PROBS_RATIO = []
            for i, p in enumerate(PATH_PROBS):
                try:
                    PATH_PROBS_RATIO.append( PATH_PROBS[i] / PATH_PROBS_UW[i] )
                except:
                    PATH_PROBS_RATIO.append(0)
            # Add likelihood
            ax[1].plot(x_ax, PATH_PROBS, color="red", linewidth=3.0)
            ax[1].plot(x_ax, PATH_PROBS_UW, color="green", linewidth=3.0)
            ax[1].set_ylabel("Log(P)")
            ax[1].set_title("Path Likelihood by Iteration")

            #ax[2].plot(x_ax, PATH_PROBS_RATIO, color="blue", linewidth=3.0)
            ax[1].set_xlabel("Iteration (#)")

            # Add recoveries
            for r in RECOVERIES:
                ax[0].axvline(r[0], color='k', linewidth=2.0, alpha=r[1]/100.0)
                ax[1].axvline(r[0], color='k', linewidth=2.0, alpha=r[1]/100.0)
                #ax[2].axvline(r, color='k', linestyle='--')
            plt.show()

            """
            for i in range(0, len(REFS)):
                plt.pcolor(snp_mat[i], cmap=plt.cm.Blues)
                plt.show()
            for i in range(0, len(PATHS)):
                plt.pcolor(snp_mat[i], cmap=plt.cm.Blues)
                print snp_mat[i]
                plt.show()

            running_bottom = None
            plt.bar(range(0, VCF_h["N"]+1), np.array(all_marginals["A"])/np.array(all_marginals["total"]), color="blue")
            running_bottom = np.array(all_marginals["A"])/np.array(all_marginals["total"])

            plt.bar(range(0, VCF_h["N"]+1), np.array(all_marginals["C"])/np.array(all_marginals["total"]), bottom=running_bottom, color="green")
            running_bottom += np.array(all_marginals["C"])/np.array(all_marginals["total"])

            plt.bar(range(0, VCF_h["N"]+1), np.array(all_marginals["G"])/np.array(all_marginals["total"]), bottom=running_bottom, color="red")
            running_bottom += np.array(all_marginals["G"])/np.array(all_marginals["total"])

            plt.bar(range(0, VCF_h["N"]+1), np.array(all_marginals["T"])/np.array(all_marginals["total"]), bottom=running_bottom, color="yellow")
            running_bottom += np.array(all_marginals["T"])/np.array(all_marginals["total"])

            plt.bar(range(0, VCF_h["N"]+1), np.array(all_marginals["N"])/np.array(all_marginals["total"]), bottom=running_bottom, color="black")
            plt.show()
            """
