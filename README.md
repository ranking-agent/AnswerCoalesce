[![Build Status](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce.svg?branch=master)](https://travis-ci.com/TranslatorIIPrototypes/AnswerCoalesce)

# AnswerCoalesce
### A web service and Swagger UI for the Answer Coalesce service for ARAGORN.

This service accepts [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) queries and returns coalesced answers using graph and property enrichment.

A live version of the API can be found [here](https://answercoalesce.renci.org/docs).


## Query Types

**Inference (EDGAR):** Single-curie queries with `knowledge_type: "inferred"`. Finds enriched associations via graph structure and chemical properties. The EDGAR UI is available at https://edgar-test.apps.renci.org/


**Multi-Curie (MCQ):** Queries with `set_interpretation: "MANY"` and `member_ids`. Finds shared enrichments across a set of input curies. The Enrichment UI is accessible at  https://robokop.renci.org/explore/enrichment-analysis

### Sample Inference Query

```json
{
  "message": {
    "query_graph": {
      "nodes": {
        "input": {"categories": ["biolink:Disease"], "ids": ["MONDO:0004975"]},
        "output": {"categories": ["biolink:Drug"]}
      },
      "edges": {
        "edge_0": {
          "subject": "output",
          "object": "input",
          "predicates": ["biolink:treats"],
          "knowledge_type": "inferred",
          "qualifier_constraints": [{"qualifier_set": [
            {"qualifier_type_id": "biolink:species_context_qualifier",
             "qualifier_value": "NCBITaxon:9606"}
          ]}]
        }
      }
    }
  },
  "parameters": {
    "pvalue_threshold": 1e-05,
    "max_rules": 100,
    "predicate_constraint_style": "exclude",
    "predicate_constraints": ["biolink:causes", "biolink:biomarker_for"]
  }
}
```

### Sample MCQ Query

```json
{
  "message": {
    "query_graph": {
      "nodes": {
        "input": {
          "categories": ["biolink:Gene"],
          "ids": ["uuid:1"],
          "member_ids": ["NCBIGene:5111", "NCBIGene:8856", "NCBIGene:5290"],
          "set_interpretation": "MANY"
        },
        "output": {"categories": ["biolink:ChemicalEntity"]}
      },
      "edges": {
        "edge_0": {
          "subject": "input",
          "object": "output",
          "predicates": ["biolink:related_to"]
        }
      }
    }
  }
}
```

### Parameters

| Parameter | Type | Default | Description                                                       |
|---|---|---|-------------------------------------------------------------------|
| `pvalue_threshold` | float | `1e-5` | Maximum p-value for enrichment results                            |
| `max_results` | int | `2000` | Maximum number of results returned                                |
| `max_rules` | int | `100` | Maximum enrichment rules evaluated per inference query            |
| `predicate_constraints` | list[str] | `[]` | Predicates to include or exclude from enrichment                  |
| `predicate_constraint_style` | str | `"exclude"` | `"include"` or `"exclude"` — how to apply `predicate_constraints` |
| `property_constraints` | list[str] | `[]` | Property types to constrain property enrichment                   |
| `node_constraints` | list[str] | `[]` | Semantic types to constrain output nodes                          |

Query edges also support `qualifier_constraints` (e.g. `species_context_qualifier`, `object_aspect_qualifier`, `object_direction_qualifier`).

## Deployment

### Local

```bash
conda create -n answercoalesce python=3.12
conda activate answercoalesce
pip install -r requirements.txt
uvicorn src.server:APP --host 0.0.0.0 --port 6380
```

### Docker

```bash
docker-compose build
docker-compose up -d
```

### Kubernetes
Kubernetes configurations and helm charts can be found at:
https://github.com/helxplatform/translator-devops/answer-coalesce

## Building the Redis Database

The AC Redis database is built on Hatteras via a Slurm pipeline. See [`src/ac_pipeline/README.md`](src/ac_pipeline/README.md) for full setup, configuration, and usage instructions.

## Testing

```bash
conda create -n answercoalesce-test python=3.12
conda activate answercoalesce-test
pip install -r requirements-test.txt

# Unit tests (no Redis required)
pytest tests/test_inputs.py tests/test_redis_build.py

# Integration tests (requires Redis)
pytest -m nongithub tests/test_endpoints.py

# Profiling
PYTHONPATH=. python tests/test_profiling.py infer MONDO:0004975 biolink:treats biolink:Disease biolink:Drug --object
PYTHONPATH=. python tests/test_profiling.py mcq NCBIGene:5111,NCBIGene:8856,NCBIGene:5290 biolink:related_to biolink:Gene biolink:ChemicalEntity
```

## Usage

http://"host name or IP":"port"/docs
