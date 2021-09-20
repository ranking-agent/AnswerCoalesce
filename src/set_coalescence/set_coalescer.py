from collections import defaultdict
from scipy.stats import hypergeom, poisson, binom, norm
from src.components import PropertyPatch
from src.util import LoggingUtil
import logging
import os
import redis
import json
import ast
import itertools


this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir+'/')

def coalesce_by_set(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]

    This simply acts as if the original question was "is_set = True" at each query node individually.  The question is
    whether we want to do that for all nodes, or just internal nodes...  Maybe we want to look at the query graph...

    For now, it's just everything.
    """
    patches = []

    logger.info(f'Start of processing. {len(opportunities)} opportunities discovered.')

    sf_cache = {}
    for opportunity in opportunities:
        logger.debug('Starting new opportunity')

        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()

        patch = PropertyPatch(qg_id,nodes,[],opportunity.get_answer_indices())
        patches.append(patch)
        logger.debug('end of opportunity')
    logger.info('All opportunities processed.')
    return patches