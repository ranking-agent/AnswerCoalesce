from src.ontology_coalescence.triplestore import TripleStore
from src.util import Text
from collections import defaultdict
#from functools import reduce

class UberGraph:

    def __init__(self):
        self.triplestore = TripleStore("https://stars-app.renci.org/uberongraph/sparql")

    def get_superclasses_of(self,iris):
        irilist = " ".join(iris)
        text=f"""
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix UBERON: <http://purl.obolibrary.org/obo/UBERON_>
        prefix CL: <http://purl.obolibrary.org/obo/CL_>
        prefix GO: <http://purl.obolibrary.org/obo/GO_>
        prefix CHEBI: <http://purl.obolibrary.org/obo/CHEBI_>
        prefix MONDO: <http://purl.obolibrary.org/obo/MONDO_>
        prefix HP: <http://purl.obolibrary.org/obo/HP_>
        select distinct ?sourcedefclass ?ancestor 
        from <http://reasoner.renci.org/ontology>
        where {{
            VALUES ?sourcedefclass {{ {irilist} }}
            graph <http://reasoner.renci.org/ontology/closure> {{
                ?sourcedefclass rdfs:subClassOf ?ancestor .
            }}
        }}
        """
        rr = self.triplestore.query_template(
            #inputs  = { 'irilist': f'{{ {irilist} }}'}, \
            inputs = {}, \
            outputs = [ 'sourcedefclass', 'ancestor' ], \
            template_text = text \
        )
        results = defaultdict(list)
        for x in rr:
            #results[Text.opt_to_curie(x['sourcedefclass'])].append(Text.opt_to_curie(x['ancestor']))
            results[Text.opt_to_curie(x['ancestor'])].append(Text.opt_to_curie(x['sourcedefclass']))
        return results

    def count_subclasses_of(self,iriset):
        irilist = " ".join(list(iriset))
        text=f"""
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix UBERON: <http://purl.obolibrary.org/obo/UBERON_>
        prefix CL: <http://purl.obolibrary.org/obo/CL_>
        prefix GO: <http://purl.obolibrary.org/obo/GO_>
        prefix CHEBI: <http://purl.obolibrary.org/obo/CHEBI_>
        prefix MONDO: <http://purl.obolibrary.org/obo/MONDO_>
        prefix HP: <http://purl.obolibrary.org/obo/HP_>
        select ?sourcedefclass (COUNT( DISTINCT ?x) AS ?subclass_count) 
        from <http://reasoner.renci.org/ontology>
        where {{
            VALUES ?sourcedefclass {{ {irilist} }}
            graph <http://reasoner.renci.org/ontology/closure> {{
                ?x rdfs:subClassOf ?sourcedefclass  .
            }}
        }}
        group by $sourcedefclass
        """
        rr = self.triplestore.query_template(
            inputs = {} , \
            #inputs  = { 'sourcedefclass': iri  }, \
            outputs = [ 'sourcedefclass', 'subclass_count' ], \
            template_text = text \
        )
        counts = {}
        for x in rr:
            counts[Text.opt_to_curie(x['sourcedefclass'])] = int(x['subclass_count'])
        return counts
