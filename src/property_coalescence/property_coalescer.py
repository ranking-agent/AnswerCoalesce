from collections import defaultdict
from scipy.stats import hypergeom
from ast import literal_eval
import sqlite3
import os.path

from src.components import PropertyPatch

class PropertyLookup():
    def __init__(self):
        # Right now, we're going to load the property file, but we should replace with a redis or sqlite
        self.thisdir = os.path.dirname(os.path.realpath(__file__))
        #dbfiles = list(filter(lambda x: x.endswith('.db'), os.listdir(thisdir)))
        #self.propfiles = [f'{thisdir}/{dbf}' for dbf in dbfiles]
    #def fix_stype(self,stype):
    #    #We're in a situation where there are databases using old style types but the input will be new style, and
    #    #for a moment we need to translate.  This will go away.
    #    if isinstance(stype, list):
    #        for i, item in enumerate(stype):
    #            if item.startswith('biolink'):
    #                pascal = item.split(':')[1]
    #                stype[i] = re.sub(r'(?<!^)(?=[A-Z])', '_', pascal).lower()
    #    elif stype.startswith('biolink'):
    #        pascal = stype.split(':')[1]
    #        stype = re.sub(r'(?<!^)(?=[A-Z])', '_', pascal).lower()
    #    return stype
    def lookup_property_by_node(self,node,stype):
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
    def total_nodes_with_property(self,property,stype):
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
    def get_nodecount(self, stype):
        pf = f'{self.thisdir}/{stype.replace(":", ".")}.db'
        if not os.path.exists(pf):
            return 0
        with sqlite3.connect(pf) as conn:
            cur = conn.execute('SELECT count(node) from properties' )
        results = cur.fetchall()
        return results[0][0]
    def collect_properties(self,nodes, stype):
        """
        given a list of curies, go somewhere and find out all of the properties that two or more
        of the nodes share.  Return a dict from the shared property to the nodes.
        """
        prop2nodes = defaultdict(list)
        for node in nodes:
            properties = self.lookup_property_by_node(node,stype)
            for prop in properties:
                prop2nodes[prop].append(node)
        returnmap = {}
        for prop, nodelist in prop2nodes.items():
            if len(nodelist) > 1:
                returnmap[prop] = frozenset(nodelist)
        return returnmap

def coalesce_by_property(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []
    for opportunity in opportunities:
        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()
        enriched_properties = get_enriched_properties(nodes,stype)
        #There will be multiple ways to combine the same curies
        # group by curies.
        c2e = defaultdict(list)
        for ep in enriched_properties:
            c2e[ep[5]].append(ep)
        #now construct a patch for each curie set.
        for curieset,eps in c2e.items():
            # newprops = {'coalescence_method':'property_enrichment',
            #             'p_values': [x[0] for x in eps],
            #             'properties': [x[1] for x in eps]}

            attributes = []

            attributes.append({'attribute_type_id': 'biolink:has_attribute',
                         'value': 'property_enrichment',
                         'value_type_id': 'EDAM:operation_0004',
                         'original_attribute_name': 'coalescence_method'})

            attributes.append({'attribute_type_id': 'biolink:has_numeric_value',
                               'value': [x[0] for x in eps],
                               'value_type_id': 'EDAM:data_1669',
                               'original_attribute_name': 'p_value'})

            attributes.append({'attribute_type_id': 'biolink:has_attribute',
                               'value': [x[1] for x in eps],
                               'value_type_id': 'EDAM:data_0006',
                               'original_attribute_name': 'properties'})

            attributes.append({'attribute_type_id': 'biolink:has_attribute',
                               'value': ['biolink:has_role'],
                               'value_type_id': 'EDAM:data_0006',
                               'original_attribute_name': 'predicates'})

            newprops = {'attributes': attributes}

            patch = PropertyPatch(qg_id,curieset,newprops,opportunity.get_answer_indices())
            patches.append(patch)
    return patches

def get_enriched_properties(nodes,semantic_type,pcut=1e-4):
    if semantic_type in ['biolink:SmallMolecule','biolink:MolecularMixture','biolink:Drug']:
        semantic_type = 'biolink:ChemicalEntity'
    if semantic_type not in ['biolink:ChemicalEntity']:
        return []
    property_lookup = PropertyLookup()
    properties = property_lookup.collect_properties(nodes,semantic_type)  # properties = {property: (curies with it)}
    enriched = []
    for property, curies in properties.items():
        # The hypergeometric distribution models drawing objects from a bin.
        # M is the total number of objects (nodes) ,
        # n is total number of Type I objects (nodes with that property).
        # The random variate represents the number of Type I objects in N drawn
        #  without replacement from the total population (len curies).
        x = len(curies)  # draws with the property
        total_node_count = property_lookup.get_nodecount(semantic_type)
        n = property_lookup.total_nodes_with_property(property,semantic_type)
        ndraws = len(nodes)
        enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)
        if enrichp < pcut:
            enriched.append( (enrichp, property, ndraws, n, total_node_count, curies) )
    enriched.sort()
    return enriched



