from src.ontology_coalescence.triplestore import TripleStore
from src.util import Text
#from collections import defaultdict
#from functools import reduce

class UberGraph:

    def __init__(self):
        self.triplestore = TripleStore("https://stars-app.renci.org/uberongraph/sparql")

    def get_superclasses_of(self,iri):
        text="""
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix UBERON: <http://purl.obolibrary.org/obo/UBERON_>
        prefix CL: <http://purl.obolibrary.org/obo/CL_>
        prefix GO: <http://purl.obolibrary.org/obo/GO_>
        prefix CHEBI: <http://purl.obolibrary.org/obo/CHEBI_>
        prefix MONDO: <http://purl.obolibrary.org/obo/MONDO_>
        prefix HP: <http://purl.obolibrary.org/obo/HP_>
        select distinct ?ancestor 
        from <http://reasoner.renci.org/ontology>
        where {
            graph <http://reasoner.renci.org/ontology/closure> {
                $sourcedefclass rdfs:subClassOf ?ancestor .
            }
        }
        """
        rr = self.triplestore.query_template(
            inputs  = { 'sourcedefclass': iri  }, \
            outputs = [ 'ancestor' ], \
            template_text = text \
        )
        results = []
        for x in rr:
            results.append(Text.opt_to_curie(x['ancestor']))
        return results

    def count_subclasses_of(self,iri):
        text="""
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix UBERON: <http://purl.obolibrary.org/obo/UBERON_>
        prefix CL: <http://purl.obolibrary.org/obo/CL_>
        prefix GO: <http://purl.obolibrary.org/obo/GO_>
        prefix CHEBI: <http://purl.obolibrary.org/obo/CHEBI_>
        prefix MONDO: <http://purl.obolibrary.org/obo/MONDO_>
        prefix HP: <http://purl.obolibrary.org/obo/HP_>
        select (COUNT( DISTINCT ?x) AS ?subclass_count) 
        from <http://reasoner.renci.org/ontology>
        where {
            graph <http://reasoner.renci.org/ontology/closure> {
                ?x rdfs:subClassOf $sourcedefclass  .
            }
        }
        """
        rr = self.triplestore.query_template(
            inputs  = { 'sourcedefclass': iri  }, \
            outputs = [ 'subclass_count' ], \
            template_text = text \
        )
        return int(rr[0]['subclass_count'])
