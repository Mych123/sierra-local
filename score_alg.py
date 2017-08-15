from hivdb import HIVdb
import os


""" score_drugs function iterates through each drug in the HIV database,
    with a given sequence it will calculate a score and store it within a resulting dictionary
    
    @param HIVdb: the database
    @param sequence: the given sequence
    @return result_dict: a dictionary holding the score results of each drug for the given sequence
"""
def score_drugs(HIVdb, sequence):
    result_dict = {}
    for drug in HIVdb.keys():
        score = score_single(HIVdb, drug, sequence)
        result_dict[drug] = score
    return result_dict



""" score_single function first checks if the drug is in the HIVdb
    if found, calculates score with a given drug and sequence according to Stanford algorithm

    @param drugname: name of the drug you want the score for
    @param sequence: user provided sequence of type str (tolerates whitespace on either side, will strip it out later)
    @return score: calculated drm mutation score
"""
def score_single(HIVdb, drugname, sequence):
    assert drugname in HIVdb.keys(), "Drugname: %s not found." % drugname
    print(drugname)
    score = 0
    for condition in HIVdb[drugname]:
        # list of potential scores
        candidates = [0]
        values = []
        residueAAtuples = []

        for gv_pairs in condition:
            # 'AND' or 'single-drm' condition
            if isinstance(gv_pairs, str):
                if gv_pairs == 'value':
                    values.append(condition[gv_pairs])
                else:
                    residueAAtuples.append(condition[gv_pairs])
            # 'MAX' or 'MAXAND' condition
            else:
                for item in gv_pairs:
                    if item == 'value':
                        values.append(gv_pairs[item])
                    else:
                        residueAAtuples.append(gv_pairs[item])

        ## alternative method? Maintains associations between group-value pairs   --> may not work b/c problem of differentiating between keys
        # cond_dict = dict(zip(residueAAtuples, values))


        iter = 0  # iter is to keep track of the associated index in the values list
        for residueAA in residueAAtuples:
            count = 0  # count is to make sure all the tuples conditions within a residueAAtuples group is satisfied
            for tuple in residueAA:
                if not sequence[tuple[0] - 1] in tuple[1]:
                    print(sequence[tuple[0] - 1], 'is not in', tuple[1], 'at residue', tuple[0])
                    continue
                else:
                    print(sequence[tuple[0] -1] , 'present in', tuple[1], tuple[0])
                    count += 1
                if count == len(
                        residueAA):  # TODO: if IndexError, continue as well (don't throw error just because sequence isn't that long)
                    candidates.append(values[iter])
                    print(candidates)
            iter += 1

        # take the max of what's in the list of potential scores and update total score
        # doesn't matter for the single drm or combo condition because they only have one associated value anyways
        score += max(candidates)

    return score


""" test-harness """
def main():
    path = os.getcwd() + '/HIVDB.xml'
    algorithm = HIVdb(path)
    algorithm.parse_definitions(algorithm.root)
    database = algorithm.parse_drugs(algorithm.root)
    x = score_drugs(database, 'DAAAAAGAAEFHKJDLSHJDFKSLDHJFKSLAFLAHSJDKFLAHKDFLAHSASDFKASDFLASDJFKALSDFRETORJTIETGOENRTIEROTNOERNTIENTIERTERTERJDKFLASKDJFHAKSIEKRJRNNFMFMMMFJHAKDHJFKHJFKHDKJSHLFKJHSKFHDSHFJDHSFFMMFMFMFMDFLAKJSDHFALKSDJHFASKDJHFALSDKJFHAJSDKFLAKSDJFHJSDKFLAKSJDFHALSKDJFHAKSDJFHALKSDJFHLKSDJHFLAKSDJHFLAKDJFHALKSJDHFALKSJDHFKAJSDHFJSKLAFKSJDHFJAKSLFJDHSFLKAJHFALSKDJFHSLADKJFAHSJDFKAJDHFKSLGAAAATCTQAAAAAAAAAA')
    print(x)

main()

