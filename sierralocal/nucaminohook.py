import subprocess
import os
from pathlib import Path
import csv
import re
from sierralocal.subtyper import Subtyper
from sierralocal.utils import get_input_sequences
import sys

class NucAminoAligner():
    """
    Initialize NucAmino for a specific input fasta file
    """
    def __init__(self):
        self.cwd = os.path.curdir

        items = os.listdir(Path(os.path.dirname(__file__)))
        self.nucamino_binary = None
        for name in items:
            if 'nucamino' in name and not (name.endswith('py') or name.endswith('pyc')):
                self.nucamino_binary = name
                break

        if self.nucamino_binary:
            print("Found NucAmino binary", self.nucamino_binary)
        else:
            sys.exit('Failed to locate NucAmino binary.  Please download binary from http://github.com/hivdb/nucamino/releases')

        self.tripletTable = self.generateTable()

        with open(Path(os.path.dirname(__file__))/'data'/'apobec.tsv','r') as csvfile:
            self.ApobecDRMs = list(csv.reader(csvfile, delimiter='\t'))

        self.PI_dict = self.prevalence_parser('PIPrevalences.tsv')
        self.RTI_dict = self.prevalence_parser('RTIPrevalences.tsv')
        self.INI_dict = self.prevalence_parser('INIPrevalences.tsv')

        #initialize gene map
        self.pol_start = 2085
        self.gene_map = self.create_gene_map()

        #initialize Subtyper class
        self.typer = Subtyper()

    def prevalence_parser(self, filename):
        '''
        Abstracted method for reading ARV prevalence TSV and returning a dictionary of these data.
        :param filename:  Name of TSV file to parse
        :return:  Dictionary of position-consensus-mutation-subtype keys to %prevalence in naive
                  populations
        '''
        handle = open(Path(os.path.dirname(__file__))/'data'/filename, 'r')
        table = csv.DictReader(handle, delimiter='\t')

        keys = [fn for fn in table.fieldnames if fn.endswith('Naive:%')]
        result = {}
        for row in table:
            for key in keys:
                value = float(row[key])
                subtype = key.split(':')[0]
                label = row['Pos'] + row['Cons'] + row['Mut'] + subtype
                result.update({label: value})
        return result


    def align_file(self, filename):
        '''
        Using subprocess to call NucAmino, generates an output .tsv containing mutation data for each sequence in the FASTA file
        '''
        self.inputname = filename
        self.outputname = os.path.splitext(filename)[0] + '.tsv'

        args = [
            Path(os.path.dirname(__file__))/self.nucamino_binary,
            "hiv1b",
            "-q",
            "-i", "{}".format(self.inputname),
            "-g=POL",
            "-o", "{}".format(self.outputname)
        ]
        popen = subprocess.Popen(args)
        popen.wait()


    def create_gene_map(self):
        """
        Returns a dictionary with the AMINO ACID position bounds for each gene in Pol,
        based on the HXB2 reference annotations.
        """
        # start and end nucleotide coordinates in HXB2 pol
        pol_nuc_map = {
            'PR': (2253, 2549),
            'RT': (2550, 3869),
            'IN': (4230, 5096)
        }
        convert = lambda x:int((x-self.pol_start)/3)
        pol_aa_map = {}
        for key, val in pol_nuc_map.items():
            pol_aa_map[key] = (convert(val[0]), convert(val[1]))
        return pol_aa_map


    def get_gene(self, firstAA):
        """
        Determines the first POL gene that is present in the query sequence, by virtue of gene breakpoints
        @param firstAA: the first amino acid position of the query sequence, as determined by NucAmino
        @return: list of length 1 with a string of the gene in the sequence
        """
        for gene, bounds in self.gene_map.items():
            if bounds[0] <= firstAA <= bounds[1]:
                return gene
        return None


    def get_mutations(self, fastaFileName):
        '''
        From the tsv output of NucAmino, parses and adjusts indices and returns as lists.
        :param fastaFileName:  FASTA input processed by NucAmino
        :return: list of sequence names, list of sequence mutation dictionaries.
        '''
        file_mutations = []
        file_genes = []
        file_firstlastNA = []
        file_trims = []
        sequence_headers = []
        
        # grab original sequences from input file
        with open(fastaFileName, 'r') as handle:
            sequence_list = get_input_sequences(handle)

        # open the NucAmino output file
        with open(os.path.splitext(fastaFileName)[0]+'.tsv', 'r') as nucamino_alignment:
            tsvin = csv.reader(nucamino_alignment, delimiter='\t')
            next(tsvin) #bypass the header row

            for idx, row in enumerate(tsvin): #iterate over sequences (1 per row)
                header, firstAA, lastAA, firstNA, lastNA, mutation_list = row[:6]
                sequence_headers.append(header)
                sequence = sequence_list[idx]  # NucAmino preserves input order

                # Let's use the gene map to figure the "reference position" for each gene
                # Nucamino outputs wonky positions, so calculate the shift so we can get positions relative to the
                #  start of each individual gene
                firstAA = int(firstAA)
                lastAA = int(lastAA)
                firstNA = int(firstNA)
                lastNA = int(lastNA)

                gene = self.get_gene(firstAA)
                shift = int(self.gene_map[gene][0])

                # parse mutation information:
                codon_list = []
                gene_muts = {}
                if len(mutation_list) > 0:
                    # generate data lists for each sequence
                    mutation_list = mutation_list.split(',')  # split list into individual mutations
                    for x in mutation_list:
                        # each entry takes the form [A-Z]+[0-9]+[A-Z]+:[ACGTN]{3}
                        mutation, codon = x.split(':')
                        p = int(re.search('\d+', mutation).group()) - shift  # AA position
                        consensus = mutation[0]

                        # obtain the mutation codon directly from the query sequence
                        index = 3*(p+shift-firstAA)
                        triplet = sequence[index:(index+3)]  #FIXME: isn't this equivalent to <codon>?
                        codon_list.append(triplet)
                        aa = '-' if triplet in ['~~~', '...'] else self.translateNATriplet(triplet)
                        gene_muts.update({p: (consensus, aa)})

                # subtype sequence
                subtype = self.typer.getClosestSubtype(sequence)
                #subtype = header.split('.')[2]

                # trim low quality leading and trailing nucleotides
                trimLeft, trimRight = self.trimLowQualities(
                    codon_list, shift, firstAA, lastAA, mutations=gene_muts, frameshifts=[], gene=gene, subtype=subtype
                )
                # if trimLeft + trimRight > 0:
                    # print(row[0], trimLeft, trimRight)
                trimmed_gene_muts = {k:v for (k,v) in gene_muts.items() if (k >= firstAA - shift + trimLeft) and (k <= lastAA - shift - trimRight)}

                # append everything to list of lists of the entire sequence set
                file_mutations.append(trimmed_gene_muts)
                file_genes.append(gene)
                file_firstlastNA.append((firstNA, lastNA))
                file_trims.append((trimLeft, trimRight))

        assert len(file_mutations) == len(sequence_headers), "error: length of mutations dicts is not the same as length of names"
        return sequence_headers, file_genes, file_mutations, file_firstlastNA, file_trims

    # BELOW is an implementation of sierra's Java algorithm for determining codon ambiguity
    
    """
    Translates a nucleotide triplet into its amino acid mixture or ambiguity.
    @param triplet: nucleotide sequence as a string
    @return: translation of the triplet as a string
    """
    def translateNATriplet(self, triplet):
        if len(triplet) != 3:
            return "X"
        if '~' in triplet:
            return "X"
        if triplet in self.tripletTable:
            return self.tripletTable[triplet]
        return "X"

    """
    Generates a dictionary of codon to amino acid mappings, including ambiguous combinations.
    @return tripletTable: codon to amino acid dictionary
    """
    def generateTable(self):
        codonToAminoAcidMap = {
            "TTT" : "F", "TTC" : "F", "TTA" : "L", "TTG" : "L", "CTT" : "L", "CTC" : "L", "CTA" : "L", "CTG" : "L", "ATT" : "I", "ATC" : "I", "ATA" : "I", "ATG" : "M", "GTT" : "V", "GTC" : "V", "GTA" : "V", "GTG" : "V", "TCT" : "S", "TCC" : "S", "TCA" : "S", "TCG" : "S", "CCT" : "P", "CCC" : "P", "CCA" : "P", "CCG" : "P", "ACT" : "T", "ACC" : "T", "ACA" : "T", "ACG" : "T", "GCT" : "A", "GCC" : "A", "GCA" : "A", "GCG" : "A", "TAT" : "Y", "TAC" : "Y", "TAA" : "*", "TAG" : "*", "CAT" : "H", "CAC" : "H", "CAA" : "Q", "CAG" : "Q", "AAT" : "N", "AAC" : "N", "AAA" : "K", "AAG" : "K", "GAT" : "D", "GAC" : "D", "GAA" : "E", "GAG" : "E", "TGT" : "C", "TGC" : "C", "TGA" : "*", "TGG" : "W", "CGT" : "R", "CGC" : "R", "CGA" : "R", "CGG" : "R", "AGT" : "S", "AGC" : "S", "AGA" : "R", "AGG" : "R", "GGT" : "G", "GGC" : "G", "GGA" : "G", "GGG" : "G"
        }
        nas = ["A","C","G","T","R","Y","M","W","S","K","B","D","H","V","N"]
        tripletTable = dict()
        for i in range(len(nas)):
            for j in range(len(nas)):
                for k in range(len(nas)):
                    triplet = nas[i] + nas[j] + nas[k]
                    codons = self.enumerateCodonPossibilities(triplet)
                    uniqueAAs = []
                    for codon in codons:
                        c = codonToAminoAcidMap[codon]
                        if c not in uniqueAAs:
                            uniqueAAs.append(c)
                    if len(uniqueAAs) > 4:
                        aas = "X"
                    else:
                        aas = ''.join(uniqueAAs)
                    tripletTable[triplet] = aas
        return tripletTable

    """
    Converts a potentially ambiguous nucleotide triplet into standard ATCG codons.
    @param triplet: nucleotide triplet as a string
    @return codonPossibilities: list of possible ATCG codons encoded by the triplet
    """
    def enumerateCodonPossibilities(self, triplet):
        ambiguityMap = {
            "A" : ["A"],
            "C" : ["C"],
            "G" : ["G"],
            "T" : ["T"],
            "R" : ["A","G"],
            "Y" : ["C","T"],
            "M" : ["A","C"],
            "W" : ["A","T"],
            "S" : ["C","G"],
            "K" : ["G","T"],
            "B" : ["C","G","T"],
            "D" : ["A","G","T"],
            "H" : ["A","C","T"],
            "V" : ["A","C","G"],
            "N" : ["A","C","G","T"]
        }
        codonPossibilities = []
        pos1 = triplet[0]
        pos2 = triplet[1]
        pos3 = triplet[2]
        for p1 in ambiguityMap[pos1]:
            for p2 in ambiguityMap[pos2]:
                for p3 in ambiguityMap[pos3]:
                    codonPossibilities.append(p1+p2+p3)
        return codonPossibilities
    
    """
    Filters low-quality leading and trailing nucleotides from a query.
    Removes large (length > SEQUENCE_TRIM_SITES_CUTOFF) low quality pieces.
    Low quality is defined as:
    (1) unusual mutation; or
    (2) 'X' in amino acid list; or
    (3) has a stop codon

    @param sequence: sequence
    @param firstAA: aligned position of first amino acid in query
    @param lastAA: aligned position of last amino acid in query
    @param mutations: list of mutations
    @param frameshifts: list of frameshifts
    @return: tuple of how many leading and trailing nucleotides to trim
    """
    def trimLowQualities(self, codon_list, shift, firstAA, lastAA, mutations, frameshifts, gene, subtype):
        SEQUENCE_SHRINKAGE_CUTOFF_PCNT = 30
        SEQUENCE_SHRINKAGE_WINDOW = 15
        SEQUENCE_SHRINKAGE_BAD_QUALITY_MUT_PREVALENCE = 0.1

        # print(mutations)
        # print(codon_list)

        badPcnt = 0
        trimLeft = 0
        trimRight = 0
        problemSites = 0
        sinceLastBadQuality = 0
        proteinSize = lastAA - firstAA + 1
        candidates = []
        invalidSites = [False for i in range(proteinSize)]

        # account for invalid sites
        for j, position in enumerate(mutations):
            idx = position - firstAA + shift
            # print(idx)
            if not self.isUnsequenced(codon_list[j]) and \
                    (self.getHighestMutPrevalence((position, mutations[position]), gene, subtype) < SEQUENCE_SHRINKAGE_BAD_QUALITY_MUT_PREVALENCE or
                     mutations[position][1] == 'X' or
                     self.isApobecDRM(gene, mutations[position][0], position, mutations[position][1]) or
                     self.isStopCodon(codon_list[j])):
                invalidSites[idx] = True

        # for fs in frameshifts:
        #     idx = fs.getPosition() - firstAA
        #     invalidSites[idx] = True

        # forward scan for trimming left
        for idx in range(0, proteinSize):
            if sinceLastBadQuality > SEQUENCE_SHRINKAGE_WINDOW:
                break
            elif invalidSites[idx]:
                problemSites += 1
                trimLeft = idx + 1
                badPcnt = problemSites * 100 / trimLeft if trimLeft > 0 else 0
                if badPcnt > SEQUENCE_SHRINKAGE_CUTOFF_PCNT:
                    candidates.append(trimLeft)
                sinceLastBadQuality = 0
            else:
                sinceLastBadQuality += 1
        trimLeft = candidates[-1] if len(candidates) > 0 else 0
        candidates = []

        #backward scan for trimming right
        problemSites = 0
        sinceLastBadQuality = 0
        for idx in range(proteinSize-1, -1, -1):
            if sinceLastBadQuality > SEQUENCE_SHRINKAGE_WINDOW:
                break
            elif invalidSites[idx]:
                problemSites += 1
                trimRight = proteinSize - idx
                badPcnt = problemSites * 100 / trimRight if trimRight > 0 else 0
                if badPcnt > SEQUENCE_SHRINKAGE_CUTOFF_PCNT:
                    candidates.append(trimRight)
                sinceLastBadQuality = 0
            else:
                sinceLastBadQuality += 1
        trimRight = candidates[-1] if len(candidates) > 0 else 0
        return (trimLeft, trimRight)

    """
    Determines whether a triplet is unsequenced (has more than one N or deletion).
    "NNN", "NN-", "NNG" should be considered as unsequenced region.
    """
    def isUnsequenced(self, triplet):
        return (triplet.replace("-", "N").count("N") > 1) #TODO: incorporate !isInsertion &&

    def isStopCodon(self, triplet):
        return ("*" in self.translateNATriplet(triplet))

    def isApobecDRM(self, gene, consensus, position, AA):
        ls = [row[0:3] for row in self.ApobecDRMs[1:]]
        if [gene, consensus, str(position)] in ls:
            i = ls.index([gene, consensus, str(position)])
            for aa in AA:
                if aa in self.ApobecDRMs[1:][i][3]:
                    return True
        return False

    def getHighestMutPrevalence(self, mutation, gene, subtype):
        """
        #TODO
        @param mutation: a tuple(?) representing a specific position in the amino acid sequence 
                         that may contain multiple amino acids (polymorphic)
        @param gene: PR, RT, or INT
        @param subtype: predicted from function()
        @return: prevalence of the most common amino acid encoded at this position within the 
                 subtype alignment
        """
        position, aaseq = mutation
        cons, aas = aaseq
        aas = aas.replace(cons, '')  # ignore consensus
        aas = aas.replace('*', '')  # remove stop codons
        
        prevalence = 0.
        for aa in aas:
            aaPrevalence = self.getMutPrevalence(position, cons, aa, gene, subtype)
            prevalence = max(prevalence, aaPrevalence)

        return prevalence

    def getMutPrevalence(self, position, cons, aa, gene, subtype):
        key2 = str(position)+str(cons)+str(aa)+subtype

        if gene == 'IN' and key2 in self.INI_dict:
            return self.INI_dict[key2]

        if gene == 'PR' and key2 in self.PI_dict:
            return self.PI_dict[key2]

        if gene == 'RT' and key2 in self.RTI_dict:
            return self.RTI_dict[key2]

        return 100.0


if __name__ == '__main__':
    test = NucAminoAligner()
    assert test.translateNATriplet("YTD") == "LF"
    assert test.isStopCodon("TAG") == True
    assert test.isStopCodon("TAA") == True
    assert test.isStopCodon("TGA") == True
    assert test.isStopCodon("NNN") == False

    assert test.isUnsequenced("NNN") == True
    assert test.isUnsequenced("NN-") == True
    assert test.isUnsequenced("NNG") == True
    assert test.isUnsequenced("NTG") == False

    print(test.getMutPrevalence(6, 'D', 'E', 'IN', "CRF01_AE"))
    print(test.getMutPrevalence(6, 'D', 'E', 'IN', "G"))
    print(test.getMutPrevalence(6, 'E', 'D', 'RT', "A"))

    print(test.gene_map)
    print(test.get_gene(594))