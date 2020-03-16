from neo4j.v1 import GraphDatabase
import os

# Maybe make this a notebook?

def get_driver(url):
    driver = GraphDatabase.driver(url, auth=("neo4j", os.environ['NEO4J_PASSWORD']))
    return driver

def run_query(url,cypherquery):
    driver = get_driver(url)
    with driver.session() as session:
        results = session.run(cypherquery)
    return list(results)

def sourceq(url):
    q = 'match (a)-[x]->(b) where not a:Concept and not a:sequence_variant and not b:sequence_variant return a.id as aid, type(x) as tx,labels(a) as la,labels(b) as lb, count(distinct b) as cb'
    result = run_query(url,q)
    with open('asource.txt','w') as outf:
        outf.write('source_id\tedgetype\tsourcelabels\ttargetlabels\tcount\n')
        for r in result:
            outf.write(f'{r["aid"]}\t{r["tx"]}\t{r["la"]}\t{r["lb"]}\t{r["cb"]}\n')

def targetq(url):
    q = 'match (b)-[x]->(a) where not a:Concept and not a:sequence_variant and not b:sequence_variant return a.id as aid, type(x) as tx,labels(a) as la,labels(b) as lb, count(distinct b) as cb'
    result = run_query(url,q)
    with open('atarget.txt','w') as outf:
        outf.write('target_id\tedgetype\ttargetlabels\tsourcelabels\tcount\n')
        for r in result:
            outf.write(f'{r["aid"]}\t{r["tx"]}\t{r["la"]}\t{r["lb"]}\t{r["cb"]}\n')

def go():
    url = 'bolt://robokopdb2.renci.org:7687'
    sourceq(url)
    targetq(url)

if __name__ == '__main__':
    go()
