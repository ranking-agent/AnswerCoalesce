from collections import defaultdict
from scipy.stats import hypergeom
from ast import literal_eval
import sqlite3
import os.path
import logging
from src.util import LoggingUtil

this_dir = os.path.dirname(os.path.realpath(__file__))
logger = LoggingUtil.init_logging('property_coalescer', level=logging.WARNING, format='long',
                                  logFilePath=this_dir + '/')


async def coalesce_by_property( input_ids: list, input_node_type: str, property_constraints: list = None,
                                pvalue_threshold: float = None ) -> list:
    """
    Given a list of input_ids for coalescence, find subset of the list with common CHEBI_ROLES then perform enrichment analysis
    input_node_type is the semantic_type for the input set
    properties_to_exclude allows us to avoid certain unwanted CHEBI_ROles
    pvalue_threshold gives the flexibility to cut off commonalities that occurs less likely
    """
    enriched_properties = get_enriched_properties(input_ids, input_node_type, property_constraints, pvalue_threshold)

    return enriched_properties


def get_enriched_properties( nodes, semantic_type, property_constraints=None, pvalue_threshold=None ):
    if semantic_type in ['biolink:SmallMolecule', 'biolink:MolecularMixture', 'biolink:Drug']:
        semantic_type = 'biolink:ChemicalEntity'
    if semantic_type not in ['biolink:ChemicalEntity']:
        return []

    BAD_PROPERTIES = ['CHEBI_ROLE_pharmaceutical', 'CHEBI_ROLE_drug', 'CHEBI_ROLE_pharmacological_role', "sp2_c",
                      "CHEBI_ROLE_biochemical_role", "sp_c", "halogen", "hetero_sp2_c", "oh_nh", 'rotb', 'o_n']

    if property_constraints:
        BAD_PROPERTIES = set(property_constraints).union(set(BAD_PROPERTIES))

    property_lookup = PropertyLookup()
    properties = property_lookup.collect_properties(nodes, semantic_type)  # properties = {property: (curies with it)}
    enriched = []

    for property, curies in properties.items():
        # The hypergeometric distribution models drawing objects from a bin.
        # M is the total number of objects (nodes) ,
        # n is total number of Type I objects (nodes with that property).
        # The random variate represents the number of Type I objects in N drawn
        #  without replacement from the total population (len curies).
        x = len(curies)  # draws with the property
        total_node_count = property_lookup.get_nodecount(semantic_type)
        n = property_lookup.total_nodes_with_property(property, semantic_type)

        if x > 0 and n == 0:
            logger.info(f"x == {x}; n == 0??? : {property} {semantic_type} ")
            continue

        ndraws = len(nodes)

        # I only care about things that occur more than by chance, not less than by chance
        if x < n * ndraws / total_node_count:
            logger.info(
                f"x == {x} < {n * ndraws / total_node_count} : {property} {semantic_type} occur less than by chance")
            continue

        enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)

        enriched.append(enrichment(enrichp, property, ndraws, n, total_node_count, curies, semantic_type))

    if pvalue_threshold:
        enriched = [enrich for enrich in enriched if enrich.get("p_value") < pvalue_threshold]

    # sifter enrichment results
    enriched = [enrich for enrich in enriched if enrich.get("enriched_property") not in BAD_PROPERTIES]

    enriched.sort(key=lambda x: x.get("p_value"))

    return enriched


class PropertyLookup():
    def __init__( self ):
        # Right now, we're going to load the property file, but we should replace with a redis or sqlite
        self.thisdir = os.path.dirname(os.path.realpath(__file__))

    def lookup_property_by_node( self, node, stype ):
        pf = f'{self.thisdir}/{stype.replace(":", ".")}.db'
        if not os.path.exists(pf):
            return {}
        with sqlite3.connect(pf) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute('SELECT propertyset from properties where node=?', (node,))
        results = cur.fetchall()
        if len(results) > 0:
            r = results[0]['propertyset']
            if r == 'set()':
                return {}
            return literal_eval(r)
        return {}

    def total_nodes_with_property( self, property, stype ):
        pf = f'{self.thisdir}/{stype.replace(":", ".")}.db'
        if not os.path.exists(pf):
            return 0
        with sqlite3.connect(pf) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute('SELECT count from property_counts where property=?', (property,))
        results = cur.fetchall()
        if len(results) > 0:
            return results[0]['count']
        return 0

    def get_nodecount( self, stype ):
        pf = f'{self.thisdir}/{stype.replace(":", ".")}.db'
        if not os.path.exists(pf):
            return 0
        with sqlite3.connect(pf) as conn:
            cur = conn.execute('SELECT count(node) from properties')
        results = cur.fetchall()
        return results[0][0]

    def collect_properties( self, nodes, stype ):
        """
        given a list of curies, go somewhere and find out all of the properties that two or more
        of the nodes share.  Return a dict from the shared property to the nodes.
        """
        prop2nodes = defaultdict(list)
        for node in nodes:
            properties = self.lookup_property_by_node(node, stype)
            for prop in properties:
                prop2nodes[prop].append(node)
        returnmap = {}
        for prop, nodelist in prop2nodes.items():
            if len(nodelist) > 1:
                returnmap[prop] = frozenset(nodelist)
        return returnmap


def enrichment( enrichp: float, property: str, ndraws: int, n: int, total_node_count: int, curies: frozenset,
                semantic_type: str ):
    return {
        "p_value": enrichp,
        "enriched_property": property,
        "linked_curies": curies,
        "semantic_type": semantic_type,
        "counts": [ndraws, n, total_node_count]
    }


def lookup_nodes_by_properties( results, stype, return_nodeset=False ):
    properties = [result.get("enriched_property") for result in results]

    thisdir = os.path.dirname(os.path.realpath(__file__))
    pf = f'{thisdir}/{stype.replace(":", ".")}.db'
    if not os.path.exists(pf):
        return {}

    with sqlite3.connect(pf) as conn:
        conn.row_factory = sqlite3.Row

        # Construct the SQL query
        conditions = " OR ".join(["INSTR(propertyset, ?) > 0"] * len(properties))
        sql_query = f'SELECT node, propertyset FROM properties WHERE {conditions}'

        cur = conn.execute(sql_query, properties)
        rows = cur.fetchall()

    results_dicts = {result["enriched_property"]: result for result in results}

    response = {prop: {
        "p_value": results_dicts.get(prop).get("p_value"),
        "enriched_property": prop,
        "linked_curies": results_dicts.get(prop).get("linked_curies"),
        "semantic_type": results_dicts.get(prop).get("semantic_type"),
        "lookup_links": [],
        "counts": results_dicts.get(prop).get("counts")
    } for prop in properties}

    nodeset = set()
    for row in rows:
        node = row['node']
        propertyset = row['propertyset']
        for prop in properties:
            if prop in propertyset:
                if node in response[prop]["linked_curies"]:
                    continue
                response[prop]["lookup_links"].append(node)
                nodeset.add(node)

    if return_nodeset:
        return response, nodeset

    return response
